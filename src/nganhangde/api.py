"""API web (FastAPI) cho ngân hàng câu hỏi. Chạy: `nhd serve`."""

from __future__ import annotations

import io
import random
import shutil
import tempfile
import threading
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import aigen, chuyende, overview, params, theory, theorygen, auth, backup, bank, builds, figures, generator, practice, render
from .compile import compile_tex, latex_available
from .db import get_url, upgrade_schema
from .models import (
    ROLE_NAMES,
    VariantGroup,
    AnswerRequest,
    Attempt,
    Base,
    Choice,
    BuildStatus,
    Exam,
    ExamTemplate,
    GenerationBatch,
    Level,
    Question,
    QuestionLog,
    QuestionType,
    Role,
    Setting,
    Status,
    TheoryLog,
    TopicDoc,
    User,
)
from .parser import ParsedQuestion, parse_text
from .serialize import NEW_TEMPLATE, question_to_ex

WEB_DIST = Path(__file__).parent / "web"
COOKIE = "nhd_session"

# Cài đặt chung và giá trị mặc định
SETTINGS = {
    "student_quick": False,  # học viên được luyện nhanh từ ngân hàng (chỉ câu đã duyệt)
}

LOG_ACTIONS = {
    "tao": "Tạo câu",
    "sua": "Sửa",
    "duyet": "Duyệt",
    "bo-duyet": "Chuyển về nháp",
    "xoa": "Xoá",
    "import": "Import",
    "hang-loat": "Sửa hàng loạt",
    "nhom": "Đổi nhóm biến thể",
}


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
        "variant_group": q.variant_group,
        "check_note": q.check_note,
        "params": q.params,
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
    if q.params:
        data["sample"] = param_sample(q, full)
    return data


def param_sample(q: Question, full: bool) -> dict | None:
    """Một bộ số cố định theo mã câu để hiển thị câu tham số trong danh sách (thay vì {{a}})."""
    try:
        inst = params.instantiate_question(q, random.Random(zlib.crc32(q.code.encode())))
    except params.ParamError:
        return None
    out = instance_json(inst)
    return out if full else {"values": out["values"], "stem": out["stem"]}


def instance_json(inst: params.Instance) -> dict:
    return {"values": inst.values_text(), "stem": inst.stem, "short_answer": inst.short_answer,
            "solution": inst.solution,
            "choices": [{"content": c, "correct": ok, "pinned": pin} for c, ok, pin in inst.choices]}


def param_report(pq: ParsedQuestion) -> dict | None:
    """Câu tham số: chạy thử 200 lần bốc số, kèm 3 bản mẫu để người soạn xem trước khi duyệt."""
    if not pq.params:
        return None
    rep = params.check(pq.type, pq.params, pq.stem, [(c.content, c.is_correct, c.pinned) for c in pq.choices],
                       pq.short_answer, pq.solution)
    return {"ok": rep.ok, "errors": rep.errors, "warnings": rep.warnings, "tried": rep.tried, "valid": rep.valid,
            "distinct": rep.distinct, "domain": rep.domain, "reasons": rep.reasons,
            "samples": [instance_json(i) for i in rep.samples]}


