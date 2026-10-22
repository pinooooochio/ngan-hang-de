"""Đọc câu hỏi soạn theo định dạng gói ex_test.

Mỗi câu nằm trong một khối ``\\begin{ex} ... \\end{ex}``:

    % @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH ; @id: 2H3-001
    \\begin{ex}
      Nội dung câu hỏi.
      \\choice{A}{\\True B}{C}{D}
      \\loigiai{Lời giải.}
    \\end{ex}

- ``\\choice`` (4 nhóm): trắc nghiệm, ``\\True`` đánh dấu đáp án đúng.
- ``\\choiceTF`` (4 nhóm): đúng/sai, ``\\True`` đánh dấu mệnh đề đúng.
- ``\\shortans{...}``: trả lời ngắn.
- Chỉ có ``\\loigiai``: tự luận.
- ``\\Pin`` trong một lựa chọn: giữ cố định vị trí khi đảo.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from .models import Level, QuestionType

BLOCK_RE = re.compile(r"\\begin\{ex\}(.*?)\\end\{ex\}", re.DOTALL)
META_RE = re.compile(r"^\s*%\s*(@.*)$", re.MULTILINE)
EX_ID_RE = re.compile(r"%\s*\[\s*(\d[A-Z]\d[A-Z]\d(?:-\d+)?)\s*\]")
TRUE_RE = re.compile(r"\\True(?![A-Za-z])\s*")
PIN_RE = re.compile(r"\\Pin(?![A-Za-z])\s*")
LETTER_REF_RE = re.compile(r"(chọn|đáp án)\s*(\\textbf\{)?\s*[ABCD](?![A-Za-z])", re.IGNORECASE)

MACROS = {"choice": 4, "choiceTF": 4, "shortans": 1, "loigiai": 1}

LEVEL_ALIASES = {
    "nb": Level.NB, "nhận biết": Level.NB, "nhan biet": Level.NB,
    "th": Level.TH, "thông hiểu": Level.TH, "thong hieu": Level.TH,
    "vd": Level.VD, "vận dụng": Level.VD, "van dung": Level.VD,
    "vdc": Level.VDC, "vận dụng cao": Level.VDC, "van dung cao": Level.VDC,
}

# Quy ước phổ biến của mã ID ex_test: ký tự 1 là lớp (0/1/2 = 10/11/12),
# ký tự 4 là mức độ (N/H/V/C).
EX_ID_GRADE = {"0": "Lớp 10", "1": "Lớp 11", "2": "Lớp 12"}
EX_ID_LEVEL = {"N": Level.NB, "H": Level.TH, "V": Level.VD, "C": Level.VDC}


@dataclass
class ParsedChoice:
    content: str
    is_correct: bool = False
    pinned: bool = False


@dataclass
class ParsedQuestion:
    line: int
    type: QuestionType
    stem: str
    choices: list[ParsedChoice] = field(default_factory=list)
    short_answer: str | None = None
    solution: str = ""
    code: str | None = None
    level: Level | None = None
    tags: list[list[str]] = field(default_factory=list)  # mỗi thẻ là một đường dẫn tên
    ex_id: str | None = None
    source: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def content_hash(self) -> str:
        parts = [normalize(self.stem)] + sorted(normalize(c.content) for c in self.choices)
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def slugify(name: str) -> str:
    s = name.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "khac"


def strip_comments(s: str) -> str:
    """Bỏ chú thích LaTeX (``%`` đến hết dòng), giữ nguyên ``\\%``."""
    return re.sub(r"(?<!\\)%.*", "", s)


def read_group(s: str, i: int) -> tuple[str, int]:
    """Đọc nhóm ``{...}`` bắt đầu từ vị trí i (bỏ qua khoảng trắng). Trả về (nội dung, vị trí sau ``}``)."""
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i >= n or s[i] != "{":
        raise ValueError("thiếu nhóm {...}")
    depth, start = 0, i + 1
    while i < n:
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    raise ValueError("ngoặc { } không cân")


def skip_optional(s: str, i: int) -> int:
    """Bỏ qua tham số tuỳ chọn ``[...]`` nếu có."""
    j = i
    while j < len(s) and s[j].isspace():
        j += 1
    if j < len(s) and s[j] == "[":
        end = s.find("]", j)
        if end != -1:
            return end + 1
    return i


def find_top_macros(s: str) -> list[tuple[str, int, int]]:
    """Tìm các macro trong MACROS ở mức ngoặc 0. Trả về (tên, vị trí bắt đầu, vị trí sau tên)."""
    out, depth, i, n = [], 0, 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            m = re.match(r"\\([A-Za-z]+)", s[i:])
            if m:
                name = m.group(1)
                if depth == 0 and name in MACROS:
                    out.append((name, i, i + m.end()))
                i += m.end()
            else:
                i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return out


def parse_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in META_RE.findall(text):
        for part in line.split(";"):
            part = part.strip()
            m = re.match(r"@(\w+)\s*:\s*(.*)", part)
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
    return meta


def parse_level(value: str) -> Level | None:
    return LEVEL_ALIASES.get(value.strip().lower())


def parse_block(raw: str, preamble: str, line: int) -> ParsedQuestion:
    meta = parse_meta(preamble)
    meta.update(parse_meta(raw))
    ex_id_match = EX_ID_RE.search(raw)
    body = strip_comments(raw)

    macros = find_top_macros(body)
    stem_end = macros[0][1] if macros else len(body)
    q = ParsedQuestion(line=line, type=QuestionType.ESSAY, stem=body[:stem_end].strip())

    seen: set[str] = set()
    pos_after = stem_end
    for name, start, after in macros:
        if start < pos_after:
            continue  # nằm bên trong tham số của macro trước
        if name in seen:
            q.errors.append(f"\\{name} xuất hiện nhiều lần")
            continue
        seen.add(name)
        i = skip_optional(body, after)
        groups = []
        try:
            for _ in range(MACROS[name]):
                g, i = read_group(body, i)
                groups.append(g)
        except ValueError as e:
            q.errors.append(f"\\{name}: {e}")
            pos_after = i
            continue
        pos_after = i
        if name in ("choice", "choiceTF"):
            q.type = QuestionType.MCQ if name == "choice" else QuestionType.TRUE_FALSE
            for g in groups:
                correct = bool(TRUE_RE.search(g))
                pinned = bool(PIN_RE.search(g))
                content = PIN_RE.sub("", TRUE_RE.sub("", g)).strip()
                q.choices.append(ParsedChoice(content, correct, pinned))
        elif name == "shortans":
            q.type = QuestionType.SHORT
            q.short_answer = groups[0].strip()
        elif name == "loigiai":
            q.solution = groups[0].strip()

    if "choice" in seen and "choiceTF" in seen:
        q.errors.append("không thể vừa có \\choice vừa có \\choiceTF")

    # Siêu dữ liệu
    q.code = meta.get("id") or None
    q.source = meta.get("source") or meta.get("nguon") or None
    if "level" in meta:
        q.level = parse_level(meta["level"])
        if q.level is None:
            q.warnings.append(f"mức độ không hợp lệ: {meta['level']!r}")
    if "tags" in meta:
        for path in meta["tags"].split(","):
            names = [p.strip() for p in path.split("/") if p.strip()]
            if names:
                q.tags.append(names)
    if ex_id_match:
        q.ex_id = ex_id_match.group(1)
        if q.level is None:
            q.level = EX_ID_LEVEL.get(q.ex_id[3])
        if not q.tags and q.ex_id[0] in EX_ID_GRADE:
            q.tags.append([EX_ID_GRADE[q.ex_id[0]]])

    validate(q)
    return q


def validate(q: ParsedQuestion) -> None:
    if not q.stem:
        q.errors.append("đề bài trống")
    if q.type == QuestionType.MCQ:
        if len(q.choices) != 4:
            q.errors.append(f"trắc nghiệm cần 4 lựa chọn, có {len(q.choices)}")
        n_true = sum(c.is_correct for c in q.choices)
        if n_true != 1:
            q.errors.append(f"trắc nghiệm cần đúng 1 \\True, có {n_true}")
        if q.solution and LETTER_REF_RE.search(q.solution):
            q.warnings.append("lời giải nhắc đến chữ cái đáp án, sẽ sai sau khi đảo")
    elif q.type == QuestionType.TRUE_FALSE:
        if len(q.choices) != 4:
            q.errors.append(f"đúng/sai cần 4 mệnh đề, có {len(q.choices)}")
    elif q.type == QuestionType.SHORT:
        if not q.short_answer:
            q.errors.append("trả lời ngắn chưa có đáp án")
    if any(not c.content for c in q.choices):
        q.errors.append("có lựa chọn trống")
    if not q.tags:
        q.warnings.append("chưa gắn thẻ lớp/chủ đề")
    if q.level is None:
        q.warnings.append("chưa có mức độ")


def mask_comments(s: str) -> str:
    """Thay phần chú thích bằng khoảng trắng cùng độ dài, giữ nguyên vị trí ký tự."""
    return re.sub(r"(?<!\\)%.*", lambda m: " " * len(m.group(0)), s)


def parse_text(text: str) -> list[ParsedQuestion]:
    out = []
    prev_end = 0
    # Tìm khối trên bản đã che chú thích để bỏ qua "\begin{ex}" nằm trong chú thích
    for m in BLOCK_RE.finditer(mask_comments(text)):
        # Chỉ lấy siêu dữ liệu ở các dòng chú thích ngay trước khối
        between = text[prev_end:m.start()]
        lines = between.rstrip().splitlines()
        meta_lines = []
        for ln in reversed(lines):
            if ln.strip().startswith("%"):
                meta_lines.append(ln)
            else:
                break
        preamble = "\n".join(reversed(meta_lines))
        line = text.count("\n", 0, m.start()) + 1
        out.append(parse_block(text[m.start(1):m.end(1)], preamble, line))
        prev_end = m.end()
    return out
