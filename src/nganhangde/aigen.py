"""Sinh câu hỏi bằng AI theo lớp / chủ đề / dạng bài / mức độ / loại câu.

Quy trình:
1. `build_prompt` dựng prompt: phần hệ thống cố định (định dạng ex_test, quy tắc từng loại câu,
   định nghĩa mức độ, câu mẫu) và phần yêu cầu (ô cần sinh, câu cùng chủ đề trong ngân hàng
   làm mẫu phong cách, danh sách câu đã có để tránh trùng).
2. Lấy kết quả: máy chủ gọi Claude API (khi có ANTHROPIC_API_KEY), hoặc người dùng chép prompt
   sang Claude rồi dán kết quả lại.
3. `check_output` phân tích kết quả, ép thẻ và mức độ theo yêu cầu, kiểm tra lỗi và trùng lặp.
4. `import_batch` lưu các câu hợp lệ vào ngân hàng ở trạng thái nháp, nguồn "AI #<lần sinh>",
   để người soạn đọc lại và duyệt trước khi dùng ra đề.
"""

from __future__ import annotations

import logging
import os
import threading
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import bank
from .models import (
    BuildStatus,
    GenerationBatch,
    Level,
    Question,
    QuestionTag,
    QuestionType,
    Status,
    TaxonomyNode,
)
from .parser import ParsedQuestion, parse_text, slugify

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_COUNT = 30  # số câu tối đa mỗi lần sinh, để kết quả không quá dài
LEVEL_ORDER = [Level.NB, Level.TH, Level.VD, Level.VDC]


class GenError(Exception):
    pass


# ---------- Khung chương trình ----------


def curriculum_path() -> Path:
    return Path(os.environ.get("NHD_CHUONG_TRINH", TEMPLATES / "chuong-trinh.toml"))


def load_curriculum() -> list[dict]:
    """[{ten, slug, chu_de: [{ten, slug, path, dang, ghi_chu}]}], đường dẫn slug trùng cách đặt thẻ."""
    with open(curriculum_path(), "rb") as f:
        data = tomllib.load(f)
    grades = []
    for g in data.get("lop", []):
        gslug = slugify(g["ten"])
        topics = [
            {
                "ten": t["ten"],
                "slug": slugify(t["ten"]),
                "path": f"{gslug}/{slugify(t['ten'])}",
                "dang": list(t.get("dang", [])),
                "ghi_chu": t.get("ghi_chu", ""),
            }
            for t in g.get("chu_de", [])
        ]
        grades.append({"ten": g["ten"], "slug": gslug, "chu_de": topics})
    return grades


def coverage(session: Session, grade: str) -> dict:
    """Số câu theo chủ đề × mức độ của một lớp (gồm các chủ đề trong khung chương trình và
    các chủ đề đã có trong ngân hàng). Đếm riêng câu đã duyệt và câu nháp."""
    gslug = slugify(grade)
    cur = next((g for g in load_curriculum() if g["slug"] == gslug), None)
    rows = session.execute(
        select(TaxonomyNode.path, Question.id, Question.level, Question.status)
        .join(QuestionTag, QuestionTag.node_id == TaxonomyNode.id)
        .join(Question, Question.id == QuestionTag.question_id)
        .where(TaxonomyNode.path.startswith(gslug + "/"))
    ).all()
    seen: set[tuple[str, int]] = set()
    counts: dict[str, dict] = {}
    for path, qid, level, status in rows:
        topic = "/".join(path.split("/")[:2])
        if (topic, qid) in seen:
            continue
        seen.add((topic, qid))
        cell = counts.setdefault(topic, {}).setdefault(level.value if level else "", {"approved": 0, "draft": 0})
        cell[status.value] += 1

    def empty() -> dict:
        return {lv.value: {"approved": 0, "draft": 0} for lv in LEVEL_ORDER}

    topics = []
    for t in cur["chu_de"] if cur else []:
        topics.append({"name": t["ten"], "path": t["path"], "dang": t["dang"], "in_curriculum": True,
                       "counts": {**empty(), **counts.pop(t["path"], {})}})
    names = {n.path: n.name for n in session.scalars(select(TaxonomyNode).where(TaxonomyNode.path.in_(list(counts))))}
    for path in sorted(counts):
        topics.append({"name": names.get(path, path), "path": path, "dang": [], "in_curriculum": False,
                       "counts": {**empty(), **counts[path]}})
    grade_name = cur["ten"] if cur else grade
    return {"grade": grade_name, "slug": gslug, "topics": topics}


