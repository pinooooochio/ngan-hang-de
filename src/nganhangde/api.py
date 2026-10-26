"""API web (FastAPI) cho ngân hàng câu hỏi. Chạy: `nhd serve`."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from . import bank, render
from .compile import compile_tex, latex_available
from .db import get_url
from .models import Base, Level, Question, QuestionType, Status
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


def create_app(db_url: str | None = None) -> FastAPI:
    url = db_url or get_url()
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(engine)

    def get_session() -> Iterator[Session]:
        with SessionLocal() as s:
            yield s

    app = FastAPI(title="Ngân hàng đề")
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
