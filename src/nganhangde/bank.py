"""Ngân hàng câu hỏi: lưu câu đã phân tích, cây thẻ, tìm kiếm."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Choice, Level, Question, QuestionTag, QuestionType, Status, TaxonomyNode
from .parser import ParsedQuestion, slugify


def get_or_create_path(session: Session, names: list[str]) -> TaxonomyNode:
    """Tạo (nếu chưa có) chuỗi nút theo tên, trả về nút cuối."""
    parent: TaxonomyNode | None = None
    path = ""
    for name in names:
        slug = slugify(name)
        path = f"{path}/{slug}" if path else slug
        node = session.scalar(select(TaxonomyNode).where(TaxonomyNode.path == path))
        if node is None:
            node = TaxonomyNode(slug=slug, name=name, path=path, parent=parent)
            session.add(node)
            session.flush()
        parent = node
    assert parent is not None
    return parent


def next_code(session: Session) -> str:
    n = session.scalar(select(func.count(Question.id))) or 0
    while True:
        n += 1
        code = f"Q{n:05d}"
        if session.scalar(select(Question.id).where(Question.code == code)) is None:
            return code


@dataclass
class ImportReport:
    added: list[str] = field(default_factory=list)
    duplicates: list[tuple[int, str]] = field(default_factory=list)  # (dòng, mã câu đã có)
    failed: list[ParsedQuestion] = field(default_factory=list)
    warned: list[ParsedQuestion] = field(default_factory=list)


def import_questions(
    session: Session,
    parsed: list[ParsedQuestion],
    source: str | None = None,
    status: Status = Status.APPROVED,
    dry_run: bool = False,
) -> ImportReport:
    report = ImportReport()
    for pq in parsed:
        if not pq.ok:
            report.failed.append(pq)
            continue
        h = pq.content_hash()
        existing = session.scalar(select(Question).where(Question.content_hash == h))
        if existing is not None:
            report.duplicates.append((pq.line, existing.code))
            continue
        if pq.code and session.scalar(select(Question.id).where(Question.code == pq.code)):
            pq.errors.append(f"mã câu {pq.code} đã tồn tại với nội dung khác")
            report.failed.append(pq)
            continue
        if pq.warnings:
            report.warned.append(pq)
        if dry_run:
            report.added.append(pq.code or f"(dòng {pq.line})")
            continue
        q = Question(
            code=pq.code or next_code(session),
            type=pq.type,
            level=pq.level,
            stem_latex=pq.stem,
            solution_latex=pq.solution,
            short_answer=pq.short_answer,
            source=pq.source or source,
            ex_id=pq.ex_id,
            status=status,
            content_hash=h,
        )
        q.choices = [
            Choice(position=i, content_latex=c.content, is_correct=c.is_correct, pinned=c.pinned)
            for i, c in enumerate(pq.choices)
        ]
        q.tags = list({id(n): n for n in (get_or_create_path(session, t) for t in pq.tags)}.values())
        session.add(q)
        session.flush()
        report.added.append(q.code)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return report


def find_questions(
    session: Session,
    tag: str | None = None,
    level: Level | None = None,
    type: QuestionType | None = None,
    approved_only: bool = False,
) -> list[Question]:
    """Lọc câu hỏi. `tag` là đường dẫn slug hoặc tên; khớp cả các nút con."""
    stmt = select(Question)
    if tag:
        prefix = "/".join(slugify(p) for p in tag.split("/") if p.strip())
        sub = (
            select(QuestionTag.question_id)
            .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
            .where((TaxonomyNode.path == prefix) | TaxonomyNode.path.startswith(prefix + "/"))
        )
        stmt = stmt.where(Question.id.in_(sub))
    if level:
        stmt = stmt.where(Question.level == level)
    if type:
        stmt = stmt.where(Question.type == type)
    if approved_only:
        stmt = stmt.where(Question.status == Status.APPROVED)
    return list(session.scalars(stmt.order_by(Question.code)))


def tag_tree(session: Session) -> list[tuple[TaxonomyNode, int, int]]:
    """Trả về (nút, độ sâu, số câu thuộc nút và các nút con), duyệt theo thứ tự cây."""
    nodes = list(session.scalars(select(TaxonomyNode).order_by(TaxonomyNode.name)))
    children: dict[int | None, list[TaxonomyNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    out: list[tuple[TaxonomyNode, int, int]] = []

    def visit(node: TaxonomyNode, depth: int) -> None:
        count = session.scalar(
            select(func.count(func.distinct(QuestionTag.question_id)))
            .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
            .where((TaxonomyNode.path == node.path) | TaxonomyNode.path.startswith(node.path + "/"))
        )
        out.append((node, depth, count or 0))
        for child in children.get(node.id, []):
            visit(child, depth + 1)

    for root in children.get(None, []):
        visit(root, 0)
    return out
