"""Ngân hàng câu hỏi: lưu câu đã phân tích, cây thẻ, tìm kiếm."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .models import Choice, Level, Question, QuestionTag, QuestionType, Status, TaxonomyNode
from .parser import ParsedQuestion, slugify


class BankError(Exception):
    pass


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


def get_question(session: Session, code: str) -> Question | None:
    return session.scalar(select(Question).where(Question.code == code))


def _apply(session: Session, q: Question, pq: ParsedQuestion) -> None:
    """Ghi nội dung câu đã phân tích vào bản ghi `q`."""
    q.type = pq.type
    q.level = pq.level
    q.stem_latex = pq.stem
    q.solution_latex = pq.solution
    q.short_answer = pq.short_answer
    q.ex_id = pq.ex_id
    if pq.source:
        q.source = pq.source
    q.content_hash = pq.content_hash()
    q.choices = [
        Choice(position=i, content_latex=c.content, is_correct=c.is_correct, pinned=c.pinned)
        for i, c in enumerate(pq.choices)
    ]
    q.tags = list({id(n): n for n in (get_or_create_path(session, t) for t in pq.tags)}.values())


def _check_conflicts(session: Session, pq: ParsedQuestion, own_id: int | None) -> None:
    if not pq.ok:
        raise BankError("; ".join(pq.errors))
    dup = session.scalar(select(Question).where(Question.content_hash == pq.content_hash()))
    if dup is not None and dup.id != own_id:
        raise BankError(f"trùng nội dung với câu {dup.code}")
    if pq.code:
        other = get_question(session, pq.code)
        if other is not None and other.id != own_id:
            raise BankError(f"mã câu {pq.code} đã được dùng")


def create_question(session: Session, pq: ParsedQuestion, status: Status = Status.DRAFT) -> Question:
    _check_conflicts(session, pq, None)
    q = Question(code=pq.code or next_code(session), status=status, source=pq.source)
    _apply(session, q, pq)
    session.add(q)
    session.commit()
    return q


def update_question(session: Session, code: str, pq: ParsedQuestion) -> Question:
    """Cập nhật câu hỏi. Mã câu đổi được qua `@id`. Đề đã sinh giữ bản chụp riêng nên không bị ảnh hưởng."""
    q = get_question(session, code)
    if q is None:
        raise BankError(f"không có câu {code}")
    _check_conflicts(session, pq, q.id)
    if pq.code:
        q.code = pq.code
    _apply(session, q, pq)
    q.version += 1
    session.commit()
    return q


def delete_question(session: Session, code: str) -> None:
    from .models import ExamItem

    q = get_question(session, code)
    if q is None:
        raise BankError(f"không có câu {code}")
    if session.scalar(select(ExamItem.id).where(ExamItem.question_id == q.id)):
        raise BankError(f"câu {code} đã nằm trong một đề, không xoá được")
    session.execute(QuestionTag.__table__.delete().where(QuestionTag.question_id == q.id))
    session.delete(q)
    session.commit()


def bulk_update(
    session: Session,
    codes: list[str],
    add_tag: list[str] | None = None,
    level: Level | None = None,
    status: Status | None = None,
) -> int:
    """Gắn thêm thẻ, đặt mức độ hoặc trạng thái cho nhiều câu cùng lúc."""
    node = get_or_create_path(session, add_tag) if add_tag else None
    qs = list(session.scalars(select(Question).where(Question.code.in_(codes))))
    for q in qs:
        if node is not None and node not in q.tags:
            q.tags.append(node)
        if level is not None:
            q.level = level
        if status is not None:
            q.status = status
    session.commit()
    return len(qs)


@dataclass
class ImportItem:
    index: int
    parsed: ParsedQuestion
    state: str  # "new" | "duplicate" | "error"
    duplicate_of: str | None = None


def preview_import(session: Session, parsed: list[ParsedQuestion]) -> list[ImportItem]:
    """Phân loại từng câu: mới, trùng (với ngân hàng hoặc với câu trước trong cùng file), lỗi."""
    items = []
    seen: dict[str, int] = {}
    seen_codes: set[str] = set()
    for i, pq in enumerate(parsed):
        h = pq.content_hash()
        if pq.code and pq.ok:
            if pq.code in seen_codes:
                pq.errors.append(f"mã câu {pq.code} lặp lại trong file")
            else:
                other = get_question(session, pq.code)
                if other is not None and other.content_hash != h:
                    pq.errors.append(f"mã câu {pq.code} đã tồn tại với nội dung khác")
            seen_codes.add(pq.code)
        if not pq.ok:
            items.append(ImportItem(i, pq, "error"))
            continue
        existing = session.scalar(select(Question).where(Question.content_hash == h))
        if existing is not None:
            items.append(ImportItem(i, pq, "duplicate", existing.code))
        elif h in seen:
            items.append(ImportItem(i, pq, "duplicate", f"câu thứ {seen[h] + 1} trong file"))
        else:
            seen[h] = i
            items.append(ImportItem(i, pq, "new"))
    return items


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
    only: set[int] | None = None,
    extra_tag: list[str] | None = None,
    default_level: Level | None = None,
) -> ImportReport:
    """Lưu các câu mới. `only`: chỉ lưu các câu có chỉ số này; `extra_tag`: gắn thêm một thẻ cho mọi câu;
    `default_level`: mức độ cho câu chưa có."""
    report = ImportReport()
    for item in preview_import(session, parsed):
        pq = item.parsed
        if only is not None and item.index not in only:
            continue
        if item.state == "error":
            report.failed.append(pq)
            continue
        if item.state == "duplicate":
            report.duplicates.append((pq.line, item.duplicate_of or ""))
            continue
        if extra_tag and extra_tag not in pq.tags:
            pq.tags.append(extra_tag)
        if pq.level is None and default_level is not None:
            pq.level = default_level
        if pq.warnings:
            report.warned.append(pq)
        if dry_run:
            report.added.append(pq.code or f"(dòng {pq.line})")
            continue
        q = Question(code=pq.code or next_code(session), status=status, source=pq.source or source)
        _apply(session, q, pq)
        session.add(q)
        session.flush()
        report.added.append(q.code)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return report


def _tag_filter(tag: str):
    prefix = "/".join(slugify(p) for p in tag.split("/") if p.strip())
    return (
        select(QuestionTag.question_id)
        .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
        .where((TaxonomyNode.path == prefix) | TaxonomyNode.path.startswith(prefix + "/"))
    )


def question_query(
    tag: str | None = None,
    level: Level | None = None,
    type: QuestionType | None = None,
    status: Status | None = None,
    text: str | None = None,
) -> Select:
    """Câu truy vấn lọc câu hỏi. `tag` là đường dẫn slug hoặc tên; khớp cả các nút con."""
    stmt = select(Question)
    if tag:
        stmt = stmt.where(Question.id.in_(_tag_filter(tag)))
    if level:
        stmt = stmt.where(Question.level == level)
    if type:
        stmt = stmt.where(Question.type == type)
    if status:
        stmt = stmt.where(Question.status == status)
    if text:
        like = f"%{text}%"
        stmt = stmt.where(
            Question.stem_latex.ilike(like) | Question.code.ilike(like) | Question.solution_latex.ilike(like)
        )
    return stmt


def find_questions(
    session: Session,
    tag: str | None = None,
    level: Level | None = None,
    type: QuestionType | None = None,
    approved_only: bool = False,
) -> list[Question]:
    stmt = question_query(tag, level, type, Status.APPROVED if approved_only else None)
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


def tag_names(node: TaxonomyNode) -> list[str]:
    """Danh sách tên từ gốc đến nút, ví dụ ["Lớp 12", "Vectơ trong không gian"]."""
    names = []
    cur: TaxonomyNode | None = node
    while cur is not None:
        names.append(cur.name)
        cur = cur.parent
    return names[::-1]