# ---------- Prompt ----------

SYSTEM_PROMPT = r"""Bạn là giáo viên Toán giàu kinh nghiệm ra đề ở Việt Nam, soạn câu hỏi cho ngân hàng đề bám sát
Chương trình giáo dục phổ thông 2018 và cấu trúc đề thi tốt nghiệp THPT môn Toán từ năm 2025
(với bậc đại học: theo giáo trình toán cao cấp phổ biến ở các trường đại học Việt Nam).
Câu hỏi viết bằng tiếng Việt, công thức viết bằng LaTeX, theo định dạng gói ex_test như mô tả dưới đây.

# Định dạng đầu ra

Chỉ trả về các khối câu hỏi, không viết lời dẫn, không đặt trong khối mã markdown. Mỗi câu gồm một
dòng chú thích khai báo thẻ và mức độ, ngay sau đó là khối \begin{ex}...\end{ex}:

% @tags: <Lớp> / <Chủ đề> / <Dạng bài> ; @level: <NB|TH|VD|VDC>
\begin{ex}
  <đề bài>
  <phần lựa chọn tuỳ loại câu>
  \loigiai{<lời giải chi tiết>}
\end{ex}

Để một dòng trống giữa hai câu. Không ghi @id (hệ thống tự đánh mã).

Theo loại câu:
- Trắc nghiệm nhiều phương án (mcq): đúng 4 lựa chọn trong \choice{...}{...}{...}{...},
  đặt \True ở đầu lựa chọn đúng, đúng một lựa chọn có \True.
- Đúng/sai (tf): một đề dẫn chung và đúng 4 mệnh đề a), b), c), d) trong \choiceTF{...}{...}{...}{...},
  đặt \True ở đầu mỗi mệnh đề đúng (mệnh đề sai thì không đánh dấu).
- Trả lời ngắn (short): không có lựa chọn, ghi đáp số trong \shortans{...}.
- Tự luận (essay): không có lựa chọn; nhiều ý thì dùng \begin{enumerate}[label=\alph*)] ... \end{enumerate}.

Ví dụ một câu trắc nghiệm đúng định dạng:

% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=(1;2;-1)$ và $\vec v=(2;0;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice
    {$0$}
    {\True $1$}
    {$2$}
    {$3$}
  \loigiai{$\vec u\cdot\vec v = 1\cdot 2 + 2\cdot 0 + (-1)\cdot 1 = 1$.}
\end{ex}

Ví dụ một câu đúng/sai:

% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=(1;-2;2)$ và $\vec v=(2;1;0)$. Xét tính đúng sai của các mệnh đề sau.
  \choiceTF
    {\True $|\vec u|=3$}
    {\True $\vec u\perp\vec v$}
    {$\vec u-\vec v=(-1;-3;3)$}
    {\True Vectơ $2\vec u$ có độ dài bằng $6$}
  \loigiai{$|\vec u|=\sqrt{1+4+4}=3$; $\vec u\cdot\vec v=2-2+0=0$; $\vec u-\vec v=(-1;-3;2)$ nên c) sai; $|2\vec u|=2|\vec u|=6$.}
\end{ex}

Ví dụ một câu trả lời ngắn:

% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH
\begin{ex}
  Trong không gian $Oxyz$, cho $A(1;1;1)$, $B(2;3;4)$, $C(4;1;3)$. Tính $\overrightarrow{AB}\cdot\overrightarrow{AC}$.
  \shortans{9}
  \loigiai{$\overrightarrow{AB}=(1;2;3)$, $\overrightarrow{AC}=(3;0;2)$ nên $\overrightarrow{AB}\cdot\overrightarrow{AC}=3+0+6=9$.}
\end{ex}

# Mức độ nhận thức

- NB (Nhận biết): nhận ra, nhắc lại định nghĩa, công thức, tính chất; áp dụng trực tiếp một bước.
- TH (Thông hiểu): hiểu và vận dụng công thức theo quy trình quen thuộc, hai đến ba bước tính.
- VD (Vận dụng): giải quyết tình huống quen thuộc nhiều bước, kết hợp vài kiến thức; có thể là bài toán thực tế đơn giản.
- VDC (Vận dụng cao): tình huống mới hoặc tổng hợp nhiều kiến thức, cần suy luận, mô hình hoá bài toán thực tế.
Mỗi câu phải đúng mức độ được yêu cầu: đừng làm câu NB quá dài, đừng làm câu VDC chỉ là tính toán nặng.

# Quy tắc nội dung

- Mọi câu phải đúng về toán học. Trước khi viết mỗi câu, tự giải đầy đủ và kiểm tra lại đáp án;
  chọn số liệu sao cho kết quả gọn (số nguyên, phân số đơn giản, căn đơn giản).
- Đề bài rõ ràng, đủ dữ kiện, chỉ có một cách hiểu, đúng thuật ngữ và kí hiệu trong sách giáo khoa Việt Nam
  (dấu chấm phẩy ngăn tọa độ, ví dụ $A(1;2;3)$; dấu phẩy thập phân, ví dụ $1{,}5$).
- Nội dung nằm trong phạm vi chủ đề và dạng bài được yêu cầu, không dùng kiến thức của lớp trên.
- Trắc nghiệm: các phương án nhiễu lấy từ lỗi sai thường gặp của học sinh (nhầm dấu, nhầm công thức, quên điều kiện),
  cùng dạng và độ dài tương đương phương án đúng; không dùng "Cả A, B, C đều đúng", "Tất cả đều sai";
  vị trí đáp án đúng phân bố đều giữa các câu (hệ thống còn đảo lại khi ra đề).
- Đúng/sai: bốn mệnh đề độc lập, xoay quanh cùng một tình huống, độ khó tăng dần từ a) đến d);
  có cả mệnh đề đúng và mệnh đề sai, không để cả bốn cùng đúng hay cùng sai.
- Trả lời ngắn: đáp số là một số; khi viết ra có tối đa 4 kí tự kể cả dấu "-" và dấu ","
  (ví dụ 12, -3, 2,5, 0,75). Nếu kết quả không gọn thì yêu cầu làm tròn rõ ràng trong đề
  (ví dụ "làm tròn kết quả đến hàng phần mười"), và ghi đáp số đã làm tròn trong \shortans.
- Lời giải trình bày ngắn gọn các bước chính để học sinh tự đọc hiểu được. Không nhắc tới chữ cái
  của phương án ("chọn A", "đáp án B") vì thứ tự phương án sẽ bị đảo khi ra đề; nêu giá trị đúng thay vào đó.
- Không vẽ hình bằng TikZ, không chèn ảnh; nếu cần hình thì mô tả bằng lời trong đề.
- Các câu trong cùng một lần sinh phải khác nhau về tình huống, dạng hỏi và số liệu; không chép lại câu
  đã có trong ngân hàng (nếu được liệt kê).
"""

