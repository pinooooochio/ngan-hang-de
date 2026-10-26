"""Biên dịch PDF của đề chạy nền.

Mỗi file cần biên dịch là một dòng trong bảng `builds`, nên bảng này cũng là hàng đợi:
worker lấy dòng `pending`, biên dịch, lưu PDF vào thư mục file (biến NHD_FILES, mặc định ./files).
File .tex giống hệt một lần biên dịch thành công trước đó thì dùng lại PDF cũ (cache theo hash).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from . import render
from .compile import CompileResult, compile_tex
from .models import Build, BuildStatus, Exam

log = logging.getLogger(__name__)


def files_dir() -> Path:
    return Path(os.environ.get("NHD_FILES", "files"))


def exam_documents(exam: Exam) -> list[tuple[str, str, str | None, str]]:
    """Các file cần xuất của một đề: (tên, loại, mã đề, nội dung .tex)."""
    docs = []
    for v in exam.variants:
        docs.append((f"de-{v.code}", "de", v.code, render.render_exam(v.data, solutions=False)))
        docs.append((f"loigiai-{v.code}", "loigiai", v.code, render.render_exam(v.data, solutions=True)))
    docs.append(
        (
            "dapan",
            "dapan",
            None,
            render.render_answer_key(exam.title, exam.exam_date, [(v.data, v.answer_key) for v in exam.variants]),
        )
    )
    return docs


def tex_hash(tex: str) -> str:
    # Gộp cả nhd.sty vào hash: đổi định dạng thì không dùng lại PDF cũ
    style = (render.TEMPLATE_DIR / "nhd.sty").read_bytes()
    return hashlib.sha256(style + b"\0" + tex.encode()).hexdigest()


def queue_builds(session: Session, exam: Exam) -> list[Build]:
    """Xếp hàng biên dịch mọi file của đề (thay các lần trước). File nào nội dung không đổi
    so với lần biên dịch thành công trước thì dùng lại PDF ngay, không cần xếp hàng."""
    previous = {
        b.tex_hash: b.pdf_path
        for b in exam.builds
        if b.status == BuildStatus.DONE and b.pdf_path and Path(b.pdf_path).exists()
    }
    for b in list(exam.builds):
        session.delete(b)
    session.flush()
    out = []
    for name, kind, code, tex in exam_documents(exam):
        h = tex_hash(tex)
        b = Build(exam=exam, name=name, kind=kind, variant_code=code, tex=tex, tex_hash=h)
        if h in previous:
            target = Path(previous[h]).with_name(f"{name}.pdf")
            if target != Path(previous[h]):
                shutil.copyfile(previous[h], target)
            b.status = BuildStatus.DONE
            b.pdf_path = str(target)
            b.cached = True
            b.finished_at = datetime.now()
        session.add(b)
        out.append(b)
    session.commit()
    return out


def claim_next(session: Session) -> Build | None:
    """Lấy một việc đang chờ và đánh dấu đang chạy."""
    stmt = select(Build).where(Build.status == BuildStatus.PENDING).order_by(Build.id).limit(1)
    if session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    build = session.scalar(stmt)
    if build is None:
        session.commit()
        return None
    build.status = BuildStatus.RUNNING
    session.commit()
    return build


def run_build(session: Session, build: Build) -> Build:
    target_dir = files_dir() / "exams" / str(build.exam_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{build.name}.pdf"

    cached = session.scalar(
        select(Build)
        .where(Build.tex_hash == build.tex_hash, Build.status == BuildStatus.DONE, Build.id != build.id)
        .order_by(Build.id.desc())
        .limit(1)
    )
    if cached is not None and cached.pdf_path and Path(cached.pdf_path).exists():
        if Path(cached.pdf_path).resolve() != target.resolve():
            shutil.copyfile(cached.pdf_path, target)
        _finish(session, build, target, cached=True)
        return build

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        render.copy_style(folder)
        tex = folder / f"{build.name}.tex"
        tex.write_text(build.tex, encoding="utf-8")
        try:
            result = compile_tex(tex)
        except Exception as e:  # ví dụ thiếu latexmk
            result = CompileResult(False, None, str(e))
        if result.ok and result.pdf:
            shutil.move(str(result.pdf), target)
            _finish(session, build, target)
        else:
            build.status = BuildStatus.FAILED
            build.error = result.error
            build.error_question = result.question
            build.finished_at = datetime.now()
            session.commit()
    return build


def _finish(session: Session, build: Build, target: Path, cached: bool = False) -> None:
    build.status = BuildStatus.DONE
    build.pdf_path = str(target)
    build.cached = cached
    build.error = None
    build.error_question = None
    build.finished_at = datetime.now()
    session.commit()


def run_pending(session: Session) -> int:
    """Chạy hết các việc đang chờ (dùng cho dòng lệnh và test). Trả về số việc đã chạy."""
    n = 0
    while (build := claim_next(session)) is not None:
        run_build(session, build)
        n += 1
    return n


def reset_stale(session: Session) -> None:
    """Việc đang chạy dở khi máy chủ tắt thì đưa về hàng đợi."""
    session.execute(update(Build).where(Build.status == BuildStatus.RUNNING).values(status=BuildStatus.PENDING))
    session.commit()


def start_worker(session_factory: sessionmaker, stop: threading.Event, poll: float = 1.0) -> threading.Thread:
    """Chạy worker trong một luồng nền của máy chủ web."""

    def loop() -> None:
        with session_factory() as s:
            reset_stale(s)
        while not stop.is_set():
            try:
                with session_factory() as s:
                    build = claim_next(s)
                    if build is not None:
                        run_build(s, build)
                        continue
            except Exception:  # một lỗi bất ngờ không được làm dừng worker
                log.exception("worker biên dịch lỗi")
            stop.wait(poll)

    t = threading.Thread(target=loop, name="nhd-worker", daemon=True)
    t.start()
    return t
