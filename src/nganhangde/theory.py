"""Lý thuyết theo chủ đề: soạn cả bài bằng LaTeX, tách thành khối (định nghĩa, định lý, công thức,
phương pháp, ví dụ, lưu ý, đoạn văn), gắn với chủ đề và dạng bài trong khung chương trình.

Định dạng soạn / import:

    % @chude: Lớp 11 / Góc trong không gian      (chỉ cần khi import; trang soạn đã biết chủ đề)
    \\begin{dinhnghia}[Hai mặt phẳng vuông góc]
      ...
    \\end{dinhnghia}
    % @dang: Góc nhị diện                          (các khối sau thuộc dạng này; để trống = kiến thức chung)
    \\begin{phuongphap} ... \\end{phuongphap}
    \\begin{vidu}[Tiêu đề] ... \\begin{loigiai} ... \\end{loigiai} \\end{vidu}
    \\cauhoi{Q01173}                               (ví dụ lấy từ câu hỏi có sẵn trong ngân hàng)

Khi import file soạn ở nơi khác, các môi trường hay gặp (definition, theorem, dn, dl, vd, note, ...)
được đổi sang loại khối tương ứng; `\\section{...}`, `\\subsection{...}` trùng tên dạng bài thì đổi dạng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Question, Status, TheoryBlock, TheoryLog
from .parser import slugify, unescape_html

# loại khối -> tên hiển thị (thứ tự này là thứ tự trong menu chèn khối)
KINDS = {
    "dinhnghia": "Định nghĩa",
    "dinhly": "Định lý / Tính chất",
    "congthuc": "Công thức",
    "phuongphap": "Phương pháp giải",
    "vidu": "Ví dụ",
    "luuy": "Lưu ý",
    "doan": "Đoạn văn",  # chữ nằm ngoài các môi trường trên
}
ENV_KINDS = [k for k in KINDS if k != "doan"]

# tên môi trường hay gặp trong tài liệu soạn ở nơi khác -> loại khối
ALIASES = {
    **{k: k for k in ENV_KINDS},
    "definition": "dinhnghia", "defn": "dinhnghia", "dn": "dinhnghia", "khainiem": "dinhnghia",
    "theorem": "dinhly", "thm": "dinhly", "dl": "dinhly", "tinhchat": "dinhly", "tc": "dinhly",
    "proposition": "dinhly", "prop": "dinhly", "lemma": "dinhly", "bode": "dinhly", "corollary": "dinhly",
    "hequa": "dinhly", "hq": "dinhly", "menhde": "dinhly",
    "formula": "congthuc", "ct": "congthuc",
    "method": "phuongphap", "pp": "phuongphap", "cachgiai": "phuongphap",
    "example": "vidu", "vd": "vidu", "exam": "vidu",
    "note": "luuy", "remark": "luuy", "rem": "luuy", "chuy": "luuy", "nhanxet": "luuy", "nx": "luuy",
    "canhbao": "luuy", "warning": "luuy",
}

TOKEN = re.compile(
    r"^[ \t]*%[ \t]*@(?P<dir>chude|chu-de|chu_de|dang)[ \t]*:(?P<val>[^\n]*)$"
    r"|\\begin\{(?P<env>[A-Za-z]+)\*?\}"
    r"|\\cauhoi\{(?P<code>[^}\n]*)\}"
    r"|\\(?:sub)*section\*?\{(?P<sec>[^}\n]*)\}",
    re.M,
)
DANG_PREFIX = re.compile(r"^\s*(d[ạa]ng|loại)\s*\d*\s*[.:)\-–—]?\s*", re.I)
NOISE = re.compile(r"\\(maketitle|tableofcontents|newpage|clearpage|pagebreak)\b\s*")


class TheoryError(Exception):
    pass


@dataclass
class ParsedBlock:
    kind: str
    content: str
    title: str | None = None
    dang: str | None = None
    ref: str | None = None
    line: int = 0

    def key(self) -> tuple:
        return (self.kind, self.title or "", self.content, self.dang or "", self.ref or "")


@dataclass
class Section:
    topic: dict | None  # chủ đề trong khung chương trình (aigen.load_curriculum)
    line: int = 0
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass
class ParsedTheory:
    sections: list[Section] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[tuple[int, str]] = field(default_factory=list)


# ---------- Khung chương trình ----------


def topics() -> list[dict]:
    from .aigen import load_curriculum

    out = []
    for g in load_curriculum():
        for t in g["chu_de"]:
            if not t.get("label"):
                out.append({**t, "grade": g["ten"], "grade_slug": g["slug"]})
    return out


def find_topic(spec: str) -> dict | None:
    """Chủ đề theo đường dẫn tên ("Lớp 11 / Góc trong không gian") hoặc slug ("lop-11/goc-trong-khong-gian").
    Chủ đề đại học có tầng chương; có thể bỏ tầng chương nếu tên chủ đề không trùng trong học phần."""
    parts = [slugify(p) for p in spec.split("/") if p.strip()]
    if not parts:
        return None
    path = "/".join(parts)
    all_topics = topics()
    for t in all_topics:
        if t["path"] == path:
            return t
    if len(parts) >= 2:
        hits = [t for t in all_topics if t["grade_slug"] == parts[0] and t["slug"] == parts[-1]]
        if len(hits) == 1:
            return hits[0]
    return None


def match_dang(topic: dict, name: str) -> str | None:
    """Tên dạng bài trong khung khớp với `name` (bỏ tiền tố "Dạng 1:"), hoặc None."""
    want = slugify(DANG_PREFIX.sub("", name))
    for d in topic["dang"]:
        if slugify(d) == want or slugify(d) == slugify(name):
            return d
    return None


# ---------- Đọc bài lý thuyết ----------


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _find_end(text: str, env: str, start: int) -> tuple[int, int] | None:
    """Vị trí `\\end{env}` khớp với `\\begin{env}` ngay trước `start` (đếm lồng nhau cùng tên)."""
    pat = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\*?\}")
    depth = 1
    for m in pat.finditer(text, start):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.start(), m.end()
    return None


def _read_title(text: str, pos: int) -> tuple[str | None, int]:
    """Tham số tuỳ chọn [tiêu đề] ngay sau \\begin{...} (cho phép ngoặc vuông lồng trong $...$)."""
    if pos >= len(text) or text[pos] != "[":
        return None, pos
    depth = 0
    for j in range(pos, len(text)):
        ch = text[j]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[pos + 1:j].strip() or None, j + 1
        elif ch == "\n" and text[pos:j].count("\n") > 2:
            break
    return None, pos


def _clean_text(s: str) -> str:
    """Chữ nằm ngoài các khối: bỏ dòng chú thích, lệnh trình bày trang, dòng trống thừa."""
    lines = [ln for ln in s.split("\n") if not ln.lstrip().startswith("%")]
    s = NOISE.sub("", "\n".join(lines))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _body(text: str) -> str:
    """Bỏ phần đầu file (\\documentclass ... \\begin{document}) và \\end{document} nếu có."""
    m = re.search(r"\\begin\{document\}", text)
    if m:
        text = text[m.end():]
        e = re.search(r"\\end\{document\}", text)
        if e:
            text = text[:e.start()]
    return text


def parse(text: str, default_topic: dict | None = None) -> ParsedTheory:
    """Tách bài lý thuyết thành các phần theo chủ đề, mỗi phần gồm các khối theo thứ tự."""
    text = _body(unescape_html(text).replace("\r\n", "\n"))
    out = ParsedTheory()
    cur = Section(default_topic) if default_topic else None
    dang: str | None = None
    pos = 0  # đầu đoạn văn chưa xử lý
    search = 0  # tìm token tiếp theo từ đây (nhảy qua môi trường lạ nằm trong đoạn văn)

    def add(block: ParsedBlock) -> None:
        if cur is None:
            out.errors.append((block.line, "chưa có dòng % @chude: ... cho biết lý thuyết thuộc chủ đề nào"))
            return
        if not any(s is cur for s in out.sections):
            out.sections.append(cur)
        cur.blocks.append(block)

    def flush(upto: int) -> None:
        raw = text[pos:upto]
        chunk = _clean_text(raw)
        if chunk:
            first = pos
            for ln in raw.split("\n"):
                if ln.strip() and not ln.lstrip().startswith("%"):
                    break
                first += len(ln) + 1
            add(ParsedBlock("doan", chunk, dang=dang, line=_line_of(text, first)))

    while True:
        m = TOKEN.search(text, search)
        if m is None:
            flush(len(text))
            break
        line = _line_of(text, m.start())
        if m.group("env") and ALIASES.get(m.group("env").lower()) is None:
            # môi trường khác (enumerate, tikzpicture, ...): thuộc đoạn văn, tìm tiếp sau khi nó đóng
            end = _find_end(text, m.group("env"), m.end())
            search = end[1] if end else m.end()
            continue
        if m.group("sec") is not None:
            d = match_dang(cur.topic, m.group("sec").strip()) if cur else None
            if d is None:  # tiêu đề không trùng dạng bài: giữ nguyên trong đoạn văn
                search = m.end()
                continue
            flush(m.start())
            dang = d
            pos = search = m.end()
            continue
        flush(m.start())
        pos = search = m.end()
        if m.group("dir"):
            val = m.group("val").strip()
            if m.group("dir") == "dang":
                if not val:
                    dang = None
                elif cur is None:
                    out.errors.append((line, "dòng % @dang đứng trước % @chude"))
                elif (d := match_dang(cur.topic, val)) is None:
                    out.errors.append((line, f"chủ đề {cur.topic['ten']} không có dạng \"{val}\" trong khung chương trình"
                                             f" (các dạng: {'; '.join(cur.topic['dang']) or 'chưa có'})"))
                else:
                    dang = d
            else:
                t = find_topic(val)
                if t is None:
                    out.errors.append((line, f"không có chủ đề \"{val}\" trong khung chương trình"))
                    cur = None
                else:
                    cur = next((s for s in out.sections if s.topic["path"] == t["path"]), None) or Section(t, line)
                dang = None
            continue
        if m.group("code") is not None:
            add(ParsedBlock("vidu", "", ref=m.group("code").strip(), dang=dang, line=line))
            continue
        env = m.group("env")
        title, body_start = _read_title(text, m.end())
        end = _find_end(text, env, body_start)
        if end is None:
            out.errors.append((line, f"thiếu \\end{{{env}}}"))
            pos = search = len(text)
            break
        content = _dedent(text[body_start:end[0]].strip("\n").rstrip())
        add(ParsedBlock(ALIASES[env.lower()], content, title=title, dang=dang, line=line))
        pos = search = end[1]
    return out


def _dedent(s: str) -> str:
    lines = s.split("\n")
    widths = [len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip()]
    w = min(widths) if widths else 0
    return "\n".join(ln[w:] if len(ln) >= w else ln.lstrip(" ") for ln in lines).strip()


# ---------- Viết lại thành văn bản soạn ----------


def block_source(b) -> str:
    """Một khối (ParsedBlock hoặc TheoryBlock) ở định dạng soạn."""
    ref = getattr(b, "ref", None) if isinstance(b, ParsedBlock) else b.ref_code
    if ref:
        return f"\\cauhoi{{{ref}}}"
    if b.kind == "doan":
        return b.content
    title = f"[{b.title}]" if b.title else ""
    return f"\\begin{{{b.kind}}}{title}\n{b.content}\n\\end{{{b.kind}}}"


def to_source(blocks, topic: dict | None = None) -> str:
    """Cả bài ở định dạng soạn; dòng % @dang mỗi khi đổi dạng bài, % @chude ở đầu nếu cần."""
    parts: list[str] = []
    if topic is not None:
        parts.append(f"% @chude: {' / '.join(topic['names'])}")
    dang: str | None = None
    for b in blocks:
        if (b.dang or None) != dang:
            dang = b.dang or None
            parts.append(f"% @dang: {dang or ''}".rstrip())
        parts.append(block_source(b))
    return "\n\n".join(parts) + ("\n" if parts else "")


# ---------- Lưu vào cơ sở dữ liệu ----------


def topic_blocks(session: Session, path: str, approved_only: bool = False) -> list[TheoryBlock]:
    q = select(TheoryBlock).where(TheoryBlock.topic_path == path)
    if approved_only:
        q = q.where(TheoryBlock.status == Status.APPROVED)
    return list(session.scalars(q.order_by(TheoryBlock.position, TheoryBlock.id)))


def _key(b: TheoryBlock) -> tuple:
    return (b.kind, b.title or "", b.content, b.dang or "", b.ref_code or "")


def _next_codes(session: Session):
    n = session.scalar(select(func.max(TheoryBlock.id))) or 0
    while True:
        n += 1
        code = f"L-{n:06d}"
        if session.scalar(select(TheoryBlock.id).where(TheoryBlock.code == code)) is None:
            yield code


def _log(session: Session, path: str, username: str | None, action: str, detail: str | None,
         before: str | None) -> None:
    session.add(TheoryLog(topic_path=path, username=username, action=action, detail=detail, before=before))


def save_topic(session: Session, topic: dict, blocks: list[ParsedBlock], *, approve: bool = False,
               username: str | None = None, source: str | None = "tay", append: bool = False,
               action: str = "sua") -> dict:
    """Ghi các khối của một chủ đề. Thay cả bài (mặc định) hoặc thêm vào cuối (`append`, khi import).
    Khối không đổi giữ mã và trạng thái; khối mới hoặc đã sửa vào nháp, trừ khi `approve`
    (khi đó mọi khối của chủ đề đều được duyệt). Trả về số khối thêm / giữ / xoá."""
    path = topic["path"]
    old = topic_blocks(session, path)
    before = to_source(old) if old else None
    codes = _next_codes(session)
    added = kept = 0
    rows: list[TheoryBlock] = []
    if append:
        rows = list(old)
        pool: dict[tuple, list[TheoryBlock]] = {}
    else:
        pool = {}
        for b in old:
            pool.setdefault(_key(b), []).append(b)
    for pb in blocks:
        reuse = pool.get(pb.key())
        if reuse:
            row = reuse.pop(0)
            kept += 1
        else:
            row = TheoryBlock(code=next(codes), topic_path=path, kind=pb.kind, title=pb.title, content=pb.content,
                              dang=pb.dang, ref_code=pb.ref, status=Status.DRAFT, source=source,
                              updated_by=username)
            session.add(row)
            added += 1
        rows.append(row)
    removed = [b for lst in pool.values() for b in lst]
    for b in removed:
        session.delete(b)
    if append:
        # thêm vào sau: khối mới đứng cuối nhóm cùng dạng bài (kiến thức chung trước, các dạng theo khung)
        order = {None: -1, **{d: i for i, d in enumerate(topic["dang"])}}
        rows.sort(key=lambda r: order.get(r.dang or None, len(order)))
    for i, row in enumerate(rows):
        row.position = i
        if approve:
            row.status = Status.APPROVED
    session.flush()
    changed = added or removed or [b.code for b in old] != [r.code for r in rows if r in old]
    if changed:
        _log(session, path, username, action, f"+{added} khối, -{len(removed)} khối", before)
    elif approve and any(b.status != Status.APPROVED for b in old):
        _log(session, path, username, "duyet", None, None)
    session.commit()
    return {"added": added, "kept": kept, "removed": len(removed)}


def approve_topic(session: Session, path: str, username: str | None = None) -> int:
    n = 0
    for b in topic_blocks(session, path):
        if b.status != Status.APPROVED:
            b.status = Status.APPROVED
            n += 1
    if n:
        _log(session, path, username, "duyet", f"{n} khối", None)
    session.commit()
    return n


def counts(session: Session) -> dict[str, dict[str, int]]:
    """Đường dẫn chủ đề -> {approved, draft} số khối."""
    out: dict[str, dict[str, int]] = {}
    for path, status, n in session.execute(
            select(TheoryBlock.topic_path, TheoryBlock.status, func.count()).group_by(
                TheoryBlock.topic_path, TheoryBlock.status)):
        out.setdefault(path, {"approved": 0, "draft": 0})[status.value] = n
    return out


def missing_refs(session: Session, blocks) -> set[str]:
    """Mã câu hỏi được dẫn làm ví dụ nhưng không có trong ngân hàng."""
    refs = {b.ref for b in blocks if getattr(b, "ref", None)}
    if not refs:
        return set()
    have = set(session.scalars(select(Question.code).where(Question.code.in_(refs))))
    return refs - have


def question_links(session: Session, codes) -> dict[str, dict]:
    """Câu hỏi -> chủ đề (và dạng bài) có lý thuyết đã duyệt, theo thẻ của câu; để "Xem lý thuyết" khi xem lại
    bài làm. Câu không có chủ đề nào có lý thuyết thì không có trong kết quả."""
    from .models import QuestionTag, TaxonomyNode

    codes = set(codes)
    if not codes:
        return {}
    approved: dict[str, set] = {}
    for path, dang in session.execute(select(TheoryBlock.topic_path, TheoryBlock.dang)
                                      .where(TheoryBlock.status == Status.APPROVED).distinct()):
        approved.setdefault(path, set()).add(dang)
    if not approved:
        return {}
    by_path = {t["path"]: t for t in topics() if t["path"] in approved}
    out: dict[str, dict] = {}
    rows = session.execute(select(Question.code, TaxonomyNode.path)
                           .join(QuestionTag, QuestionTag.question_id == Question.id)
                           .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id)
                           .where(Question.code.in_(codes)))
    for code, tag in rows:
        for path, t in by_path.items():
            if tag == path or tag.startswith(path + "/"):
                rest = tag[len(path) + 1:].split("/")[0] if tag != path else ""
                dang = next((d for d in t["dang"] if slugify(d) == rest and d in approved[path]), None)
                if code not in out or (dang and not out[code]["dang"]):
                    out[code] = {"path": path, "ten": t["ten"], "dang": dang}
    return out
