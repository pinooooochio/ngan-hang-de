"""API web (FastAPI) cho ngân hàng câu hỏi. Chạy: `nhd serve`."""

from __future__ import annotations

import io
import random
import shutil
import tempfile
import threading
import zipfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from . import bank, builds, generator, practice, render
from .compile import compile_tex, latex_available
from .db import get_url
from .models import Attempt, Base, BuildStatus, Exam, Level, Question, QuestionType, Status
from .parser import ParsedQuestion, parse_text
from .serialize import NEW_TEMPLATE, question_to_ex

WEB_DIST = Path(__file__).parent / "web"


# ---------- Dữ liệu trả về ----------


def question_json(q: Question, full: bool = True) -> dict:
    data = {
        "code": q.code,
        "type": q.type.value,
        "level": q.level.value if q.level else None,
        "status": q.status.value,
        "stem": q.stem_latex,
        "tags": [{"path": t.path, "names": bank.tag_names(t)} for t in q.tags],
        "updated_at": q.updated_at.isoformat(timespec="seconds") if q.updated_at else None,
    }
    if full:
        data.update(
            choices=[{"content": c.content_latex, "correct": c.is_correct, "pinned": c.pinned} for c in q.choices],
            short_answer=q.short_answer,
            solution=q.solution_latex,
            source=q.source,
            ex_id=q.ex_id,
            version=q.version,
            ex_source=question_to_ex(q),
        )
    return data


def parsed_json(pq: ParsedQuestion) -> dict:
    return {
        "line": pq.line,
        "type": pq.type.value,
        "level": pq.level.value if pq.level else None,
        "code": pq.code,
        "tags": pq.tags,
        "stem": pq.stem,
        "choices": [{"content": c.content, "correct": c.is_correct, "pinned": c.pinned} for c in pq.choices],
        "short_answer": pq.short_answer,
        "solution": pq.solution,
        "errors": pq.errors,
        "warnings": pq.warnings,
    }


# ---------- Dữ liệu gửi lên ----------


class SourceIn(BaseModel):
    source: str


class SaveIn(BaseModel):
    source: str
    status: Status | None = None


class BulkIn(BaseModel):
    codes: list[str]
    add_tag: str | None = None  # "Lớp 12 / Vectơ"
    level: Level | None = None
    status: Status | None = None


class ImportIn(BaseModel):
    source: str
    filename: str | None = None
    only: list[int] | None = None
    extra_tag: str | None = None
    default_level: Level | None = None
    status: Status = Status.APPROVED


class PickIn(BaseModel):
    tag: str | None = None
    level: Level | None = None
    count: int = Field(1, ge=1, le=200)


class SectionIn(BaseModel):
    name: str = ""
    type: QuestionType
    points: float | None = None
    shuffle: bool = True
    pick: list[PickIn] = []
    ids: list[str] = []


class ExamIn(BaseModel):
    title: str = Field(min_length=1)
    date: str | None = None
    duration: int | None = None
    variants: int = Field(1, ge=1, le=30)
    first_code: int = 101
    seed: int | None = None
    sections: list[SectionIn] = Field(min_length=1)


class AvailabilityIn(BaseModel):
    sections: list[SectionIn]


def exam_spec(body: ExamIn) -> dict:
    """Chuyển dữ liệu gửi lên thành cấu hình đề giống file TOML của dòng lệnh."""
    data = body.model_dump(mode="json", exclude_none=True)
    data["seed"] = body.seed if body.seed is not None else random.randint(1, 10**6)
    data["section"] = data.pop("sections")
    return data


def build_json(exam_id: int, b) -> dict:
    return {
        "name": b.name,
        "kind": b.kind,
        "variant_code": b.variant_code,
        "status": b.status.value,
        "cached": b.cached,
        "error": b.error,
        "error_question": b.error_question,
        "url": f"/api/exams/{exam_id}/files/{b.name}.pdf" if b.status == BuildStatus.DONE else None,
    }


def exam_json(exam: Exam, full: bool = False) -> dict:
    counts = {s.value: 0 for s in BuildStatus}
    for b in exam.builds:
        counts[b.status.value] += 1
    data = {
        "id": exam.id,
        "title": exam.title,
        "date": exam.exam_date,
        "duration": exam.duration,
        "created_at": exam.created_at.isoformat(timespec="seconds"),
        "n_variants": len(exam.variants),
        "n_questions": len(exam.items),
        "builds": counts,
    }
    if full:
        data.update(
            config=exam.config,
            variants=[{"code": v.code, "answer_key": v.answer_key, "data": v.data} for v in exam.variants],
            files=[build_json(exam.id, b) for b in exam.builds],
        )
    return data