TYPE_NAMES = {
    QuestionType.MCQ: "trắc nghiệm nhiều phương án (mcq)",
    QuestionType.TRUE_FALSE: "đúng/sai (tf)",
    QuestionType.SHORT: "trả lời ngắn (short)",
    QuestionType.ESSAY: "tự luận (essay)",
}
LEVEL_NAMES = {Level.NB: "Nhận biết", Level.TH: "Thông hiểu", Level.VD: "Vận dụng", Level.VDC: "Vận dụng cao"}


def normalize_params(p: dict) -> dict:
    """Kiểm tra và chuẩn hoá yêu cầu sinh câu."""
    grade = (p.get("grade") or "").strip()
    topic = (p.get("topic") or "").strip()
    if not grade or not topic:
        raise GenError("cần chọn lớp và chủ đề")
    try:
        level = Level(p.get("level"))
        qtype = QuestionType(p.get("type", "mcq"))
    except ValueError as e:
        raise GenError(f"giá trị không hợp lệ: {e}") from e
    count = int(p.get("count") or 0)
    if not 1 <= count <= MAX_COUNT:
        raise GenError(f"số câu mỗi lần từ 1 đến {MAX_COUNT}")
    return {
        "grade": grade,
        "topic": topic,
        "dang": (p.get("dang") or "").strip() or None,
        "level": level.value,
        "type": qtype.value,
        "count": count,
        "notes": (p.get("notes") or "").strip() or None,
    }


