"""Ngân hàng câu hỏi: lưu câu đã phân tích, cây thẻ, tìm kiếm."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .models import Choice, Level, Question, QuestionTag, QuestionType, Status, TaxonomyNode, VariantGroup
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
    q.params = pq.params
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
    group = q.variant_group
    session.delete(q)
    session.flush()
    fix_groups(session, [group])
    session.commit()


def bulk_update(
    session: Session,
    codes: list[str],
    add_tag: list[str] | None = None,
    level: Level | None = None,
    status: Status | None = None,
    set_tag: list[str] | None = None,
) -> int:
    """Gắn thêm thẻ, đổi hẳn thẻ (`set_tag` thay mọi thẻ cũ), đặt mức độ hoặc trạng thái cho nhiều câu."""
    node = get_or_create_path(session, add_tag) if add_tag else None
    only = get_or_create_path(session, set_tag) if set_tag else None
    qs = list(session.scalars(select(Question).where(Question.code.in_(codes))))
    old = {n.path for q in qs for n in q.tags} if only is not None else set()
    for q in qs:
        if only is not None:
            q.tags = [only]
        if node is not None and node not in q.tags:
            q.tags.append(node)
        if level is not None:
            q.level = level
        if status is not None:
            q.status = status
    session.flush()
    for path in old:
        prune_tags(session, path)
    session.commit()
    return len(qs)


def bulk_delete(session: Session, codes: list[str]) -> tuple[int, list[str]]:
    """Xoá nhiều câu; câu đã nằm trong đề thì giữ lại. Trả về (số câu đã xoá, mã câu giữ lại)."""
    from .models import ExamItem

    qs = list(session.scalars(select(Question).where(Question.code.in_(codes))))
    used = set(session.scalars(select(ExamItem.question_id).where(ExamItem.question_id.in_([q.id for q in qs]))))
    old = {n.path for q in qs for n in q.tags}
    kept = [q.code for q in qs if q.id in used]
    groups = {q.variant_group for q in qs if q.id not in used}
    for q in qs:
        if q.id not in used:
            q.tags = []
            session.delete(q)
    session.flush()
    fix_groups(session, groups)
    for path in old:
        prune_tags(session, path)
    session.commit()
    return len(qs) - len(kept), kept


def tag_path(tag: str) -> str:
    """Đường dẫn slug từ tên ("Lớp 12 / Vectơ") hoặc slug ("lop-12/vecto")."""
    return "/".join(slugify(p) for p in tag.split("/") if p.strip())


def _subtree(path: str):
    return (TaxonomyNode.path == path) | TaxonomyNode.path.startswith(path + "/")


def prune_tags(session: Session, path: str) -> int:
    """Xoá các nút không còn câu nào trong nhánh, từ `path` đi lên gốc (kể cả nút con của nó)."""
    n = 0
    parts = path.split("/")
    candidates = list(session.scalars(select(TaxonomyNode).where(_subtree(path))))
    candidates += list(session.scalars(
        select(TaxonomyNode).where(TaxonomyNode.path.in_(["/".join(parts[:i]) for i in range(1, len(parts))]))
    ))
    for node in sorted(candidates, key=lambda x: -x.path.count("/")):
        used = session.scalar(
            select(QuestionTag.question_id)
            .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
            .where(_subtree(node.path))
            .limit(1)
        )
        has_children = session.scalar(select(TaxonomyNode.id).where(TaxonomyNode.parent_id == node.id).limit(1))
        if used is None and has_children is None:
            session.delete(node)
            session.flush()
            n += 1
    return n


def move_tag(session: Session, source: str, target: list[str]) -> int:
    """Chuyển mọi câu có thẻ thuộc nhánh `source` sang thẻ `target` (thay các thẻ trong nhánh đó,
    giữ thẻ khác), rồi xoá các nút đã trống. Trả về số câu được chuyển. Nếu đích nằm trong nhánh
    nguồn (ví dụ chương -> một chủ đề của chương) thì chỉ chuyển câu gắn đúng nút nguồn."""
    src = tag_path(source)
    dst_path = tag_path(" / ".join(target))
    if dst_path == src:
        raise BankError("thẻ đích trùng thẻ nguồn")
    inside = dst_path.startswith(src + "/")
    nodes = list(session.scalars(select(TaxonomyNode).where(TaxonomyNode.path == src if inside else _subtree(src))))
    ids = {n.id for n in nodes}
    qs = list(session.scalars(
        select(Question).where(Question.id.in_(select(QuestionTag.question_id).where(QuestionTag.node_id.in_(ids))))
    )) if ids else []
    if not qs:
        return 0
    dst = get_or_create_path(session, target)
    for q in qs:
        rest = [n for n in q.tags if n.id not in ids]
        q.tags = rest + ([dst] if dst not in rest else [])
    session.flush()
    prune_tags(session, src)
    session.commit()
    return len(qs)


def count_in_tag(session: Session, tag: str) -> int:
    return session.scalar(
        select(func.count(func.distinct(QuestionTag.question_id)))
        .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
        .where(_subtree(tag_path(tag)))
    ) or 0


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
    prefix = tag_path(tag)
    return (
        select(QuestionTag.question_id)
        .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
        .where((TaxonomyNode.path == prefix) | TaxonomyNode.path.startswith(prefix + "/"))
    )


CODE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def code_list(text: str | None) -> list[str]:
    """Ô tìm có dạng "Q00001, Q00005; 12V-004": trả về danh sách mã (rỗng nếu không phải dạng này)."""
    if not text or not re.search(r"[,;\n]", text):
        return []
    parts = [p.strip() for p in re.split(r"[,;\n]+", text) if p.strip()]
    if parts and all(CODE_TOKEN.match(p) for p in parts):
        return list(dict.fromkeys(parts))
    return []


def question_query(
    tag: str | None = None,
    level: Level | None = None,
    type: QuestionType | None = None,
    status: Status | None = None,
    text: str | None = None,
    source: str | None = None,
    group: str | None = None,
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
    if group:
        stmt = stmt.where(Question.variant_group == group)
    if source:
        # nhiều nguồn ngăn bởi "|" (ví dụ các lần sinh của một đợt: "AI #3|AI #4")
        sources = [s for s in source.split("|") if s]
        stmt = stmt.where(Question.source.in_(sources) if len(sources) > 1 else Question.source == source)
    codes = code_list(text)
    if codes:
        # nhiều mã câu cách nhau bằng dấu phẩy / chấm phẩy / xuống dòng: tìm đúng các câu đó
        stmt = stmt.where(func.upper(Question.code).in_([c.upper() for c in codes]))
    elif text:
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


def tag_tree(session: Session, order: dict[str, int] | None = None) -> list[tuple[TaxonomyNode, int, int]]:
    """Trả về (nút, độ sâu, số câu thuộc nút và các nút con), duyệt theo thứ tự cây. Nút có trong
    `order` (đường dẫn -> thứ tự, ví dụ thứ tự khung chương trình) đứng trước, còn lại theo tên."""
    order = order or {}
    nodes = list(session.scalars(select(TaxonomyNode).order_by(TaxonomyNode.name)))
    nodes.sort(key=lambda n: order.get(n.path, len(order)))
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


def variant_members(session: Session, q: Question) -> list[Question]:
    """Các câu cùng nhóm biến thể với `q` (gồm cả `q`); câu chưa có nhóm thì chỉ có chính nó."""
    if not q.variant_group:
        return [q]
    return list(session.scalars(select(Question).where(Question.variant_group == q.variant_group).order_by(Question.id)))


def tag_names(node: TaxonomyNode) -> list[str]:
    """Danh sách tên từ gốc đến nút, ví dụ ["Lớp 12", "Vectơ trong không gian"]."""
    names = []
    cur: TaxonomyNode | None = node
    while cur is not None:
        names.append(cur.name)
        cur = cur.parent
    return names[::-1]


# ---------- Nhóm biến thể ----------


class GroupError(Exception):
    pass


def get_group(session: Session, code: str | None) -> VariantGroup | None:
    if not code:
        return None
    return session.scalar(select(VariantGroup).where(VariantGroup.code == code))


def new_group(session: Session, origin: Question, label: str | None = None) -> VariantGroup:
    """Tạo nhóm mới lấy `origin` làm câu gốc (thẻ, mức độ, loại câu của nhóm theo câu gốc)."""
    g = VariantGroup(code="", origin_code=origin.code, label=(label or "").strip() or None,
                     tag_id=origin.tags[0].id if origin.tags else None, level=origin.level, type=origin.type)
    session.add(g)
    session.flush()
    g.code = f"N-{g.id:06d}"
    return g


def ensure_group(session: Session, q: Question, label: str | None = None) -> VariantGroup:
    """Nhóm của câu `q`; câu chưa có nhóm thì tạo nhóm mới với `q` là câu gốc."""
    g = get_group(session, q.variant_group)
    if g is None:
        g = new_group(session, q, label)
        q.variant_group = g.code
    elif label and not g.label:
        g.label = label.strip()
    return g


def group_size(session: Session, code: str) -> int:
    return session.scalar(select(func.count()).select_from(Question).where(Question.variant_group == code)) or 0


def _fix_origin(session: Session, g: VariantGroup) -> None:
    """Câu gốc rời nhóm: câu cũ nhất còn lại thành câu gốc; nhóm hết câu thì xoá."""
    members = list(session.scalars(select(Question).where(Question.variant_group == g.code).order_by(Question.id)))
    if not members:
        session.delete(g)
    elif g.origin_code not in {m.code for m in members}:
        g.origin_code = members[0].code


def set_group(session: Session, q: Question, code: str | None) -> VariantGroup | None:
    """Chuyển câu `q` sang nhóm `code` (None = tách khỏi nhóm, câu đứng riêng)."""
    target = None
    if code:
        target = get_group(session, code)
        if target is None:
            raise GroupError(f"không có nhóm {code}")
        if target.type is not None and target.type != q.type:
            raise GroupError(f"nhóm {code} gồm câu khác loại với câu {q.code}")
    old = get_group(session, q.variant_group)
    q.variant_group = target.code if target else None
    session.flush()
    if old is not None and old is not target:
        _fix_origin(session, old)
    return target


def merge_group(session: Session, questions: list[Question], label: str | None = None) -> VariantGroup:
    """Gộp các câu thành một nhóm: dùng nhóm lớn nhất mà một trong các câu đang thuộc về, hoặc tạo nhóm
    mới với câu cũ nhất là câu gốc. Các câu phải cùng loại."""
    if len(questions) < 2:
        raise GroupError("cần chọn ít nhất 2 câu để gộp")
    if len({q.type for q in questions}) > 1:
        raise GroupError("các câu trong một nhóm phải cùng loại câu")
    existing = [g for g in {get_group(session, q.variant_group) for q in questions} if g is not None]
    target = max(existing, key=lambda g: (group_size(session, g.code), -g.id)) if existing else new_group(session, min(questions, key=lambda q: q.id))
    if label and label.strip():
        target.label = label.strip()
    for q in questions:
        set_group(session, q, target.code)
    return target


def migrate_groups(session: Session) -> int:
    """Chuyển nhóm kiểu cũ (giá trị là mã câu gốc) sang bảng nhóm biến thể. Trả về số nhóm đã chuyển."""
    known = set(session.scalars(select(VariantGroup.code)))
    old = [v for v in session.scalars(select(Question.variant_group).where(Question.variant_group.is_not(None)).distinct())
           if v not in known]
    for value in old:
        members = list(session.scalars(select(Question).where(Question.variant_group == value).order_by(Question.id)))
        origin = next((m for m in members if m.code == value), members[0])
        g = new_group(session, origin)
        for m in members:
            m.variant_group = g.code
    if old:
        session.commit()
    return len(old)


def fix_groups(session: Session, codes) -> None:
    """Sau khi xoá câu: cập nhật câu gốc của các nhóm liên quan, xoá nhóm không còn câu nào."""
    for code in codes:
        g = get_group(session, code)
        if g is not None:
            _fix_origin(session, g)


def _merge_split(paths: list[list[str]]) -> list[list[str]]:
    """Ghép lại các thẻ bị tách nhầm ở dấu phẩy trong tên ("... / Độc lập tuyến tính" + "cơ sở và số chiều / ...")."""
    from .parser import _norm, known_names

    names = known_names()
    paths = [list(p) for p in paths]
    changed = True
    while changed and len(paths) > 1:
        changed = False
        for a in paths:
            for b in paths:
                if a is b:
                    continue
                joined = f"{a[-1]}, {b[0]}"
                key = _norm(joined)
                lone = len(paths) == 2 and b[0][:1].islower()
                if lone or any(n.startswith(key) for n in names):
                    merged = a[:-1] + [joined] + b[1:]
                    paths = [p for p in paths if p is not a and p is not b] + [merged]
                    changed = True
                    break
            if changed:
                break
    return paths


def repair_split_tags(session: Session) -> int:
    """Sửa thẻ của các câu import trước đây bị tách đôi ở dấu phẩy trong tên chủ đề. Trả về số câu đã sửa."""
    multi = select(QuestionTag.question_id).group_by(QuestionTag.question_id).having(func.count() > 1)
    fixed = 0
    old_paths: set[str] = set()
    for q in session.scalars(select(Question).where(Question.id.in_(multi))):
        before = [tag_names(t) for t in q.tags]
        after = _merge_split(before)
        if after == before:
            continue
        old_paths.update(t.path for t in q.tags)
        q.tags = list({id(n): n for n in (get_or_create_path(session, p) for p in after)}.values())
        fixed += 1
    if fixed:
        session.flush()
        for path in old_paths:
            prune_tags(session, path)
        session.commit()
    return fixed