class QuickIn(BaseModel):
    title: str | None = None
    tag: str | None = None
    level: Level | None = None
    mcq: int = Field(0, ge=0, le=100)
    tf: int = Field(0, ge=0, le=50)
    short: int = Field(0, ge=0, le=50)
    essay: int = Field(0, ge=0, le=20)
    duration: int | None = Field(None, ge=1, le=600)


class AttemptIn(BaseModel):
    exam_id: int | None = None
    variant: str | None = None
    timed: bool = True
    quick: QuickIn | None = None
    retry_of: int | None = None


class AnswersIn(BaseModel):
    answers: dict[str, Any] = {}


def attempt_json(a: Attempt, full: bool = False) -> dict:
    end = practice.deadline(a)
    data = {
        "id": a.id,
        "kind": a.kind,
        "title": a.title,
        "exam_id": a.exam_id,
        "variant_code": a.variant_code,
        "duration": a.duration,
        "started_at": a.started_at.isoformat(timespec="seconds"),
        "deadline": end.isoformat(timespec="seconds") if end else None,
        "submitted_at": a.submitted_at.isoformat(timespec="seconds") if a.submitted_at else None,
        "late": practice.is_late(a),
        "score": a.score,
        "max_score": a.max_score,
        "n_questions": sum(len(s["questions"]) for s in a.data["sections"]),
    }
    if full:
        done = a.submitted_at is not None
        data["data"] = a.data if done else practice.public_data(a.data)
        data["answers"] = a.answers
        data["results"] = (
            {f"{it.section}.{it.position}": {"points": it.points, "max_points": it.max_points, "correct": it.correct} for it in a.items}
            if done
            else None
        )
        data["server_time"] = datetime.now().isoformat(timespec="seconds")
    return data


def split_tag(text: str | None) -> list[str] | None:
    if not text:
        return None
    names = [p.strip() for p in text.split("/") if p.strip()]
    return names or None


def parse_one(source: str) -> ParsedQuestion:
    parsed = parse_text(source)
    if len(parsed) != 1:
        raise HTTPException(422, f"cần đúng một khối \\begin{{ex}}...\\end{{ex}}, tìm thấy {len(parsed)}")
    return parsed[0]


# ---------- Ứng dụng ----------