def _short(text: str, n: int = 220) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def build_prompt(session: Session, params: dict, n_examples: int = 2, n_avoid: int = 40) -> tuple[str, str]:
    """Trả về (prompt hệ thống, prompt yêu cầu). Prompt hệ thống không đổi giữa các lần gọi."""
    p = normalize_params(params)
    level, qtype = Level(p["level"]), QuestionType(p["type"])
    topic_path = f"{slugify(p['grade'])}/{slugify(p['topic'])}"
    cur_topic = next(
        (t for g in load_curriculum() for t in g["chu_de"] if t["path"] == topic_path), None
    )

    tag_line = f"{p['grade']} / {p['topic']}" + (f" / {p['dang']}" if p["dang"] else " / <Dạng bài>")
    lines = [
        f"Hãy soạn {p['count']} câu hỏi mới:",
        f"- Lớp: {p['grade']}",
        f"- Chủ đề: {p['topic']}" + (f" ({cur_topic['ghi_chu']})" if cur_topic and cur_topic["ghi_chu"] else ""),
    ]
    if p["dang"]:
        lines.append(f"- Dạng bài: {p['dang']}")
    elif cur_topic and cur_topic["dang"]:
        lines.append("- Dạng bài: phân bổ đều trong các dạng sau, ghi dạng của từng câu ở dòng @tags: "
                     + "; ".join(cur_topic["dang"]))
    else:
        lines.append("- Dạng bài: tự chọn dạng phù hợp trong chủ đề, ghi dạng của từng câu ở dòng @tags")
    lines += [
        f"- Mức độ: {LEVEL_NAMES[level]} ({level.value})",
        f"- Loại câu: {TYPE_NAMES[qtype]}",
        f"- Dòng thẻ của mỗi câu: % @tags: {tag_line} ; @level: {level.value}",
    ]
    if p["notes"]:
        lines += ["", "Yêu cầu thêm của người soạn:", p["notes"]]

    examples = list(
        session.scalars(
            bank.question_query(tag=topic_path, type=qtype, status=Status.APPROVED)
            .order_by(func.random())
            .limit(n_examples)
        )
    )
    if examples:
        from .serialize import question_to_ex

        lines += ["", "Câu mẫu đã duyệt cùng chủ đề trong ngân hàng (tham khảo phong cách, không chép lại):", ""]
        lines += [question_to_ex(q).strip() + "\n" for q in examples]

    existing = list(
        session.scalars(
            bank.question_query(tag=topic_path).order_by(Question.updated_at.desc()).limit(n_avoid)
        )
    )
    if existing:
        lines += ["", "Ngân hàng đã có các câu sau trong chủ đề này, câu mới phải khác hẳn:"]
        lines += [f"- {_short(q.stem_latex)}" for q in existing]

    lines += ["", f"Trả về đúng {p['count']} khối câu hỏi theo định dạng đã nêu, không kèm lời dẫn."]
    return SYSTEM_PROMPT, "\n".join(lines)


def combined_prompt(system: str, user: str) -> str:
    """Một prompt duy nhất để dán vào ô chat Claude (không có chỗ nhập prompt hệ thống)."""
    return f"{system}\n# Yêu cầu\n\n{user}\n"


# ---------- Kiểm tra kết quả ----------

def strip_fences(text: str) -> str:
    """Bỏ khối ``` nếu mô hình lỡ bọc kết quả trong markdown."""
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("```"))


def short_answer_ok(ans: str) -> bool:
    t = ans.strip().replace(" ", "").replace("$", "").replace("{,}", ",")
    if len(t) > 4:
        return False
    try:
        float(t.replace(",", "."))
        return True
    except ValueError:
        return False