def parsed_json(pq: ParsedQuestion, report: bool = False) -> dict:
    return {
        "params": pq.params,
        "param_report": param_report(pq) if report else None,
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


class FigureIn(BaseModel):
    code: str


class SaveIn(BaseModel):
    source: str
    status: Status | None = None


class BulkIn(BaseModel):
    codes: list[str]
    add_tag: str | None = None  # "Lớp 12 / Vectơ"
    set_tag: str | None = None  # thay mọi thẻ cũ bằng thẻ này
    level: Level | None = None
    status: Status | None = None


class CodesIn(BaseModel):
    codes: list[str]


class MoveTagIn(BaseModel):
    source: str = Field(min_length=1)  # tên hoặc slug, ví dụ "Đại học / Giải tích"
    target: str = Field(min_length=1)  # tên, ví dụ "Giải tích 1 / Chương 1. Hàm số một biến số"


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
    vary: bool = True  # đổi biến thể mỗi lần học viên làm
    date: str | None = None
    duration: int | None = None
    variants: int = Field(1, ge=1, le=30)
    first_code: int = 101
    seed: int | None = None
    sections: list[SectionIn] = Field(min_length=1)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    duration: int | None = None
    variants: int | None = Field(None, ge=1, le=30)
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


def template_config(body: TemplateIn) -> dict:
    """Cấu hình khung đề: bỏ câu chọn tay (thuộc về từng đề) và dòng ma trận trống."""
    data = body.model_dump(mode="json", exclude_none=True, exclude={"name", "description"})
    for sec in data["sections"]:
        sec.pop("ids", None)
        sec["pick"] = [p for p in sec["pick"] if p.get("count")]
    return data


def template_json(t: ExamTemplate) -> dict:
    sections = t.config.get("sections", [])
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "updated_at": t.updated_at.isoformat(timespec="seconds"),
        "n_questions": sum(p.get("count", 0) for sec in sections for p in sec.get("pick", [])),
        **t.config,
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
        "published": bool(exam.published),
        "vary": bool(exam.vary),
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
        "user_id": a.user_id,
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


class GenParamsIn(BaseModel):
    grade: str
    topic: str
    dang: str | None = None
    level: Level
    type: QuestionType = QuestionType.MCQ
    count: int = Field(10, ge=1, le=aigen.MAX_COUNT)
    notes: str | None = None
    figure: bool = False
    variant_of: str | None = None  # mã câu gốc khi sinh biến thể
    param: bool = False  # soạn mẫu câu tham số


class GenCheckIn(BaseModel):
    params: GenParamsIn
    output: str


class GenRowsIn(BaseModel):
    rows: list[GenParamsIn] = Field(min_length=1, max_length=200)


class GenMultiCheckIn(GenRowsIn):
    output: str


class GenMultiIn(GenRowsIn):
    mode: str = Field("api", pattern="^(api|manual)$")
    output: str | None = None
    group_id: str | None = None  # dán tay nhiều phần: phần sau gộp vào đợt của phần trước


class VariantPlanIn(BaseModel):
    tag: str | None = None  # theo chủ đề / dạng (đường dẫn thẻ)
    levels: list[Level] = []
    types: list[QuestionType] = []
    exam_id: int | None = None  # theo đề đã ghép
    codes: list[str] = Field([], max_length=2000)  # theo các câu đang chọn
    q: str | None = None  # tìm như ở ngân hàng: nội dung, mã câu, hoặc nhiều mã cách nhau bằng dấu phẩy
    computational_only: bool = False


class VariantRunIn(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=aigen.MAX_SOURCES)
    per: int = Field(5, ge=1, le=aigen.MAX_PER)
    notes: str | None = None
    mode: str = Field("api", pattern="^(api|manual)$")
    output: str | None = None
    group_id: str | None = None
    param: bool = False  # chuyển các câu gốc thành câu tham số (mỗi câu một mẫu)


class GenBatchIn(BaseModel):
    params: GenParamsIn
    mode: str = Field("api", pattern="^(api|manual)$")
    output: str | None = None


def batch_json(b: GenerationBatch, full: bool = False, n_pending: int | None = None) -> dict:
    items = b.items or []
    data = {
        "id": b.id,
        "user_id": b.user_id,
        "username": b.username,
        "group_id": b.group_id,
        "mode": b.mode,
        "status": b.status.value,
        "params": b.params,
        "model": b.model,
        "source": b.source,
        "created_at": b.created_at.isoformat(timespec="seconds"),
        "finished_at": b.finished_at.isoformat(timespec="seconds") if b.finished_at else None,
        "error": b.error,
        "usage": b.usage,
        "n_added": sum(1 for it in items if it.get("code")),
        "n_duplicate": sum(1 for it in items if it["state"] == "duplicate"),
        "n_error": sum(1 for it in items if it["state"] == "error"),
    }
    if n_pending is not None:
        data["n_pending"] = n_pending  # câu của lần sinh còn ở trạng thái nháp
    if full:
        data.update(system_prompt=b.system_prompt, user_prompt=b.user_prompt, output=b.output, items=items)
    return data


class SetupIn(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class UserIn(BaseModel):
    username: str
    password: str
    role: Role
    display_name: str | None = None


class UserUpdateIn(BaseModel):
    display_name: str | None = None
    role: Role | None = None
    active: bool | None = None
    password: str | None = None


class PublishIn(BaseModel):
    published: bool


class GroupLabelIn(BaseModel):
    label: str = Field("", max_length=300)


class SetGroupIn(BaseModel):
    group: str | None = None  # None: tách khỏi nhóm


class MergeGroupIn(BaseModel):
    codes: list[str] = Field(min_length=2, max_length=500)
    label: str | None = Field(None, max_length=300)


def group_json(session: Session, g: VariantGroup, members: bool = False) -> dict:
    data = {"code": g.code, "origin_code": g.origin_code, "label": g.label,
            "level": g.level.value if g.level else None, "type": g.type.value if g.type else None,
            "n": bank.group_size(session, g.code)}
    if members:
        rows = session.scalars(select(Question).where(Question.variant_group == g.code).order_by(Question.id))
        data["members"] = [{"code": q.code, "status": q.status.value} for q in rows]
    return data


class VaryIn(BaseModel):
    vary: bool


class TheoryParseIn(BaseModel):
    source: str
    path: str | None = None  # chủ đề mặc định (trang soạn theo chủ đề, hoặc chọn khi import)


class TheorySaveIn(BaseModel):
    path: str
    source: str
    approve: bool = False


class TheoryImportIn(BaseModel):
    source: str
    path: str | None = None
    filename: str | None = None
    mode: str = Field("append", pattern="^(append|replace)$")
    approve: bool = False
    only: list[str] | None = None  # chỉ import các chủ đề này (đường dẫn)


class TheoryPathIn(BaseModel):
    path: str


class TheoryGenIn(BaseModel):
    paths: list[str] = Field(min_length=1)
    general: bool | None = None  # None: tự chọn phần còn thiếu của chủ đề
    dang: list[str] | None = None  # chỉ khi một chủ đề; None: các dạng còn thiếu (hoặc tất cả nếu all_parts)
    all_parts: bool = False  # soạn cả chủ đề, kể cả phần đã có
    examples: int = Field(2, ge=0, le=4)
    note: str = ""
    mode: str = Field("api", pattern="^(api|manual)$")
    output: str | None = None


class TopicDocIn(BaseModel):
    title: str = ""
    date: str | None = None
    parts: list[dict] = Field(default_factory=list)
    levels: dict[str, int] | None = None
    mixed: dict[str, int] | None = None
    types: list[str] | None = None
    seed: int | None = None


class DecisionIn(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    note: str | None = None


def user_json(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role.value,
        "role_name": ROLE_NAMES[u.role],
        "active": u.active,
        "created_at": u.created_at.isoformat(timespec="seconds") if u.created_at else None,
        "last_login": u.last_login.isoformat(timespec="seconds") if u.last_login else None,
    }


def log_json(r: QuestionLog) -> dict:
    return {
        "id": r.id,
        "code": r.code,
        "username": r.username,
        "action": r.action,
        "action_name": LOG_ACTIONS.get(r.action, r.action),
        "detail": r.detail,
        "has_before": r.before is not None,
        "at": r.at.isoformat(timespec="seconds"),
    }


def is_staff(user: User) -> bool:
    return user.role in (Role.ADMIN, Role.EDITOR)


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


# ---------- Lý thuyết ----------


def theory_block_json(b, refs: dict[str, dict] | None = None) -> dict:
    """Một khối lý thuyết (đã lưu: TheoryBlock, hoặc vừa đọc: theory.ParsedBlock)."""
    saved = not isinstance(b, theory.ParsedBlock)
    ref = b.ref_code if saved else b.ref
    data = {"kind": b.kind, "kind_name": theory.KINDS.get(b.kind, b.kind), "title": b.title, "content": b.content,
            "dang": b.dang, "ref": ref, "question": (refs or {}).get(ref) if ref else None}
    if saved:
        data.update(code=b.code, status=b.status.value, source=b.source, updated_by=b.updated_by,
                    updated_at=b.updated_at.isoformat(timespec="seconds") if b.updated_at else None)
    else:
        data["line"] = b.line
    return data


def theory_refs(session: Session, blocks, approved_only: bool) -> dict[str, dict]:
    """Câu hỏi được dẫn làm ví dụ: mã -> dữ liệu để hiển thị (học viên chỉ thấy câu đã duyệt)."""
    codes = {(b.ref if isinstance(b, theory.ParsedBlock) else b.ref_code) for b in blocks}
    codes.discard(None)
    if not codes:
        return {}
    q = select(Question).where(Question.code.in_(codes))
    if approved_only:
        q = q.where(Question.status == Status.APPROVED)
    out = {}
    for row in session.scalars(q):
        data = question_json(row)
        out[row.code] = {k: data.get(k) for k in ("code", "type", "level", "status", "stem", "choices",
                                                     "short_answer", "solution", "sample")}
    return out


def theory_topic_json(t: dict) -> dict:
    return {"path": t["path"], "ten": t["ten"], "names": t["names"], "grade": t["grade"], "chuong": t["chuong"],
            "dang": t["dang"], "noi_dung": t["noi_dung"]}


def theory_parsed_json(session: Session, parsed: theory.ParsedTheory) -> dict:
    blocks = [b for sec in parsed.sections for b in sec.blocks]
    refs = theory_refs(session, blocks, approved_only=False)
    warnings = list(parsed.warnings)
    for sec in parsed.sections:
        for b in sec.blocks:
            if b.ref and b.ref not in refs:
                warnings.append((b.line, f"không có câu {b.ref} trong ngân hàng"))
    return {
        "errors": [{"line": ln, "message": m} for ln, m in parsed.errors],
        "warnings": [{"line": ln, "message": m} for ln, m in sorted(warnings)],
        "sections": [{"topic": theory_topic_json(sec.topic), "line": sec.line,
                      "blocks": [theory_block_json(b, refs) for b in sec.blocks]} for sec in parsed.sections],
    }


# ---------- Ứng dụng ----------


def create_app(db_url: str | None = None, worker: bool = False) -> FastAPI:
    url = db_url or get_url()
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    upgrade_schema(engine)
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        bank.migrate_groups(s)  # nhóm biến thể kiểu cũ (mã câu gốc) sang bảng nhóm
        bank.repair_split_tags(s)  # thẻ bị tách nhầm ở dấu phẩy trong tên chủ đề (bản cũ)

    def get_session() -> Iterator[Session]:
        with SessionLocal() as s:
            yield s

    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if worker:
            builds.start_worker(SessionLocal, stop)
            aigen.start_worker(SessionLocal, stop)
        yield
        stop.set()

    app = FastAPI(title="Ngân hàng đề", lifespan=lifespan)
    app.state.engine = engine
    S = Depends(get_session)

    # ---------- Đăng nhập và quyền ----------
    # Mọi API trừ /api/auth/* cần đăng nhập; quyền theo vai trò kiểm tra ở từng API
    # (test_auth.py duyệt mọi đường dẫn để chắc không API nào bị bỏ sót).

    def current_user(request: Request, session: Session = S) -> User:
        user = auth.session_user(session, request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, "chưa đăng nhập")
        return user

    def need(*roles: Role):
        def dep(user: User = Depends(current_user)) -> User:
            if user.role not in roles:
                raise HTTPException(403, "tài khoản của bạn không có quyền này")
            return user

        return Depends(dep)

    U = Depends(current_user)
    STAFF = need(Role.ADMIN, Role.EDITOR)
    ADMIN = need(Role.ADMIN)

    def get_setting(session: Session, key: str):
        row = session.get(Setting, key)
        return row.value if row is not None else SETTINGS[key]

    def log(session: Session, user: User | None, codes, action: str, detail: str | None = None,
            before: str | None = None) -> None:
        for code in codes:
            session.add(QuestionLog(code=code, user_id=user.id if user else None,
                                    username=user.username if user else None, action=action,
                                    detail=detail, before=before))
        session.commit()

    def set_cookie(resp: Response, token: str) -> None:
        resp.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax")

    @app.get("/api/auth/me")
    def me(request: Request, session: Session = S):
        user = auth.session_user(session, request.cookies.get(COOKIE))
        if user is None:
            return JSONResponse({"detail": "chưa đăng nhập", "setup": not auth.has_users(session)}, status_code=401)
        data = user_json(user)
        data["settings"] = {k: get_setting(session, k) for k in SETTINGS}
        if user.role == Role.ADMIN:
            data["pending_requests"] = session.scalar(
                select(func.count(AnswerRequest.id)).where(AnswerRequest.status == "pending")
            )
        return data

    @app.post("/api/auth/setup", status_code=201)
    def setup(body: SetupIn, response: Response, session: Session = S):
        """Tạo tài khoản admin đầu tiên; chỉ dùng được khi chưa có tài khoản nào."""
        if auth.has_users(session):
            raise HTTPException(409, "đã có tài khoản, hãy đăng nhập")
        try:
            user = auth.create_user(session, body.username, body.password, Role.ADMIN, body.display_name)
        except auth.AuthError as e:
            raise HTTPException(422, str(e))
        user.last_login = datetime.now()
        session.commit()
        set_cookie(response, auth.start_session(session, user))
        return user_json(user)

    @app.post("/api/auth/login")
    def login(body: LoginIn, response: Response, session: Session = S):
        try:
            user = auth.authenticate(session, body.username, body.password)
        except auth.AuthError as e:
            raise HTTPException(401, str(e))
        set_cookie(response, auth.start_session(session, user))
        return user_json(user)

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response, session: Session = S):
        auth.end_session(session, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)

    @app.post("/api/auth/password", status_code=204)
    def change_password(body: PasswordIn, request: Request, user: User = U, session: Session = S):
        if not auth.verify_password(body.old_password, user.password_hash):
            raise HTTPException(422, "mật khẩu hiện tại không đúng")
        try:
            auth.set_password(session, user, body.new_password)
        except auth.AuthError as e:
            raise HTTPException(422, str(e))
        auth.end_user_sessions(session, user.id, keep=request.cookies.get(COOKIE))

    @app.put("/api/auth/me")
    def update_me(body: UserUpdateIn, user: User = U, session: Session = S):
        if body.display_name is not None and body.display_name.strip():
            user.display_name = body.display_name.strip()
            session.commit()
        return user_json(user)

    # ---------- Người dùng (admin) ----------

    @app.get("/api/users", dependencies=[ADMIN])
    def list_users(session: Session = S):
        return [user_json(u) for u in session.scalars(select(User).order_by(User.role, User.username))]

    @app.post("/api/users", status_code=201, dependencies=[ADMIN])
    def create_user(body: UserIn, session: Session = S):
        try:
            return user_json(auth.create_user(session, body.username, body.password, body.role, body.display_name))
        except auth.AuthError as e:
            raise HTTPException(422, str(e))

    @app.put("/api/users/{user_id}")
    def update_user(user_id: int, body: UserUpdateIn, me: User = ADMIN, session: Session = S):
        u = session.get(User, user_id)
        if u is None:
            raise HTTPException(404, f"không có tài khoản #{user_id}")
        demote = (body.role is not None and body.role != Role.ADMIN) or body.active is False
        if u.role == Role.ADMIN and u.active and demote and auth.active_admins(session) <= 1:
            raise HTTPException(409, "phải còn ít nhất một admin đang hoạt động")
        if body.display_name is not None and body.display_name.strip():
            u.display_name = body.display_name.strip()
        if body.role is not None:
            u.role = body.role
        if body.active is not None:
            u.active = body.active
            if body.active:
                u.failed_logins, u.locked_until = 0, None
        session.commit()
        if body.password:
            try:
                auth.set_password(session, u, body.password)
            except auth.AuthError as e:
                raise HTTPException(422, str(e))
        if body.active is False or body.password or body.role is not None:
            # đổi quyền, mật khẩu hay khoá thì người đó phải đăng nhập lại
            if u.id != me.id:
                auth.end_user_sessions(session, u.id)
        return user_json(u)

    # ---------- Cài đặt chung ----------

    @app.get("/api/settings", dependencies=[U])
    def read_settings(session: Session = S):
        return {k: get_setting(session, k) for k in SETTINGS}

    @app.put("/api/settings", dependencies=[ADMIN])
    def write_settings(body: dict[str, Any], session: Session = S):
        for k, v in body.items():
            if k not in SETTINGS:
                raise HTTPException(422, f"không có cài đặt {k}")
            if type(v) is not type(SETTINGS[k]):
                raise HTTPException(422, f"giá trị của {k} không hợp lệ")
            row = session.get(Setting, k) or Setting(key=k)
            row.value = v
            session.add(row)
        session.commit()
        return {k: get_setting(session, k) for k in SETTINGS}

    @app.get("/api/questions", dependencies=[STAFF])
    def list_questions(
        tag: str | None = None,
        level: Level | None = None,
        type: QuestionType | None = None,
        status: Status | None = None,
        q: str | None = None,
        source: str | None = None,
        group: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session: Session = S,
    ):
        stmt = bank.question_query(tag, level, type, status, q, source, group)
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = list(session.scalars(stmt.order_by(Question.updated_at.desc(), Question.id.desc()).limit(limit).offset(offset)))
        groups = {r.variant_group for r in rows if r.variant_group}
        sizes = dict(session.execute(
            select(Question.variant_group, func.count()).where(Question.variant_group.in_(groups))
            .group_by(Question.variant_group)
        ).all()) if groups else {}
        labels = dict(session.execute(
            select(VariantGroup.code, VariantGroup.label).where(VariantGroup.code.in_(groups))
        ).all()) if groups else {}
        items = [{**question_json(r, full=False), "n_variants": sizes.get(r.variant_group, 1),
                  "variant_label": labels.get(r.variant_group)} for r in rows]
        return {"total": total, "items": items}

    @app.get("/api/questions/codes", dependencies=[STAFF])
    def question_codes(
        tag: str | None = None,
        level: Level | None = None,
        type: QuestionType | None = None,
        status: Status | None = None,
        q: str | None = None,
        source: str | None = None,
        group: str | None = None,
        session: Session = S,
    ):
        """Mã mọi câu khớp bộ lọc (không phân trang), để chọn tất cả rồi sửa hàng loạt."""
        stmt = bank.question_query(tag, level, type, status, q, source, group)
        return list(session.scalars(stmt.with_only_columns(Question.code).order_by(Question.code)))

    @app.get("/api/questions/{code}", dependencies=[STAFF])
    def get_question(code: str, session: Session = S):
        q = bank.get_question(session, code)
        if q is None:
            raise HTTPException(404, f"không có câu {code}")
        return question_detail(session, q)

    def question_detail(session: Session, q: Question) -> dict:
        """Câu đầy đủ kèm nhóm biến thể (trang soạn câu cần các trường này cả sau khi lưu)."""
        members = bank.variant_members(session, q)
        g = bank.get_group(session, q.variant_group)
        return {**question_json(q), "n_variants": len(members),
                "variants": [{"code": m.code, "status": m.status.value} for m in members],
                "variant_label": g.label if g else None, "variant_origin": g.origin_code if g else None}

    def check_status(user: User, status: Status | None) -> None:
        if status == Status.APPROVED and user.role != Role.ADMIN:
            raise HTTPException(403, "chỉ admin được duyệt câu hỏi")

    @app.post("/api/questions", status_code=201)
    def create_question(body: SaveIn, user: User = STAFF, session: Session = S):
        check_status(user, body.status)
        pq = parse_one(body.source)
        try:
            q = bank.create_question(session, pq, status=body.status or Status.DRAFT)
        except bank.BankError as e:
            raise HTTPException(422, str(e))
        log(session, user, [q.code], "tao", "đã duyệt" if q.status == Status.APPROVED else None)
        return question_json(q)

    @app.put("/api/questions/{code}")
    def update_question(code: str, body: SaveIn, user: User = STAFF, session: Session = S):
        q = bank.get_question(session, code)
        if q is None:
            raise HTTPException(404, f"không có câu {code}")
        old_status = q.status
        if body.status is not None and body.status != old_status and user.role != Role.ADMIN:
            raise HTTPException(403, "chỉ admin được duyệt hoặc chuyển câu về nháp")
        before = question_to_ex(q)
        pq = parse_one(body.source)
        try:
            q = bank.update_question(session, code, pq)
            if question_to_ex(q) != before:
                q.check_note = None  # đã sửa: cảnh báo lúc sinh không còn đúng
            if body.status:
                q.status = body.status
                session.commit()
        except bank.BankError as e:
            raise HTTPException(422, str(e))
        after = question_to_ex(q)
        if after != before:
            log(session, user, [q.code], "sua", f"đổi mã từ {code}" if q.code != code else None, before)
        if q.status != old_status:
            log(session, user, [q.code], "duyet" if q.status == Status.APPROVED else "bo-duyet")
        return question_detail(session, q)

    @app.get("/api/questions/{code}/variant-params", dependencies=[STAFF])
    def variant_params(code: str, count: int = 5, session: Session = S):
        """Tham số để sinh biến thể (cùng dạng, khác số liệu) cho câu này."""
        try:
            return aigen.variant_params(session, code, count)
        except aigen.GenError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/variant-groups/{code}", dependencies=[STAFF])
    def get_variant_group(code: str, session: Session = S):
        g = bank.get_group(session, code)
        if g is None:
            raise HTTPException(404, f"không có nhóm {code}")
        return group_json(session, g, members=True)

    @app.put("/api/variant-groups/{code}", dependencies=[STAFF])
    def label_variant_group(code: str, body: GroupLabelIn, session: Session = S):
        """Sửa mô tả dạng bài của nhóm."""
        g = bank.get_group(session, code)
        if g is None:
            raise HTTPException(404, f"không có nhóm {code}")
        g.label = body.label.strip() or None
        session.commit()
        return group_json(session, g)

    @app.post("/api/variant-groups/merge")
    def merge_variant_group(body: MergeGroupIn, user: User = STAFF, session: Session = S):
        """Gộp các câu đã chọn thành một nhóm biến thể."""
        qs = [bank.get_question(session, c) for c in dict.fromkeys(body.codes)]
        missing = [c for c, q in zip(dict.fromkeys(body.codes), qs) if q is None]
        if missing:
            raise HTTPException(404, f"không có câu {', '.join(missing)}")
        try:
            g = bank.merge_group(session, qs, body.label)  # type: ignore[arg-type]
        except bank.GroupError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        session.commit()
        log(session, user, [q.code for q in qs], "nhom", f"gộp vào nhóm {g.code}")
        return group_json(session, g)

    @app.put("/api/questions/{code}/variant-group")
    def set_question_group(code: str, body: SetGroupIn, user: User = STAFF, session: Session = S):
        """Chuyển câu sang nhóm khác, hoặc tách khỏi nhóm (group = null)."""
        q = bank.get_question(session, code)
        if q is None:
            raise HTTPException(404, f"không có câu {code}")
        old = q.variant_group
        try:
            g = bank.set_group(session, q, (body.group or "").strip() or None)
        except bank.GroupError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        session.commit()
        log(session, user, [q.code], "nhom", f"chuyển sang nhóm {g.code}" if g else f"tách khỏi nhóm {old}")
        return {"code": q.code, "variant_group": q.variant_group}

    @app.post("/api/questions/group/{group}/approve")
    def approve_group(group: str, user: User = ADMIN, session: Session = S):
        """Duyệt mọi câu nháp của một nhóm biến thể, trừ câu còn cảnh báo lúc sinh (hình lỗi, đáp án tự
        kiểm không khớp): những câu đó phải mở ra sửa hoặc duyệt từng câu."""
        rows = list(session.scalars(select(Question).where(Question.variant_group == group,
                                                           Question.status == Status.DRAFT)
                                    .order_by(Question.code)))
        ok = [q for q in rows if not q.check_note]
        for q in ok:
            q.status = Status.APPROVED
        session.commit()
        if ok:
            log(session, user, [q.code for q in ok], "duyet", f"duyệt cả nhóm {group}")
        return {"approved": len(ok), "skipped": [q.code for q in rows if q.check_note]}

    @app.get("/api/questions/{code}/log", dependencies=[STAFF])
    def question_log(code: str, session: Session = S):
        rows = session.scalars(select(QuestionLog).where(QuestionLog.code == code)
                               .order_by(QuestionLog.at.desc(), QuestionLog.id.desc()))
        return [log_json(r) for r in rows]

    @app.get("/api/question-logs/{log_id}", dependencies=[STAFF])
    def question_log_entry(log_id: int, session: Session = S):
        r = session.get(QuestionLog, log_id)
        if r is None:
            raise HTTPException(404, f"không có mục nhật ký #{log_id}")
        return {**log_json(r), "before": r.before}

    @app.get("/api/question-logs", dependencies=[ADMIN])
    def question_logs(limit: int = 100, offset: int = 0, username: str | None = None, session: Session = S):
        stmt = select(QuestionLog)
        if username:
            stmt = stmt.where(QuestionLog.username == username)
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(stmt.order_by(QuestionLog.at.desc(), QuestionLog.id.desc()).limit(limit).offset(offset))
        return {"total": total, "items": [log_json(r) for r in rows]}

    @app.delete("/api/questions/{code}", status_code=204)
    def delete_question(code: str, user: User = ADMIN, session: Session = S):
        q = bank.get_question(session, code)
        before = question_to_ex(q) if q is not None else None
        session.expire_all()  # bank.delete_question xoá gắn thẻ bằng SQL trực tiếp
        try:
            bank.delete_question(session, code)
        except bank.BankError as e:
            raise HTTPException(422, str(e))
        log(session, user, [code], "xoa", before=before)

    @app.post("/api/questions/bulk")
    def bulk(body: BulkIn, user: User = STAFF, session: Session = S):
        if body.status is not None and user.role != Role.ADMIN:
            raise HTTPException(403, "chỉ admin được duyệt hoặc chuyển câu về nháp")
        n = bank.bulk_update(session, body.codes, split_tag(body.add_tag), body.level, body.status,
                             split_tag(body.set_tag))
        parts = [f"thêm thẻ {body.add_tag}" if body.add_tag else None,
                 f"đặt thẻ {body.set_tag}" if body.set_tag else None,
                 f"mức độ {body.level.value}" if body.level else None,
                 ("duyệt" if body.status == Status.APPROVED else "chuyển về nháp") if body.status else None]
        log(session, user, body.codes, "hang-loat", ", ".join(p for p in parts if p) or None)
        return {"updated": n}

    @app.post("/api/questions/bulk-delete")
    def bulk_delete(body: CodesIn, user: User = ADMIN, session: Session = S):
        befores = {q.code: question_to_ex(q) for q in session.scalars(select(Question).where(Question.code.in_(body.codes)))}
        session.expire_all()
        n, kept = bank.bulk_delete(session, body.codes)
        for code, before in befores.items():
            if code not in kept:
                log(session, user, [code], "xoa", "xoá hàng loạt", before)
        return {"deleted": n, "kept": kept}

    @app.get("/api/template", dependencies=[STAFF])
    def template():
        return {"source": NEW_TEMPLATE}

    @app.post("/api/parse", dependencies=[STAFF])
    def parse(body: SourceIn):
        pqs = parse_text(body.source)
        return [parsed_json(pq, report=len(pqs) == 1) for pq in pqs]

    @app.get("/api/tags", dependencies=[U])
    def tags(khung: bool = False, session: Session = S):
        """Cây thẻ. `khung=1`: hiện đủ khung chương trình (cả chương, chủ đề, dạng chưa có câu nào)."""
        return bank.tag_tree_full(session, aigen.curriculum_order(),
                                  aigen.curriculum_skeleton() if khung else None)

    @app.post("/api/tags/move", dependencies=[ADMIN])
    def move_tag(body: MoveTagIn, session: Session = S):
        target = split_tag(body.target)
        if not target:
            raise HTTPException(422, "chưa nhập thẻ đích")
        try:
            return {"moved": bank.move_tag(session, body.source, target)}
        except bank.BankError as e:
            session.rollback()
            raise HTTPException(422, str(e))

    @app.get("/api/tags/moves", dependencies=[ADMIN])
    def tag_moves(session: Session = S):
        """Quy tắc chuyển thẻ từ khung cũ trong khung chương trình, kèm số câu còn ở thẻ nguồn."""
        return [{**r, "count": bank.count_in_tag(session, r["from"])} for r in aigen.load_tag_moves()]

    @app.post("/api/tags/moves/apply", dependencies=[ADMIN])
    def apply_tag_moves(session: Session = S):
        moved = 0
        for r in aigen.load_tag_moves():
            moved += bank.move_tag(session, r["from"], split_tag(r["to"]) or [])
        return {"moved": moved}

    def split_summary(changes: list[dict]) -> list[dict]:
        rows: dict[tuple, dict] = {}
        for c in changes:
            key = (tuple(c["before"]), tuple(c["after"]))
            r = rows.setdefault(key, {"before": c["before"], "after": c["after"], "codes": []})
            r["codes"].append(c["code"])
        return sorted(rows.values(), key=lambda r: -len(r["codes"]))

    @app.get("/api/tags/split", dependencies=[ADMIN])
    def split_tags_preview(session: Session = S):
        """Câu có thẻ bị tách nhầm ở dấu phẩy trong tên chủ đề (import bằng bản cũ) và thẻ sau khi ghép lại."""
        return split_summary(bank.repair_split_tags(session, dry_run=True))

    @app.post("/api/tags/split/repair", dependencies=[ADMIN])
    def split_tags_repair(session: Session = S):
        return {"fixed": len(bank.repair_split_tags(session))}

    @app.get("/api/overview", dependencies=[STAFF])
    def bank_overview(session: Session = S):
        """Ngân hàng theo chủ đề: số câu theo mức độ, câu nháp, lý thuyết, chuyên đề của từng chủ đề / dạng bài."""
        return overview.overview(session)

    @app.get("/api/stats", dependencies=[STAFF])
    def stats(session: Session = S):
        by_level = dict(session.execute(select(Question.level, func.count()).group_by(Question.level)).all())
        by_status = dict(session.execute(select(Question.status, func.count()).group_by(Question.status)).all())
        return {
            "total": sum(by_status.values()),
            "by_level": {(k.value if k else "none"): v for k, v in by_level.items()},
            "by_status": {k.value: v for k, v in by_status.items()},
        }

    @app.post("/api/import/preview", dependencies=[STAFF])
    def import_preview(body: SourceIn, session: Session = S):
        items = bank.preview_import(session, parse_text(body.source))
        return [
            {"index": it.index, "state": it.state, "duplicate_of": it.duplicate_of, **parsed_json(it.parsed)}
            for it in items
        ]

    @app.post("/api/import/commit")
    def import_commit(body: ImportIn, user: User = STAFF, session: Session = S):
        # câu do tài khoản Soạn đề import luôn vào nháp, chờ admin duyệt
        status = body.status if user.role == Role.ADMIN else Status.DRAFT
        report = bank.import_questions(
            session,
            parse_text(body.source),
            source=body.filename,
            status=status,
            only=set(body.only) if body.only is not None else None,
            extra_tag=split_tag(body.extra_tag),
            default_level=body.default_level,
        )
        log(session, user, report.added, "import", body.filename)
        return {"added": report.added, "duplicates": len(report.duplicates), "failed": len(report.failed)}

    @app.post("/api/preview/pdf", dependencies=[STAFF])
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
        if pq.params:  # câu tham số: in một bộ số ngẫu nhiên
            try:
                inst = params.instantiate(pq.type, pq.params, pq.stem,
                                          [(c.content, c.is_correct, c.pinned) for c in pq.choices],
                                          pq.short_answer, pq.solution, random.Random())
            except params.ParamError as e:
                raise HTTPException(422, f"câu tham số: {e}") from e
            item.update(stem=inst.stem, short_answer=inst.short_answer, solution=inst.solution,
                        choices=[{"content": c, "correct": ok} for c, ok, _ in inst.choices])
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

    # ---------- Hình vẽ ----------

    def figure_in_use(session: Session, user: User, code: str) -> bool:
        """Hình có trong một câu của ngân hàng hoặc trong bài làm của học viên này không
        (so sánh bỏ qua khác biệt khoảng trắng)."""
        want = " ".join(code.split())

        def has(text: str) -> bool:
            return want in " ".join(text.split())

        mark = "tikzpicture"
        for stem, sol in session.execute(select(Question.stem_latex, Question.solution_latex).where(
                Question.stem_latex.contains(mark) | Question.solution_latex.contains(mark))):
            if has(stem) or has(sol or ""):
                return True
        if any(has(t) for t in session.scalars(select(Choice.content_latex).where(Choice.content_latex.contains(mark)))):
            return True

        def mentions(v) -> bool:
            if isinstance(v, str):
                return mark in v and has(v)
            if isinstance(v, dict):
                return any(mentions(x) for x in v.values())
            if isinstance(v, list):
                return any(mentions(x) for x in v)
            return False

        return any(mentions(a.data) for a in session.scalars(select(Attempt).where(Attempt.user_id == user.id)))

    @app.post("/api/figures")
    def figure(body: FigureIn, user: User = U, session: Session = S):
        """Biên dịch một hình TikZ ra SVG (lưu lại, lần sau lấy ngay). Học viên chỉ được tạo ảnh
        cho hình có sẵn trong câu hỏi hoặc bài làm, không biên dịch mã tuỳ ý."""
        code = body.code.strip()
        fid = figures.figure_id(code)
        hit = figures.cached(fid)
        if hit is None and user.role == Role.STUDENT and not figure_in_use(session, user, code):
            raise HTTPException(403, "hình không thuộc câu hỏi nào")
        f = hit or figures.render(code)
        return {"id": f.id, "ok": f.ok, "error": f.error}

    @app.get("/api/figures/{fid}.svg", dependencies=[U])
    def figure_svg(fid: str):
        if not figures.ID_RE.match(fid) or not figures.svg_path(fid).exists():
            raise HTTPException(404, "không có hình này")
        return FileResponse(figures.svg_path(fid), media_type="image/svg+xml",
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    # ---------- Đề thi ----------

    @app.post("/api/exams/availability", dependencies=[STAFF])
    def availability(body: AvailabilityIn, session: Session = S):
        """Số câu đã duyệt hiện có cho từng dòng ma trận (kèm số câu chưa từng dùng trong đề hay lượt
        luyện nào), và các mã câu chọn tay không dùng được."""
        usage = generator.usage_counts(session)
        out = []
        for sec in body.sections:
            pools = [bank.find_questions(session, tag=p.tag, level=p.level, type=sec.type, approved_only=True)
                     for p in sec.pick]
            rows = [len(pool) for pool in pools]
            unused = [sum(1 for q in pool if not usage.get(q.code)) for pool in pools]
            problems = []
            for code in sec.ids:
                q = bank.get_question(session, code)
                if q is None:
                    problems.append(f"không có câu {code}")
                elif q.type != sec.type:
                    problems.append(f"câu {code} không đúng loại của phần này")
            out.append({"rows": rows, "unused": unused, "problems": problems})
        return {"sections": out}

    # ---------- Khung đề ----------

    @app.get("/api/exam-templates", dependencies=[STAFF])
    def list_templates(session: Session = S):
        return [template_json(t) for t in session.scalars(select(ExamTemplate).order_by(ExamTemplate.name))]

    def save_template(session: Session, t: ExamTemplate, body: TemplateIn) -> dict:
        name = body.name.strip()
        other = session.scalar(select(ExamTemplate).where(ExamTemplate.name == name))
        if other is not None and other.id != t.id:
            raise HTTPException(409, f"đã có khung đề tên \"{name}\"")
        t.name, t.description, t.config = name, body.description.strip(), template_config(body)
        session.add(t)
        session.commit()
        return template_json(t)

    @app.post("/api/exam-templates", status_code=201, dependencies=[STAFF])
    def create_template(body: TemplateIn, session: Session = S):
        return save_template(session, ExamTemplate(), body)

    def load_template(session: Session, template_id: int) -> ExamTemplate:
        t = session.get(ExamTemplate, template_id)
        if t is None:
            raise HTTPException(404, f"không có khung đề #{template_id}")
        return t

    @app.put("/api/exam-templates/{template_id}", dependencies=[STAFF])
    def update_template(template_id: int, body: TemplateIn, session: Session = S):
        return save_template(session, load_template(session, template_id), body)

    @app.delete("/api/exam-templates/{template_id}", status_code=204, dependencies=[ADMIN])
    def delete_template(template_id: int, session: Session = S):
        session.delete(load_template(session, template_id))
        session.commit()

    def request_of(session: Session, user: User, exam_id: int) -> AnswerRequest | None:
        return session.scalar(select(AnswerRequest).where(AnswerRequest.user_id == user.id,
                                                          AnswerRequest.exam_id == exam_id))

    def can_download(session: Session, user: User, exam: Exam, kind: str) -> bool:
        """Soạn đề và admin tải mọi file; học viên tải file đề của đề đã mở, còn đáp án và lời giải
        thì cần admin đồng ý yêu cầu."""
        if is_staff(user):
            return True
        if not exam.published:
            return False
        if kind == "de":
            return True
        r = request_of(session, user, exam.id)
        return r is not None and r.status == "approved"

    def student_exam_json(session: Session, user: User, exam: Exam) -> dict:
        data = exam_json(exam)
        r = request_of(session, user, exam.id)
        data["request"] = {"status": r.status, "note": r.note} if r else None
        data["files"] = [build_json(exam.id, b) for b in exam.builds if can_download(session, user, exam, b.kind)]
        return data

    @app.get("/api/exams")
    def list_exams(user: User = U, session: Session = S):
        stmt = select(Exam).order_by(Exam.created_at.desc(), Exam.id.desc())
        if not is_staff(user):
            return [student_exam_json(session, user, e) for e in session.scalars(stmt.where(Exam.published.is_(True)))]
        return [exam_json(e) for e in session.scalars(stmt)]

    @app.post("/api/exams", status_code=201, dependencies=[STAFF])
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
    def get_exam(exam_id: int, user: User = U, session: Session = S):
        exam = load_exam(session, exam_id)
        if is_staff(user):
            return exam_json(exam, full=True)
        if not exam.published:
            raise HTTPException(404, f"không có đề #{exam_id}")
        return student_exam_json(session, user, exam)

    @app.put("/api/exams/{exam_id}/published", dependencies=[STAFF])
    def publish_exam(exam_id: int, body: PublishIn, session: Session = S):
        exam = load_exam(session, exam_id)
        exam.published = body.published
        session.commit()
        return exam_json(exam)

    @app.put("/api/exams/{exam_id}/vary", dependencies=[STAFF])
    def set_vary(exam_id: int, body: VaryIn, session: Session = S):
        exam = load_exam(session, exam_id)
        exam.vary = body.vary
        session.commit()
        return exam_json(exam)

    @app.post("/api/exams/{exam_id}/answer-request", status_code=201)
    def request_answers(exam_id: int, user: User = need(Role.STUDENT), session: Session = S):
        exam = load_exam(session, exam_id)
        if not exam.published:
            raise HTTPException(404, f"không có đề #{exam_id}")
        r = request_of(session, user, exam_id)
        if r is not None and r.status == "approved":
            raise HTTPException(409, "yêu cầu đã được đồng ý")
        r = r or AnswerRequest(user_id=user.id, exam_id=exam_id)
        r.status, r.note, r.created_at, r.decided_at, r.decided_by = "pending", None, datetime.now(), None, None
        session.add(r)
        session.commit()
        return student_exam_json(session, user, exam)

    @app.get("/api/answer-requests")
    def list_requests(status: str | None = None, user: User = U, session: Session = S):
        stmt = select(AnswerRequest).order_by(AnswerRequest.created_at.desc())
        if user.role != Role.ADMIN:
            stmt = stmt.where(AnswerRequest.user_id == user.id)
        if status:
            stmt = stmt.where(AnswerRequest.status == status)
        out = []
        for r in session.scalars(stmt):
            u, e = session.get(User, r.user_id), session.get(Exam, r.exam_id)
            out.append({
                "id": r.id, "status": r.status, "note": r.note,
                "created_at": r.created_at.isoformat(timespec="seconds"),
                "decided_at": r.decided_at.isoformat(timespec="seconds") if r.decided_at else None,
                "decided_by": r.decided_by,
                "user": {"id": u.id, "username": u.username, "display_name": u.display_name} if u else None,
                "exam": {"id": e.id, "title": e.title} if e else None,
            })
        return out

    @app.put("/api/answer-requests/{request_id}")
    def decide_request(request_id: int, body: DecisionIn, user: User = ADMIN, session: Session = S):
        r = session.get(AnswerRequest, request_id)
        if r is None:
            raise HTTPException(404, f"không có yêu cầu #{request_id}")
        r.status, r.note = body.status, (body.note or "").strip() or None
        r.decided_at, r.decided_by = datetime.now(), user.username
        session.commit()
        return {"id": r.id, "status": r.status}

    @app.post("/api/exams/{exam_id}/rebuild", dependencies=[STAFF])
    def rebuild_exam(exam_id: int, session: Session = S):
        exam = load_exam(session, exam_id)
        builds.queue_builds(session, exam)
        return exam_json(exam, full=True)

    @app.delete("/api/exams/{exam_id}", status_code=204, dependencies=[ADMIN])
    def delete_exam(exam_id: int, session: Session = S):
        exam = load_exam(session, exam_id)
        for r in session.scalars(select(AnswerRequest).where(AnswerRequest.exam_id == exam_id)):
            session.delete(r)
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
    def download_pdf(exam_id: int, name: str, user: User = U, session: Session = S):
        exam = load_exam(session, exam_id)
        b = next((b for b in exam.builds if b.name == name and b.status == BuildStatus.DONE), None)
        if b is not None and not can_download(session, user, exam, b.kind):
            raise HTTPException(403, "chưa được tải file này")
        if b is None or not b.pdf_path or not Path(b.pdf_path).exists():
            raise HTTPException(404, "file chưa có")
        return FileResponse(b.pdf_path, media_type="application/pdf", filename=download_name(exam, name, "pdf"))

    @app.get("/api/exams/{exam_id}/files.zip", dependencies=[STAFF])
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

    def load_attempt(session: Session, attempt_id: int, user: User, write: bool = False) -> Attempt:
        """Lượt luyện của chính mình; admin xem được lượt của mọi người nhưng không làm thay."""
        a = session.get(Attempt, attempt_id)
        if a is None or (a.user_id != user.id and (write or user.role != Role.ADMIN)):
            raise HTTPException(404, f"không có lượt luyện #{attempt_id}")
        return a

    def check_quick(session: Session, user: User) -> None:
        if not is_staff(user) and not get_setting(session, "student_quick"):
            raise HTTPException(403, "luyện nhanh từ ngân hàng chưa mở cho học viên")

    @app.post("/api/attempts", status_code=201)
    def start_attempt(body: AttemptIn, user: User = U, session: Session = S):
        try:
            if body.exam_id is not None:
                exam = load_exam(session, body.exam_id)
                if not is_staff(user) and not exam.published:
                    raise HTTPException(404, f"không có đề #{body.exam_id}")
                a = practice.start_from_exam(session, exam, body.variant, body.timed, user.id)
            elif body.retry_of is not None:
                check_quick(session, user)
                spec = practice.retry_spec(load_attempt(session, body.retry_of, user, write=True), session, user.id)
                a = practice.start_quick(session, spec, user_id=user.id)
            elif body.quick is not None:
                check_quick(session, user)
                qk = body.quick
                counts = {"mcq": qk.mcq, "tf": qk.tf, "short": qk.short, "essay": qk.essay}
                spec = practice.quick_spec(qk.title, qk.tag, qk.level.value if qk.level else None, counts)
                a = practice.start_quick(session, spec, qk.duration, user.id)
            else:
                raise HTTPException(422, "cần exam_id, quick hoặc retry_of")
        except practice.PracticeError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        a.user_id = user.id
        session.commit()
        return attempt_json(a, full=True)

    @app.get("/api/attempts")
    def list_attempts(exam_id: int | None = None, all: bool = False, user_id: int | None = None,
                      user: User = U, session: Session = S):
        """Lượt luyện của mình; admin thêm `all=true` (hoặc `user_id`) để xem của người khác."""
        q = select(Attempt).order_by(Attempt.started_at.desc(), Attempt.id.desc())
        if user.role == Role.ADMIN and (all or user_id is not None):
            if user_id is not None:
                q = q.where(Attempt.user_id == user_id)
        else:
            q = q.where(Attempt.user_id == user.id)
        if exam_id is not None:
            q = q.where(Attempt.exam_id == exam_id)
        names = {u.id: u.display_name for u in session.scalars(select(User))}
        return [{**attempt_json(a), "user_name": names.get(a.user_id)} for a in session.scalars(q)]

    @app.get("/api/attempts/stats")
    def attempt_stats(user_id: int | None = None, user: User = U, session: Session = S):
        if user_id is not None and user_id != user.id and user.role != Role.ADMIN:
            raise HTTPException(403, "tài khoản của bạn không có quyền này")
        return practice.stats(session, user_id=user_id if user_id is not None else user.id)

    @app.get("/api/attempts/{attempt_id}")
    def get_attempt(attempt_id: int, user: User = U, session: Session = S):
        a = load_attempt(session, attempt_id, user)
        owner = session.get(User, a.user_id) if a.user_id else None
        data = {**attempt_json(a, full=True), "user_name": owner.display_name if owner else None}
        if a.submitted_at is not None:  # xem lại bài: câu nào có lý thuyết thì có nút "Xem lý thuyết"
            codes = [q["code"] for sec in a.data["sections"] for q in sec["questions"]]
            data["theory_links"] = theory.question_links(session, codes)
        return data

    @app.put("/api/attempts/{attempt_id}/answers", status_code=204)
    def save_answers(attempt_id: int, body: AnswersIn, user: User = U, session: Session = S):
        try:
            practice.save_answers(session, load_attempt(session, attempt_id, user, write=True), body.answers)
        except practice.PracticeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/attempts/{attempt_id}/submit")
    def submit_attempt(attempt_id: int, body: AnswersIn | None = None, user: User = U, session: Session = S):
        a = load_attempt(session, attempt_id, user, write=True)
        try:
            practice.submit(session, a, body.answers if body else None)
        except practice.PracticeError as e:
            raise HTTPException(409, str(e))
        return attempt_json(a, full=True)

    @app.delete("/api/attempts/{attempt_id}", status_code=204)
    def delete_attempt(attempt_id: int, user: User = STAFF, session: Session = S):
        # admin xoá được mọi lượt, Soạn đề chỉ lượt của mình, học viên không xoá
        session.delete(load_attempt(session, attempt_id, user, write=user.role != Role.ADMIN))
        session.commit()

    # ---------- Lý thuyết ----------

    def theory_topic(path: str) -> dict:
        t = theory.find_topic(path)
        if t is None:
            raise HTTPException(404, f"không có chủ đề {path} trong khung chương trình")
        return t

    @app.get("/api/theory/topics")
    def theory_topics(user: User = U, session: Session = S):
        """Khung chương trình theo lớp, mỗi chủ đề kèm số khối lý thuyết đã duyệt / nháp."""
        student = user.role == Role.STUDENT
        counts = theory.counts(session)
        grades = []
        for g in aigen.load_curriculum():
            items = []
            for t in g["chu_de"]:
                if t.get("label"):
                    continue
                c = counts.get(t["path"], {"approved": 0, "draft": 0})
                if student and not c["approved"]:
                    continue
                items.append({"path": t["path"], "ten": t["ten"], "chuong": t["chuong"], "n_dang": len(t["dang"]),
                              "approved": c["approved"], "draft": 0 if student else c["draft"]})
            if items:
                grades.append({"ten": g["ten"], "slug": g["slug"], "bac": g["bac"], "topics": items})
        return {"grades": grades, "kinds": theory.KINDS}

    @app.get("/api/theory/topic")
    def theory_get(path: str, user: User = U, session: Session = S):
        t = theory_topic(path)
        student = user.role == Role.STUDENT
        blocks = theory.topic_blocks(session, t["path"], approved_only=student)
        refs = theory_refs(session, blocks, approved_only=student)
        data = {"topic": theory_topic_json(t), "kinds": theory.KINDS,
                "blocks": [theory_block_json(b, refs) for b in blocks if not (student and b.ref_code
                                                                              and b.ref_code not in refs)]}
        if not student:
            data["source"] = theory.to_source(blocks)
            logs = session.scalars(select(TheoryLog).where(TheoryLog.topic_path == t["path"])
                                   .order_by(TheoryLog.id.desc()).limit(30))
            data["logs"] = [{"id": lg.id, "username": lg.username, "action": lg.action, "detail": lg.detail,
                             "at": lg.at.isoformat(timespec="seconds"), "has_before": bool(lg.before)} for lg in logs]
        return data

    @app.get("/api/theory/logs/{log_id}", dependencies=[STAFF])
    def theory_log(log_id: int, session: Session = S):
        lg = session.get(TheoryLog, log_id)
        if lg is None:
            raise HTTPException(404, "không có bản ghi này")
        return {"id": lg.id, "path": lg.topic_path, "before": lg.before or ""}

    @app.post("/api/theory/parse", dependencies=[STAFF])
    def theory_parse(body: TheoryParseIn, session: Session = S):
        default = theory_topic(body.path) if body.path else None
        return theory_parsed_json(session, theory.parse(body.source, default))

    @app.put("/api/theory/topic")
    def theory_save(body: TheorySaveIn, user: User = STAFF, session: Session = S):
        if body.approve and user.role != Role.ADMIN:
            raise HTTPException(403, "chỉ admin được duyệt lý thuyết")
        t = theory_topic(body.path)
        parsed = theory.parse(body.source, t)
        if parsed.errors:
            ln, msg = parsed.errors[0]
            raise HTTPException(422, f"dòng {ln}: {msg}")
        other = [sec for sec in parsed.sections if sec.topic["path"] != t["path"]]
        if other:
            raise HTTPException(422, f"trang này chỉ soạn chủ đề {t['ten']}; bỏ dòng % @chude: "
                                     f"{' / '.join(other[0].topic['names'])} hoặc dùng trang Import")
        blocks = parsed.sections[0].blocks if parsed.sections else []
        result = theory.save_topic(session, t, blocks, approve=body.approve, username=user.username)
        return {**result, **theory_get(t["path"], user, session)}

    @app.post("/api/theory/topic/approve", dependencies=[ADMIN])
    def theory_approve(body: TheoryPathIn, user: User = U, session: Session = S):
        t = theory_topic(body.path)
        return {"approved": theory.approve_topic(session, t["path"], user.username)}

    @app.post("/api/theory/import/preview", dependencies=[STAFF])
    def theory_import_preview(body: TheoryParseIn, session: Session = S):
        default = theory_topic(body.path) if body.path else None
        data = theory_parsed_json(session, theory.parse(body.source, default))
        counts = theory.counts(session)
        for sec in data["sections"]:
            c = counts.get(sec["topic"]["path"], {"approved": 0, "draft": 0})
            sec["existing"] = c["approved"] + c["draft"]
        return data

    @app.post("/api/theory/import/commit")
    def theory_import_commit(body: TheoryImportIn, user: User = STAFF, session: Session = S):
        if body.approve and user.role != Role.ADMIN:
            raise HTTPException(403, "chỉ admin được duyệt lý thuyết")
        default = theory_topic(body.path) if body.path else None
        parsed = theory.parse(body.source, default)
        if parsed.errors:
            ln, msg = parsed.errors[0]
            raise HTTPException(422, f"dòng {ln}: {msg}")
        topics = []
        for sec in parsed.sections:
            if body.only is not None and sec.topic["path"] not in body.only:
                continue
            r = theory.save_topic(session, sec.topic, sec.blocks, approve=body.approve, username=user.username,
                                  source=body.filename or "import", append=body.mode == "append", action="import")
            topics.append({"path": sec.topic["path"], "ten": sec.topic["ten"], **r})
        return {"topics": topics}

    # ---------- Chuyên đề (lý thuyết + bài tập, xuất PDF) ----------

    def doc_json(doc: TopicDoc, full: bool = False) -> dict:
        data = doc.data or {}
        out = {"id": doc.id, "title": doc.title, "username": doc.username,
               "created_at": doc.created_at.isoformat(timespec="seconds"), "status": doc.status.value,
               "error": doc.error, "error_question": doc.error_question, "count": data.get("count", 0),
               "topics": [t["ten"] for t in data.get("topics", [])],
               "finished_at": doc.finished_at.isoformat(timespec="seconds") if doc.finished_at else None}
        if full:
            out.update(config=doc.config, notes=data.get("notes", []), outline=[
                {"ten": t["ten"], "path": t["path"], "general": len(t["general"]), "mixed": [q["code"] for q in t["mixed"]],
                 "dang": [{"name": d["name"], "theory": len(d["theory"]),
                           "exercises": [{"code": q["code"], "level": q["level"], "number": q["number"]}
                                         for q in d["exercises"]]} for d in t["dang"]]}
                for t in data.get("topics", [])])
        return out

    def load_doc(session: Session, doc_id: int) -> TopicDoc:
        doc = session.get(TopicDoc, doc_id)
        if doc is None:
            raise HTTPException(404, f"không có chuyên đề #{doc_id}")
        return doc

    @app.post("/api/topic-docs/availability", dependencies=[STAFF])
    def topic_doc_availability(body: TopicDocIn, session: Session = S):
        try:
            return chuyende.availability(session, body.model_dump())
        except chuyende.DocError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/topic-docs", dependencies=[STAFF])
    def topic_doc_list(session: Session = S):
        return [doc_json(d) for d in session.scalars(select(TopicDoc).order_by(TopicDoc.id.desc()))]

    @app.post("/api/topic-docs", status_code=201)
    def topic_doc_create(body: TopicDocIn, user: User = STAFF, session: Session = S):
        try:
            doc = chuyende.create(session, body.model_dump(), user.username)
        except chuyende.DocError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return doc_json(doc, full=True)

    @app.get("/api/topic-docs/{doc_id}", dependencies=[STAFF])
    def topic_doc_get(doc_id: int, session: Session = S):
        return doc_json(load_doc(session, doc_id), full=True)

    @app.post("/api/topic-docs/{doc_id}/refresh", dependencies=[STAFF])
    def topic_doc_refresh(doc_id: int, reselect: bool = False, session: Session = S):
        return doc_json(chuyende.refresh(session, load_doc(session, doc_id), reselect), full=True)

    @app.delete("/api/topic-docs/{doc_id}", status_code=204, dependencies=[ADMIN])
    def topic_doc_delete(doc_id: int, session: Session = S):
        doc = load_doc(session, doc_id)
        session.delete(doc)
        session.commit()
        shutil.rmtree(chuyende.doc_dir(doc_id), ignore_errors=True)

    @app.get("/api/topic-docs/{doc_id}/chuyen-de.pdf", dependencies=[STAFF])
    def topic_doc_pdf(doc_id: int, download: bool = False, session: Session = S):
        doc = load_doc(session, doc_id)
        if doc.status != BuildStatus.DONE or not doc.pdf_path or not Path(doc.pdf_path).exists():
            raise HTTPException(404, "chưa có file PDF")
        name = f"chuyen-de-{doc.id}.pdf"
        return FileResponse(doc.pdf_path, media_type="application/pdf", filename=name if download else None,
                            content_disposition_type="attachment" if download else "inline")

    @app.get("/api/topic-docs/{doc_id}/chuyen-de.tex", dependencies=[STAFF])
    def topic_doc_tex(doc_id: int, session: Session = S):
        """File .tex kèm nhd.sty, nhd-hinh.sty (nén .zip) để sửa tiếp ngoài hệ thống."""
        doc = load_doc(session, doc_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("chuyen-de.tex", doc.tex)
            for name in render.STYLE_FILES:
                z.write(render.TEMPLATE_DIR / name, name)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="chuyen-de-{doc.id}-tex.zip"'})

    # ---------- Sinh câu hỏi bằng AI ----------

    @app.get("/api/gen/curriculum", dependencies=[STAFF])
    def gen_curriculum():
        return {"grades": aigen.load_curriculum(), "api": aigen.api_available(), "model": aigen.model_name(),
                "max_count": aigen.MAX_COUNT, "max_total": aigen.MAX_TOTAL,
                "max_prompt": aigen.MAX_PROMPT}

    @app.get("/api/gen/coverage", dependencies=[STAFF])
    def gen_coverage(grade: str, session: Session = S):
        return aigen.coverage(session, grade)

    @app.post("/api/gen/prompt", dependencies=[STAFF])
    def gen_prompt(body: GenParamsIn, session: Session = S):
        try:
            system, user = aigen.build_prompt(session, body.model_dump(mode="json"))
        except aigen.GenError as e:
            raise HTTPException(422, str(e))
        return {"system": system, "user": user, "combined": aigen.combined_prompt(system, user)}

    @app.post("/api/gen/check", dependencies=[STAFF])
    def gen_check(body: GenCheckIn, session: Session = S):
        try:
            items = aigen.check_output(session, body.params.model_dump(mode="json"), body.output)
        except aigen.GenError as e:
            raise HTTPException(422, str(e))
        for it in items:
            it.pop("parsed")
        return items

    def rows_of(body: GenRowsIn) -> list[dict]:
        return [r.model_dump(mode="json") for r in body.rows]

    @app.post("/api/gen/prompt/multi", dependencies=[STAFF])
    def gen_prompt_multi(body: GenRowsIn, session: Session = S):
        """Prompt gộp nhiều ô để chép sang Claude."""
        try:
            system, user = aigen.build_multi_prompt(session, rows_of(body))
        except aigen.GenError as e:
            raise HTTPException(422, str(e))
        return {"system": system, "user": user, "combined": aigen.combined_prompt(system, user)}

    @app.post("/api/gen/check/multi", dependencies=[STAFF])
    def gen_check_multi(body: GenMultiCheckIn, session: Session = S):
        try:
            return aigen.check_multi(session, rows_of(body), body.output)
        except aigen.GenError as e:
            raise HTTPException(422, str(e))

    @app.post("/api/gen/batches/multi", status_code=201)
    def gen_create_multi(body: GenMultiIn, user: User = STAFF, session: Session = S):
        """Một đợt sinh nhiều ô: mỗi ô một lần sinh, chung mã đợt."""
        try:
            batches = aigen.create_group(session, rows_of(body), body.mode, body.output,
                                         user_id=user.id, username=user.username, group_id=body.group_id)
        except aigen.GenError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return {"group_id": batches[0].group_id, "batches": [batch_json(b) for b in batches]}

    # ---------- Sinh biến thể hàng loạt ----------

    @app.post("/api/gen/variants/plan", dependencies=[STAFF])
    def variant_plan(body: VariantPlanIn, session: Session = S):
        """Câu gốc cho đợt sinh biến thể theo chủ đề, theo đề, hoặc theo các câu đang chọn."""
        if body.exam_id is not None:
            exam = load_exam(session, body.exam_id)
            qs = [it.question for it in sorted(exam.items, key=lambda it: (it.section, it.position))]
        elif body.codes:
            qs = [bank.get_question(session, c) for c in body.codes]
        elif body.q and body.q.strip():
            text = body.q.strip()
            qs = list(session.scalars(bank.question_query(text=text, tag=body.tag or None)
                                      .order_by(Question.id).limit(1000)))
        elif body.tag:
            qs = list(session.scalars(bank.question_query(tag=body.tag).order_by(Question.id)))
        else:
            raise HTTPException(422, "cần chọn chủ đề, đề hoặc các câu")
        if body.levels:
            qs = [q for q in qs if q is not None and q.level in body.levels]
        if body.types:
            qs = [q for q in qs if q is not None and q.type in body.types]
        plan = aigen.plan_variants(session, qs, body.computational_only)
        found = {q.code.upper() for q in qs if q is not None}
        typed = bank.code_list(body.q) if body.q and not body.codes and body.exam_id is None else []
        plan["skipped"] += [{"code": c, "reason": "không có trong ngân hàng"} for c in typed if c.upper() not in found]
        if typed:  # nhập nhiều mã: giữ đúng thứ tự đã gõ
            order = {c.upper(): i for i, c in enumerate(typed)}
            plan["sources"].sort(key=lambda q: order.get(q.code.upper(), len(order)))
        sizes = {}
        for q in plan["sources"]:
            if q.variant_group and q.variant_group not in sizes:
                sizes[q.variant_group] = bank.group_size(session, q.variant_group)
        labels = {g.code: g.label for g in session.scalars(
            select(VariantGroup).where(VariantGroup.code.in_(list(sizes))))} if sizes else {}
        return {
            "sources": [{**question_json(q), "n_variants": sizes.get(q.variant_group, 1),
                         "variant_label": labels.get(q.variant_group)} for q in plan["sources"]],
            "skipped": plan["skipped"],
            "max_sources": aigen.MAX_SOURCES, "max_per": aigen.MAX_PER, "pack": aigen.PACK,
        }

    def variant_rows(body: VariantRunIn, session: Session) -> list[dict]:
        try:
            packs = aigen.variant_packs(session, body.codes, body.per, body.param)
        except aigen.GenError as e:
            raise HTTPException(422, str(e))
        notes = (body.notes or "").strip() or None
        return [{**p, "notes": notes} for p in packs]

    @app.post("/api/gen/variants/prompts", dependencies=[STAFF])
    def variant_prompts(body: VariantRunIn, session: Session = S):
        """Prompt dán tay, mỗi phần là một gói câu gốc."""
        out = []
        for p in variant_rows(body, session):
            system, user = aigen.build_prompt(session, p)
            out.append({"codes": p["variants_of"], "count": p["count"],
                        "combined": aigen.combined_prompt(system, user)})
        return {"parts": out}

    @app.post("/api/gen/variants/check", dependencies=[STAFF])
    def variant_check(body: VariantRunIn, session: Session = S):
        rows = variant_rows(body, session)
        if len(rows) != 1:
            raise HTTPException(422, "mỗi lần kiểm tra đúng một phần (một prompt)")
        try:
            items = aigen.check_output(session, rows[0], body.output or "")
        except aigen.GenError as e:
            raise HTTPException(422, str(e))
        for it in items:
            it.pop("parsed")
        return items

    @app.post("/api/gen/variants/batches", status_code=201)
    def variant_batches(body: VariantRunIn, user: User = STAFF, session: Session = S):
        """Đợt sinh biến thể: mỗi gói câu gốc một lần sinh, chung mã đợt."""
        notes = (body.notes or "").strip() or None
        try:
            batches = aigen.create_variant_group(session, body.codes, body.per, body.mode, body.output,
                                                 user_id=user.id, username=user.username, group_id=body.group_id,
                                                 notes=notes, param=body.param)
        except aigen.GenError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return {"group_id": batches[0].group_id, "batches": [batch_json(b) for b in batches]}

    @app.post("/api/gen/batches", status_code=201)
    def gen_create(body: GenBatchIn, user: User = STAFF, session: Session = S):
        try:
            batch = aigen.create_batch(session, body.params.model_dump(mode="json"), body.mode, body.output,
                                       user_id=user.id, username=user.username)
        except aigen.GenError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return batch_json(batch, full=True)

    # ---------- Claude soạn lý thuyết ----------

    def theory_gen_params(session: Session, body: TheoryGenIn) -> list[dict]:
        out = []
        for path in body.paths:
            t = theory_topic(path)
            miss = theorygen.missing_parts(session, t)
            general = body.general if body.general is not None else (True if body.all_parts else miss["general"])
            if body.dang is not None and len(body.paths) == 1:
                dang = body.dang
            else:
                dang = t["dang"] if body.all_parts else miss["dang"]
            if not general and not dang:
                if len(body.paths) == 1:
                    raise HTTPException(422, f"{t['ten']}: chưa chọn phần nào để soạn")
                continue  # chủ đề đã đủ lý thuyết
            out.append({"path": t["path"], "general": general, "dang": dang, "examples": body.examples,
                        "note": body.note})
        if not out:
            raise HTTPException(422, "các chủ đề đã chọn đều đã có đủ lý thuyết")
        return out

    def theory_batch_json(b: GenerationBatch) -> dict:
        t = theory.find_topic(b.params.get("path", ""))
        return {**batch_json(b), "topic": t["ten"] if t else b.params.get("path"),
                "added": sum(it.get("added", 0) for it in b.items or []),
                "kinds": (b.items or [{}])[0].get("kinds", {}) if b.items else {}}

    @app.post("/api/theory/gen/prompt", dependencies=[STAFF])
    def theory_gen_prompt(body: TheoryGenIn, session: Session = S):
        if len(body.paths) != 1:
            raise HTTPException(422, "cách chép prompt chỉ làm từng chủ đề")
        try:
            p = theorygen.normalize(theory_gen_params(session, body)[0])
        except aigen.GenError as e:
            raise HTTPException(422, str(e))
        system, user = theorygen.build_prompt(session, p)
        return {"params": p, "system": system, "user": user, "combined": aigen.combined_prompt(system, user)}

    @app.post("/api/theory/gen", status_code=201)
    def theory_gen(body: TheoryGenIn, user: User = STAFF, session: Session = S):
        rows = theory_gen_params(session, body)
        if body.mode == "manual" and len(rows) != 1:
            raise HTTPException(422, "cách chép prompt chỉ làm từng chủ đề")
        if len(rows) > theorygen.MAX_TOPICS:
            raise HTTPException(422, f"mỗi đợt tối đa {theorygen.MAX_TOPICS} chủ đề")
        group = f"T{datetime.now():%y%m%d%H%M%S}" if len(rows) > 1 else None
        try:
            batches = [theorygen.create(session, r, body.mode, body.output, user_id=user.id, username=user.username,
                                        group_id=group) for r in rows]
        except aigen.GenError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return [theory_batch_json(b) for b in batches]

    @app.get("/api/theory/gen", dependencies=[STAFF])
    def theory_gen_list(path: str | None = None, session: Session = S):
        return {"api": aigen.api_available(), "model": aigen.model_name(),
                "batches": [theory_batch_json(b) for b in theorygen.batches(session, path)]}

    @app.get("/api/theory/gen/{batch_id}", dependencies=[STAFF])
    def theory_gen_get(batch_id: int, session: Session = S):
        b = load_batch(session, batch_id)
        return {**theory_batch_json(b), "output": b.output, "system_prompt": b.system_prompt,
                "user_prompt": b.user_prompt}

    @app.get("/api/gen/batches", dependencies=[STAFF])
    def gen_list(session: Session = S):
        """Mọi lần sinh (trang Sinh câu AI nhóm theo khung chương trình), kèm số câu còn chờ duyệt."""
        pending = dict(session.execute(
            select(Question.source, func.count())
            .where(Question.status == Status.DRAFT, Question.source.startswith("AI #"))
            .group_by(Question.source)
        ).all())
        rows = session.scalars(select(GenerationBatch).where(GenerationBatch.kind.is_(None))
                               .order_by(GenerationBatch.id.desc()))
        return [batch_json(b, n_pending=pending.get(b.source, 0)) for b in rows]

    def load_batch(session: Session, batch_id: int) -> GenerationBatch:
        b = session.get(GenerationBatch, batch_id)
        if b is None:
            raise HTTPException(404, f"không có lần sinh #{batch_id}")
        return b

    @app.get("/api/gen/batches/{batch_id}", dependencies=[STAFF])
    def gen_get(batch_id: int, session: Session = S):
        return batch_json(load_batch(session, batch_id), full=True)

    @app.post("/api/gen/batches/{batch_id}/retry", dependencies=[STAFF])
    def gen_retry(batch_id: int, session: Session = S):
        b = load_batch(session, batch_id)
        if b.mode != "api" or b.status != BuildStatus.FAILED:
            raise HTTPException(409, "chỉ chạy lại được lần sinh qua API bị lỗi")
        b.status, b.error, b.finished_at = BuildStatus.PENDING, None, None
        session.commit()
        return batch_json(b, full=True)

    # ---------- Sao lưu và khôi phục ----------

    def attachment(name: str) -> dict:
        return {"Content-Disposition": f'attachment; filename="{name}"'}

    @app.get("/api/backup/info", dependencies=[ADMIN])
    def backup_info():
        n_files, size = backup.files_size()
        return {
            "tables": [
                {"name": t, "label": backup.TABLE_NAMES.get(t, t), "count": n}
                for t, n in backup.table_counts(engine).items()
            ],
            "files": n_files,
            "files_size": size,
            "folder": str(backup.backups_dir()),
            "backups": backup.list_backups(),
        }

    @app.get("/api/backup/download", dependencies=[ADMIN])
    def backup_download(files: bool = True):
        """Tạo bản sao lưu và tải về ngay (không giữ lại trên máy chủ)."""
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        try:
            with tmp:
                backup.write_backup(engine, tmp, include_files=files)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise
        return FileResponse(
            tmp.name,
            media_type="application/zip",
            filename=backup.backup_name(),
            background=BackgroundTask(Path(tmp.name).unlink, missing_ok=True),
        )

    @app.post("/api/backup/save", status_code=201, dependencies=[ADMIN])
    def backup_save(files: bool = True):
        """Lưu một bản sao lưu vào thư mục sao lưu trên máy chủ."""
        return {"name": backup.save_backup(engine, include_files=files).name}

    def stored(name: str) -> Path:
        try:
            return backup.stored_backup(name)
        except backup.BackupError as e:
            raise HTTPException(404, str(e))

    @app.get("/api/backup/stored/{name}", dependencies=[ADMIN])
    def backup_stored(name: str):
        return FileResponse(stored(name), media_type="application/zip", filename=name)

    @app.delete("/api/backup/stored/{name}", status_code=204, dependencies=[ADMIN])
    def backup_delete(name: str):
        stored(name).unlink()

    async def upload_or_stored(request: Request, name: str | None) -> bytes | Path:
        if name:
            return stored(name)
        body = await request.body()
        if not body:
            raise HTTPException(422, "chưa chọn file sao lưu")
        return body

    @app.post("/api/backup/inspect", dependencies=[ADMIN])
    async def backup_inspect(request: Request, name: str | None = None):
        """Đọc thử file sao lưu (gửi nội dung .zip làm thân yêu cầu, hoặc tên một bản trên máy chủ)."""
        src = await upload_or_stored(request, name)

        def inspect():
            z, archive = backup.open_archive(src)
            with z:
                return backup.summary(archive)

        try:
            return await run_in_threadpool(inspect)
        except backup.BackupError as e:
            raise HTTPException(422, str(e))

    @app.post("/api/backup/restore")
    async def backup_restore(request: Request, response: Response, name: str | None = None,
                             me: User = ADMIN):
        """Thay toàn bộ dữ liệu bằng file sao lưu; dữ liệu hiện tại được lưu một bản trước."""
        src = await upload_or_stored(request, name)
        username = me.username
        try:
            result = await run_in_threadpool(backup.restore, engine, src)
        except backup.BackupError as e:
            raise HTTPException(422, str(e))
        with SessionLocal() as session:
            auth.claim_orphan_attempts(session)
            session.commit()
            # bản sao lưu có tài khoản thì mọi phiên cũ mất; giữ đăng nhập cho người vừa khôi phục
            # nếu tài khoản của họ trong bản đó vẫn là admin
            user = auth.get_user(session, username)
            result["relogin"] = user is None or not user.active or user.role != Role.ADMIN
            if not result["relogin"] and auth.session_user(session, request.cookies.get(COOKIE)) is None:
                set_cookie(response, auth.start_session(session, user))
        return result

    @app.get("/api/export/questions.tex", dependencies=[ADMIN])
    def export_questions(session: Session = S):
        """Toàn bộ câu hỏi theo định dạng soạn, import lại được ở trang Import."""
        rows = session.scalars(select(Question).order_by(Question.code))
        parts = [
            f"% Ngân hàng đề: toàn bộ câu hỏi, xuất lúc {datetime.now():%d/%m/%Y %H:%M}",
            "% Import lại ở trang Import hoặc bằng lệnh: nhd import <file>",
            "",
        ]
        for q in rows:
            if q.status == Status.DRAFT:
                parts.append("% (nháp)")
            parts += [question_to_ex(q), ""]
        name = f"ngan-hang-cau-hoi-{datetime.now():%Y%m%d}.tex"
        return Response("\n".join(parts), media_type="text/plain; charset=utf-8", headers=attachment(name))

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