def create_app(db_url: str | None = None, worker: bool = False) -> FastAPI:
    url = db_url or get_url()
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(engine)

    def get_session() -> Iterator[Session]:
        with SessionLocal() as s:
            yield s

    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if worker:
            builds.start_worker(SessionLocal, stop)
        yield
        stop.set()

    app = FastAPI(title="Ngân hàng đề", lifespan=lifespan)
    app.state.engine = engine
    S = Depends(get_session)

    @app.get("/api/questions")
    def list_questions(
        tag: str | None = None,
        level: Level | None = None,
        type: QuestionType | None = None,
        status: Status | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session: Session = S,
    ):
        stmt = bank.question_query(tag, level, type, status, q)
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(stmt.order_by(Question.updated_at.desc(), Question.id.desc()).limit(limit).offset(offset))
        return {"total": total, "items": [question_json(r, full=False) for r in rows]}

    @app.get("/api/questions/{code}")
    def get_question(code: str, session: Session = S):
        q = bank.get_question(session, code)
        if q is None:
            raise HTTPException(404, f"không có câu {code}")
        return question_json(q)

    @app.post("/api/questions", status_code=201)
    def create_question(body: SaveIn, session: Session = S):
        pq = parse_one(body.source)
        try:
            q = bank.create_question(session, pq, status=body.status or Status.DRAFT)
        except bank.BankError as e:
            raise HTTPException(422, str(e))
        return question_json(q)

    @app.put("/api/questions/{code}")
    def update_question(code: str, body: SaveIn, session: Session = S):
        pq = parse_one(body.source)
        try:
            q = bank.update_question(session, code, pq)
            if body.status:
                q.status = body.status
                session.commit()
        except bank.BankError as e:
            raise HTTPException(422, str(e))
        return question_json(q)

    @app.delete("/api/questions/{code}", status_code=204)
    def delete_question(code: str, session: Session = S):
        try:
            bank.delete_question(session, code)
        except bank.BankError as e:
            raise HTTPException(422, str(e))

    @app.post("/api/questions/bulk")
    def bulk(body: BulkIn, session: Session = S):
        n = bank.bulk_update(session, body.codes, split_tag(body.add_tag), body.level, body.status)
        return {"updated": n}

    @app.get("/api/template")
    def template():
        return {"source": NEW_TEMPLATE}

    @app.post("/api/parse")
    def parse(body: SourceIn):
        return [parsed_json(pq) for pq in parse_text(body.source)]

    @app.get("/api/tags")
    def tags(session: Session = S):
        return [
            {"path": n.path, "name": n.name, "depth": d, "count": c, "names": bank.tag_names(n)}
            for n, d, c in bank.tag_tree(session)
        ]

    @app.get("/api/stats")
    def stats(session: Session = S):
        by_level = dict(session.execute(select(Question.level, func.count()).group_by(Question.level)).all())
        by_status = dict(session.execute(select(Question.status, func.count()).group_by(Question.status)).all())
        return {
            "total": sum(by_status.values()),
            "by_level": {(k.value if k else "none"): v for k, v in by_level.items()},
            "by_status": {k.value: v for k, v in by_status.items()},
        }

    @app.post("/api/import/preview")
    def import_preview(body: SourceIn, session: Session = S):
        items = bank.preview_import(session, parse_text(body.source))
        return [
            {"index": it.index, "state": it.state, "duplicate_of": it.duplicate_of, **parsed_json(it.parsed)}
            for it in items
        ]

    @app.post("/api/import/commit")
    def import_commit(body: ImportIn, session: Session = S):
        report = bank.import_questions(
            session,
            parse_text(body.source),
            source=body.filename,
            status=body.status,
            only=set(body.only) if body.only is not None else None,
            extra_tag=split_tag(body.extra_tag),
            default_level=body.default_level,
        )
        return {"added": report.added, "duplicates": len(report.duplicates), "failed": len(report.failed)}

    @app.post("/api/preview/pdf")
    def preview_pdf(body: SourceIn):
        """Biên dịch thử một câu (kèm lời giải) ra PDF để xem đúng như khi in."""
        if not latex_available():
            raise HTTPException(503, "máy chủ chưa cài XeLaTeX")
        pq = parse_one(body.source)
        if pq.errors:
            raise HTTPException(422, "; ".join(pq.errors))
        item = {
            "code": pq.code or "MOI",
            "type": pq.type.value,
            "stem": pq.stem,
            "choices": [{"content": c.content, "correct": c.is_correct} for c in pq.choices],
            "short_answer": pq.short_answer,
            "solution": pq.solution,
        }
        data = {
            "title": "Xem trước câu hỏi",
            "date": "",
            "duration": None,
            "code": item["code"],
            "sections": [{"name": "", "type": pq.type.value, "points": None, "questions": [item]}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            render.copy_style(folder)
            tex = folder / "xemtruoc.tex"
            tex.write_text(render.render_exam(data, solutions=True), encoding="utf-8")
            result = compile_tex(tex)
            if not result.ok:
                raise HTTPException(422, f"Lỗi LaTeX: {result.error}")
            return Response(result.pdf.read_bytes(), media_type="application/pdf")

    # ---------- Đề thi ----------

    @app.post("/api/exams/availability")
    def availability(body: AvailabilityIn, session: Session = S):
        """Số câu đã duyệt hiện có cho từng dòng ma trận, và các mã câu chọn tay không dùng được."""
        out = []
        for sec in body.sections:
            rows = [
                len(bank.find_questions(session, tag=p.tag, level=p.level, type=sec.type, approved_only=True))
                for p in sec.pick
            ]
            problems = []
            for code in sec.ids:
                q = bank.get_question(session, code)
                if q is None:
                    problems.append(f"không có câu {code}")
                elif q.type != sec.type:
                    problems.append(f"câu {code} không đúng loại của phần này")
            out.append({"rows": rows, "problems": problems})
        return {"sections": out}

    @app.get("/api/exams")
    def list_exams(session: Session = S):
        exams = session.scalars(select(Exam).order_by(Exam.created_at.desc(), Exam.id.desc()))
        return [exam_json(e) for e in exams]

    @app.post("/api/exams", status_code=201)
    def create_exam(body: ExamIn, session: Session = S):
        try:
            exam = generator.build_exam(session, exam_spec(body))
        except generator.SpecError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        builds.queue_builds(session, exam)
        return exam_json(exam, full=True)

    def load_exam(session: Session, exam_id: int) -> Exam:
        exam = session.get(Exam, exam_id)
        if exam is None:
            raise HTTPException(404, f"không có đề #{exam_id}")
        return exam

    @app.get("/api/exams/{exam_id}")
    def get_exam(exam_id: int, session: Session = S):
        return exam_json(load_exam(session, exam_id), full=True)

    @app.post("/api/exams/{exam_id}/rebuild")
    def rebuild_exam(exam_id: int, session: Session = S):
        exam = load_exam(session, exam_id)
        builds.queue_builds(session, exam)
        return exam_json(exam, full=True)

    @app.delete("/api/exams/{exam_id}", status_code=204)
    def delete_exam(exam_id: int, session: Session = S):
        exam = load_exam(session, exam_id)
        # Lượt luyện giữ bản chụp đề riêng nên vẫn còn sau khi xoá đề
        for a in session.scalars(select(Attempt).where(Attempt.exam_id == exam_id)):
            a.exam_id = None
        session.delete(exam)
        session.commit()
        shutil.rmtree(builds.files_dir() / "exams" / str(exam_id), ignore_errors=True)

    def download_name(exam: Exam, name: str, ext: str) -> str:
        from .parser import slugify

        return f"{slugify(exam.title)}-{name}.{ext}"

    @app.get("/api/exams/{exam_id}/files/{name}.pdf")
    def download_pdf(exam_id: int, name: str, session: Session = S):
        exam = load_exam(session, exam_id)
        b = next((b for b in exam.builds if b.name == name and b.status == BuildStatus.DONE), None)
        if b is None or not b.pdf_path or not Path(b.pdf_path).exists():
            raise HTTPException(404, "file chưa có")
        return FileResponse(b.pdf_path, media_type="application/pdf", filename=download_name(exam, name, "pdf"))

    @app.get("/api/exams/{exam_id}/files.zip")
    def download_zip(exam_id: int, session: Session = S):
        exam = load_exam(session, exam_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for b in exam.builds:
                if b.status == BuildStatus.DONE and b.pdf_path and Path(b.pdf_path).exists():
                    z.write(b.pdf_path, f"{b.name}.pdf")
        headers = {"Content-Disposition": f'attachment; filename="{download_name(exam, "tat-ca", "zip")}"'}
        return Response(buf.getvalue(), media_type="application/zip", headers=headers)

    # ---------- Luyện đề ----------

    def load_attempt(session: Session, attempt_id: int) -> Attempt:
        a = session.get(Attempt, attempt_id)
        if a is None:
            raise HTTPException(404, f"không có lượt luyện #{attempt_id}")
        return a

    @app.post("/api/attempts", status_code=201)
    def start_attempt(body: AttemptIn, session: Session = S):
        try:
            if body.exam_id is not None:
                a = practice.start_from_exam(session, load_exam(session, body.exam_id), body.variant, body.timed)
            elif body.retry_of is not None:
                spec = practice.retry_spec(load_attempt(session, body.retry_of))
                a = practice.start_quick(session, spec)
            elif body.quick is not None:
                qk = body.quick
                counts = {"mcq": qk.mcq, "tf": qk.tf, "short": qk.short, "essay": qk.essay}
                spec = practice.quick_spec(qk.title, qk.tag, qk.level.value if qk.level else None, counts)
                a = practice.start_quick(session, spec, qk.duration)
            else:
                raise HTTPException(422, "cần exam_id, quick hoặc retry_of")
        except practice.PracticeError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return attempt_json(a, full=True)

    @app.get("/api/attempts")
    def list_attempts(exam_id: int | None = None, session: Session = S):
        q = select(Attempt).order_by(Attempt.started_at.desc(), Attempt.id.desc())
        if exam_id is not None:
            q = q.where(Attempt.exam_id == exam_id)
        return [attempt_json(a) for a in session.scalars(q)]

    @app.get("/api/attempts/stats")
    def attempt_stats(session: Session = S):
        return practice.stats(session)

    @app.get("/api/attempts/{attempt_id}")
    def get_attempt(attempt_id: int, session: Session = S):
        return attempt_json(load_attempt(session, attempt_id), full=True)

    @app.put("/api/attempts/{attempt_id}/answers", status_code=204)
    def save_answers(attempt_id: int, body: AnswersIn, session: Session = S):
        try:
            practice.save_answers(session, load_attempt(session, attempt_id), body.answers)
        except practice.PracticeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/attempts/{attempt_id}/submit")
    def submit_attempt(attempt_id: int, body: AnswersIn | None = None, session: Session = S):
        a = load_attempt(session, attempt_id)
        try:
            practice.submit(session, a, body.answers if body else None)
        except practice.PracticeError as e:
            raise HTTPException(409, str(e))
        return attempt_json(a, full=True)

    @app.delete("/api/attempts/{attempt_id}", status_code=204)
    def delete_attempt(attempt_id: int, session: Session = S):
        session.delete(load_attempt(session, attempt_id))
        session.commit()

    # Giao diện web đã build (src/nganhangde/web); mọi đường dẫn khác trả về index.html
    if (WEB_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            root = WEB_DIST.resolve()
            target = (root / path).resolve()
            if path and target.is_file() and root in target.parents:
                return FileResponse(target)
            return FileResponse(root / "index.html")

    return app