def check_output(session: Session, params: dict, text: str) -> list[dict]:
    """Phân tích kết quả, ép thẻ và mức độ theo yêu cầu. Trả về danh sách kết quả từng câu
    (chưa lưu). Mỗi phần tử: index, state (new | duplicate | error), stem, type, tags, errors,
    warnings, duplicate_of và `parsed` (ParsedQuestion, bỏ đi khi lưu vào lần sinh)."""
    p = normalize_params(params)
    level, qtype = Level(p["level"]), QuestionType(p["type"])
    base = [p["grade"], p["topic"]]
    parsed = parse_text(strip_fences(text))
    for pq in parsed:
        pq.code = None  # mã và nguồn do hệ thống đặt
        pq.source = None
        pq.level = level
        dang = p["dang"]
        if not dang:
            # Giữ dạng bài mô hình ghi nếu dòng thẻ đúng lớp và chủ đề
            for t in pq.tags:
                if len(t) >= 3 and [slugify(x) for x in t[:2]] == [slugify(x) for x in base]:
                    dang = t[2]
                    break
        pq.tags = [base + ([dang] if dang else [])]
        pq.warnings = [w for w in pq.warnings if "thẻ" not in w and "mức độ" not in w]
        if pq.type != qtype:
            pq.errors.append(f"loại câu là {pq.type.value}, yêu cầu {qtype.value}")
        if pq.type == QuestionType.SHORT and pq.short_answer and not short_answer_ok(pq.short_answer):
            pq.warnings.append(f"đáp số \"{pq.short_answer}\" không phải số tối đa 4 kí tự như đề THPT")
        if pq.type == QuestionType.TRUE_FALSE and len(pq.choices) == 4:
            n_true = sum(c.is_correct for c in pq.choices)
            if n_true in (0, 4):
                pq.warnings.append("cả 4 mệnh đề cùng " + ("đúng" if n_true == 4 else "sai"))
        if not pq.solution:
            pq.warnings.append("chưa có lời giải")

    out = []
    for item in bank.preview_import(session, parsed):
        pq = item.parsed
        out.append({
            "index": item.index,
            "state": item.state,
            "line": pq.line,
            "type": pq.type.value,
            "stem": pq.stem,
            "tags": pq.tags,
            "errors": pq.errors,
            "warnings": pq.warnings,
            "duplicate_of": item.duplicate_of,
            "code": None,
            "parsed": pq,
        })
    return out


def import_batch(session: Session, batch: GenerationBatch, text: str) -> None:
    """Kiểm tra kết quả `text` của lần sinh và lưu câu hợp lệ vào ngân hàng ở trạng thái nháp."""
    items = check_output(session, batch.params, text)
    batch.output = text
    for it in items:
        pq: ParsedQuestion = it.pop("parsed")
        if it["state"] != "new":
            continue
        q = Question(code=bank.next_code(session), status=Status.DRAFT, source=batch.source)
        bank._apply(session, q, pq)
        session.add(q)
        session.flush()
        it["code"] = q.code
    batch.items = items
    if not items:
        batch.status = BuildStatus.FAILED
        batch.error = "không tìm thấy khối \\begin{ex}...\\end{ex} nào trong kết quả"
    else:
        batch.status = BuildStatus.DONE
    batch.finished_at = datetime.now()
    session.commit()


def create_batch(session: Session, params: dict, mode: str, output: str | None = None) -> GenerationBatch:
    p = normalize_params(params)
    system, user = build_prompt(session, p)
    batch = GenerationBatch(
        mode=mode,
        status=BuildStatus.PENDING,
        params=p,
        system_prompt=system,
        user_prompt=user,
        model=model_name() if mode == "api" else None,
        items=[],
    )
    session.add(batch)
    session.flush()
    if mode == "manual":
        if not (output or "").strip():
            raise GenError("chưa dán kết quả")
        import_batch(session, batch, output)
    else:
        if not api_available():
            raise GenError("máy chủ chưa có ANTHROPIC_API_KEY, hãy dùng cách chép prompt")
        session.commit()
    return batch


