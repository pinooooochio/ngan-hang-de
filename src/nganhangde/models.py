"""Mô hình dữ liệu: câu hỏi, lựa chọn, cây thẻ, đề và mã đề."""

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

    items: Mapped[list[ExamItem]] = relationship(
        back_populates="exam", order_by="ExamItem.position", cascade="all, delete-orphan"
    )
    variants: Mapped[list[ExamVariant]] = relationship(
        back_populates="exam", order_by="ExamVariant.code", cascade="all, delete-orphan"
    )
    builds: Mapped[list[Build]] = relationship(
        back_populates="exam", order_by="Build.id", cascade="all, delete-orphan"
    )


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
