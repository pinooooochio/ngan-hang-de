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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import aigen, auth, backup, bank, builds, generator, practice, render
from .compile import compile_tex, latex_available
from .db import get_url, upgrade_schema
from .models import (
    ROLE_NAMES,
    AnswerRequest,
    Attempt,
    Base,
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


class GenCheckIn(BaseModel):
    params: GenParamsIn
    output: str


class GenBatchIn(BaseModel):
    params: GenParamsIn
    mode: str = Field("api", pattern="^(api|manual)$")
    output: str | None = None


def batch_json(b: GenerationBatch, full: bool = False) -> dict:
    items = b.items or []
    data = {
        "id": b.id,
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


# ---------- Ứng dụng ----------


def create_app(db_url: str | None = None, worker: bool = False) -> FastAPI:
    url = db_url or get_url()
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    upgrade_schema(engine)
    SessionLocal = sessionmaker(engine)

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
        limit: int = 50,
        offset: int = 0,
        session: Session = S,
    ):
        stmt = bank.question_query(tag, level, type, status, q, source)
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(stmt.order_by(Question.updated_at.desc(), Question.id.desc()).limit(limit).offset(offset))
        return {"total": total, "items": [question_json(r, full=False) for r in rows]}

    @app.get("/api/questions/{code}", dependencies=[STAFF])
    def get_question(code: str, session: Session = S):
        q = bank.get_question(session, code)
        if q is None:
            raise HTTPException(404, f"không có câu {code}")
        return question_json(q)

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
        return question_json(q)

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
        return [parsed_json(pq) for pq in parse_text(body.source)]

    @app.get("/api/tags", dependencies=[U])
    def tags(session: Session = S):
        return [
            {"path": n.path, "name": n.name, "depth": d, "count": c, "names": bank.tag_names(n)}
            for n, d, c in bank.tag_tree(session, aigen.curriculum_order())
        ]

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

    @app.post("/api/exams/availability", dependencies=[STAFF])
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
                a = practice.start_from_exam(session, exam, body.variant, body.timed)
            elif body.retry_of is not None:
                check_quick(session, user)
                spec = practice.retry_spec(load_attempt(session, body.retry_of, user, write=True))
                a = practice.start_quick(session, spec)
            elif body.quick is not None:
                check_quick(session, user)
                qk = body.quick
                counts = {"mcq": qk.mcq, "tf": qk.tf, "short": qk.short, "essay": qk.essay}
                spec = practice.quick_spec(qk.title, qk.tag, qk.level.value if qk.level else None, counts)
                a = practice.start_quick(session, spec, qk.duration)
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
        return {**attempt_json(a, full=True), "user_name": owner.display_name if owner else None}

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

    # ---------- Sinh câu hỏi bằng AI ----------

    @app.get("/api/gen/curriculum", dependencies=[STAFF])
    def gen_curriculum():
        return {"grades": aigen.load_curriculum(), "api": aigen.api_available(), "model": aigen.model_name(),
                "max_count": aigen.MAX_COUNT}

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

    @app.post("/api/gen/batches", status_code=201, dependencies=[STAFF])
    def gen_create(body: GenBatchIn, session: Session = S):
        try:
            batch = aigen.create_batch(session, body.params.model_dump(mode="json"), body.mode, body.output)
        except aigen.GenError as e:
            session.rollback()
            raise HTTPException(422, str(e))
        return batch_json(batch, full=True)

    @app.get("/api/gen/batches", dependencies=[STAFF])
    def gen_list(session: Session = S):
        rows = session.scalars(select(GenerationBatch).order_by(GenerationBatch.id.desc()).limit(100))
        return [batch_json(b) for b in rows]

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