# ---------- Gọi Claude API ----------


def model_name() -> str:
    return os.environ.get("NHD_MODEL", DEFAULT_MODEL)


def api_available() -> bool:
    if CALLER is not call_claude:  # đã thay bằng hàm giả lập (kiểm thử)
        return True
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def call_claude(system: str, user: str, model: str) -> tuple[str, dict]:
    """Gọi Claude, trả về (văn bản, thông tin token). Dùng streaming vì kết quả có thể dài;
    prompt hệ thống cố định nên được cache giữa các lần sinh."""
    import anthropic

    client = anthropic.Anthropic()
    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "high"},
            # Nếu mô hình từ chối, máy chủ Anthropic tự chạy lại trên mô hình dự phòng
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise GenError("khoá Claude API không hợp lệ") from e
    except anthropic.PermissionDeniedError as e:
        raise GenError(f"khoá Claude API không có quyền: {e.message}") from e
    except anthropic.NotFoundError as e:
        raise GenError(f"không có mô hình {model}") from e
    except anthropic.RateLimitError as e:
        raise GenError("Claude API đang giới hạn tần suất, thử lại sau ít phút") from e
    except anthropic.BadRequestError as e:
        raise GenError(f"yêu cầu không hợp lệ: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise GenError(f"Claude API lỗi {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise GenError("không kết nối được Claude API") from e

    if msg.stop_reason == "refusal":
        raise GenError("Claude từ chối yêu cầu này")
    text = "".join(b.text for b in msg.content if b.type == "text")
    u = msg.usage
    usage = {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
        "stop_reason": msg.stop_reason,
        "model": msg.model,
    }
    return text, usage


# Hàm gọi mô hình; kiểm thử thay bằng hàm giả lập
CALLER: Callable[[str, str, str], tuple[str, dict]] = call_claude


def run_batch(session: Session, batch: GenerationBatch) -> None:
    try:
        text, usage = CALLER(batch.system_prompt, batch.user_prompt, batch.model or model_name())
        batch.usage = usage
        import_batch(session, batch, text)
        if usage.get("stop_reason") == "max_tokens":
            batch.error = "kết quả bị cắt vì quá dài, câu cuối có thể thiếu; nên giảm số câu mỗi lần"
            session.commit()
    except Exception as e:  # noqa: BLE001 - mọi lỗi đều ghi vào lần sinh để người dùng thấy
        session.rollback()
        log.exception("sinh câu hỏi lỗi")
        batch.status = BuildStatus.FAILED
        batch.error = str(e) if isinstance(e, GenError) else f"lỗi: {e}"
        batch.finished_at = datetime.now()
        session.commit()


def claim_next(session: Session) -> GenerationBatch | None:
    stmt = (
        select(GenerationBatch)
        .where(GenerationBatch.status == BuildStatus.PENDING, GenerationBatch.mode == "api")
        .order_by(GenerationBatch.id)
        .limit(1)
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    batch = session.scalar(stmt)
    if batch is None:
        session.rollback()
        return None
    batch.status = BuildStatus.RUNNING
    session.commit()
    return batch


def run_pending(session: Session) -> int:
    n = 0
    while (batch := claim_next(session)) is not None:
        run_batch(session, batch)
        n += 1
    return n


def reset_stale(session: Session) -> None:
    """Lần sinh đang chạy dở khi máy chủ tắt thì đưa về hàng đợi."""
    for b in session.scalars(select(GenerationBatch).where(GenerationBatch.status == BuildStatus.RUNNING)):
        b.status = BuildStatus.PENDING
    session.commit()


def start_worker(session_factory, stop: threading.Event, poll: float = 2.0) -> threading.Thread:
    def loop() -> None:
        with session_factory() as s:
            reset_stale(s)
        while not stop.is_set():
            try:
                with session_factory() as s:
                    run_pending(s)
            except Exception:  # noqa: BLE001
                log.exception("worker sinh câu lỗi")
            stop.wait(poll)

    t = threading.Thread(target=loop, name="nhd-aigen", daemon=True)
    t.start()
    return t
