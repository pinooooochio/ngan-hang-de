"""Mô hình dữ liệu: câu hỏi, lựa chọn, cây thẻ, đề, khung đề, mã đề, lượt luyện đề và tài khoản."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class QuestionType(str, enum.Enum):
    MCQ = "mcq"  # trắc nghiệm 4 lựa chọn
    TRUE_FALSE = "tf"  # đúng/sai 4 ý
    SHORT = "short"  # trả lời ngắn
    ESSAY = "essay"  # tự luận


class Level(str, enum.Enum):
    NB = "NB"  # nhận biết
    TH = "TH"  # thông hiểu
    VD = "VD"  # vận dụng
    VDC = "VDC"  # vận dụng cao


LEVEL_NAMES = {
    Level.NB: "Nhận biết",
    Level.TH: "Thông hiểu",
    Level.VD: "Vận dụng",
    Level.VDC: "Vận dụng cao",
}


class Status(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"


class TaxonomyNode(Base):
    """Một nút trong cây thẻ: lớp > chủ đề > dạng bài."""

    __tablename__ = "taxonomy_nodes"
    __table_args__ = (UniqueConstraint("parent_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy_nodes.id"))
    slug: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    # Đường dẫn đầy đủ, ví dụ "lop12/vecto-khong-gian/tich-vo-huong"
    path: Mapped[str] = mapped_column(String(500), unique=True, index=True)

    parent: Mapped[TaxonomyNode | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[TaxonomyNode]] = relationship(back_populates="parent")


class QuestionTag(Base):
    __tablename__ = "question_tags"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("taxonomy_nodes.id"), primary_key=True)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType))
    level: Mapped[Level | None] = mapped_column(Enum(Level))
    stem_latex: Mapped[str] = mapped_column(Text)
    solution_latex: Mapped[str] = mapped_column(Text, default="")
    short_answer: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(300))
    ex_id: Mapped[str | None] = mapped_column(String(64))  # mã ID kiểu ex_test, ví dụ 0D1N1-1
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.APPROVED)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    choices: Mapped[list[Choice]] = relationship(
        back_populates="question", order_by="Choice.position", cascade="all, delete-orphan"
    )
    tags: Mapped[list[TaxonomyNode]] = relationship(secondary="question_tags")


class Choice(Base):
    """Một lựa chọn (MCQ) hoặc một mệnh đề (đúng/sai)."""

    __tablename__ = "choices"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    position: Mapped[int] = mapped_column(Integer)  # thứ tự gốc, từ 0
    content_latex: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[Question] = relationship(back_populates="choices")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    exam_date: Mapped[str | None] = mapped_column(String(20))
    duration: Mapped[int | None] = mapped_column(Integer)  # phút
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # học viên chỉ thấy và làm được đề đã mở
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    items: Mapped[list[ExamItem]] = relationship(
        back_populates="exam", order_by="ExamItem.position", cascade="all, delete-orphan"
    )
    variants: Mapped[list[ExamVariant]] = relationship(
        back_populates="exam", order_by="ExamVariant.code", cascade="all, delete-orphan"
    )
    builds: Mapped[list[Build]] = relationship(
        back_populates="exam", order_by="Build.id", cascade="all, delete-orphan"
    )


class ExamTemplate(Base):
    """Khung đề dùng lại khi ghép đề: các phần, loại câu, điểm và ma trận thẻ × mức độ × số câu.
    `config` cùng dạng với phần gửi lên khi tạo đề (duration, variants, sections[].pick),
    không gồm câu chọn tay vì đó là câu của riêng từng đề."""

    __tablename__ = "exam_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ExamItem(Base):
    __tablename__ = "exam_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    section: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    points: Mapped[float | None] = mapped_column(Float)

    exam: Mapped[Exam] = relationship(back_populates="items")
    question: Mapped[Question] = relationship()


class ExamVariant(Base):
    """Một mã đề. `data` lưu bản chụp nội dung đã hoán vị, nên sửa câu hỏi
    trong ngân hàng không làm đổi đề đã phát."""

    __tablename__ = "exam_variants"
    __table_args__ = (UniqueConstraint("exam_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    code: Mapped[str] = mapped_column(String(20))
    seed: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)
    answer_key: Mapped[dict] = mapped_column(JSON)

    exam: Mapped[Exam] = relationship(back_populates="variants")


class BuildStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Build(Base):
    """Một file PDF cần biên dịch của một đề (đề / lời giải của từng mã đề, bảng đáp án).
    Bảng này cũng là hàng đợi cho worker biên dịch."""

    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))  # ví dụ "de-101"
    kind: Mapped[str] = mapped_column(String(20))  # de | loigiai | dapan
    variant_code: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[BuildStatus] = mapped_column(Enum(BuildStatus), default=BuildStatus.PENDING, index=True)
    tex: Mapped[str] = mapped_column(Text)
    tex_hash: Mapped[str] = mapped_column(String(64), index=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    error_question: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    exam: Mapped[Exam] = relationship(back_populates="builds")


class Attempt(Base):
    """Một lượt luyện đề: làm một mã đề trong kho đề, hoặc luyện nhanh câu lấy từ ngân hàng.
    `data` là bản chụp đề (cùng dạng ExamVariant.data, có đáp án), nên xoá đề hay sửa câu
    hỏi không làm đổi lượt đã làm."""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # exam | quick
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    variant_code: Mapped[str | None] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)  # "phần.câu" -> câu trả lời
    duration: Mapped[int | None] = mapped_column(Integer)  # phút, None = không giới hạn
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)

    items: Mapped[list[AttemptItem]] = relationship(
        back_populates="attempt", order_by="AttemptItem.id", cascade="all, delete-orphan"
    )


class AttemptItem(Base):
    """Kết quả chấm một câu trong lượt luyện; dùng để thống kê theo chủ đề và mức độ."""

    __tablename__ = "attempt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    section: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    question_code: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(10))
    level: Mapped[str | None] = mapped_column(String(10))
    tags: Mapped[list] = mapped_column(JSON, default=list)  # đường dẫn thẻ của câu lúc nộp
    points: Mapped[float] = mapped_column(Float, default=0)
    max_points: Mapped[float] = mapped_column(Float, default=0)
    correct: Mapped[bool | None] = mapped_column(Boolean)  # None: tự luận, không chấm

    attempt: Mapped[Attempt] = relationship(back_populates="items")


class GenerationBatch(Base):
    """Một lần sinh câu hỏi bằng AI. `mode`: "api" (máy chủ gọi Claude) hoặc "manual"
    (người dùng chép prompt sang Claude rồi dán kết quả lại). Câu sinh ra vào ngân hàng ở
    trạng thái nháp, nguồn "AI #<id>". Bảng này cũng là hàng đợi cho worker sinh câu."""

    __tablename__ = "generation_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[BuildStatus] = mapped_column(Enum(BuildStatus), default=BuildStatus.PENDING, index=True)
    params: Mapped[dict] = mapped_column(JSON)  # lớp, chủ đề, dạng, mức độ, loại câu, số câu, ghi chú
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    output: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JSON, default=list)  # kết quả kiểm tra từng câu
    usage: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def source(self) -> str:
        return f"AI #{self.id}"


class Role(str, enum.Enum):
    ADMIN = "admin"  # toàn quyền
    EDITOR = "editor"  # soạn đề: soạn, import, ghép đề; không xoá, không duyệt câu, không cài đặt
    STUDENT = "student"  # học viên: chỉ làm các đề đã mở


ROLE_NAMES = {Role.ADMIN: "Admin", Role.EDITOR: "Soạn đề", Role.STUDENT: "Học viên"}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)


class UserSession(Base):
    """Phiên đăng nhập; cookie giữ mã ngẫu nhiên, bảng chỉ lưu băm của mã. Không đưa vào sao lưu."""

    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class QuestionLog(Base):
    """Nhật ký thay đổi câu hỏi: ai làm gì, lúc nào, kèm nội dung câu trước khi sửa.
    Giữ theo mã câu (không khoá ngoại) để vẫn còn sau khi xoá câu hay xoá tài khoản."""

    __tablename__ = "question_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(20))  # tao | sua | duyet | bo-duyet | xoa | import | hang-loat | the
    detail: Mapped[str | None] = mapped_column(String(500))
    before: Mapped[str | None] = mapped_column(Text)  # câu ở định dạng soạn trước khi sửa
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AnswerRequest(Base):
    """Học viên xin tải PDF đáp án / lời giải của một đề; admin đồng ý thì tải được."""

    __tablename__ = "answer_requests"
    __table_args__ = (UniqueConstraint("user_id", "exam_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | approved | rejected
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String(64))


class Setting(Base):
    """Cài đặt chung dạng khoá -> giá trị JSON."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON)
