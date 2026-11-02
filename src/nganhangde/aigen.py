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
import random
import threading
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import bank, figures, kiemtra
from . import params as params_mod
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
from .parser import ParsedQuestion, parse_text, slugify, split_blocks

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_COUNT = 30  # số câu tối đa mỗi lần sinh, để kết quả không quá dài
MAX_TOTAL = 300  # tổng số câu tối đa của một đợt sinh nhiều ô bằng API (mỗi ô một lần gọi)
MAX_SOURCES = 100  # số câu gốc tối đa của một đợt sinh biến thể hàng loạt
MAX_PER = 10  # số biến thể tối đa cho mỗi câu gốc
PACK = 4  # số câu gốc gộp trong một lần gọi (một prompt)
MAX_PROMPT = 60  # tổng số câu tối đa của một prompt gộp (cách chép prompt); hơn thì chia phần
LEVEL_ORDER = [Level.NB, Level.TH, Level.VD, Level.VDC]


class GenError(Exception):
    pass


# ---------- Khung chương trình ----------


def curriculum_path() -> Path:
    return Path(os.environ.get("NHD_CHUONG_TRINH", TEMPLATES / "chuong-trinh.toml"))


def _topic(t: dict, names: list[str], chapter: dict | None) -> dict:
    return {
        "ten": t["ten"],
        "slug": slugify(t["ten"]),
        "names": names,
        "path": "/".join(slugify(n) for n in names),
        "chuong": chapter["ten"] if chapter else "",
        "dang": list(t.get("dang", [])),
        "ghi_chu": t.get("ghi_chu", ""),
        "noi_dung": t.get("noi_dung", "").strip(),
        "goi_y_trac_nghiem": list(chapter.get("goi_y_trac_nghiem", [])) if chapter else [],
        "goi_y_tu_luan": list(chapter.get("goi_y_tu_luan", [])) if chapter else [],
    }


def load_curriculum() -> list[dict]:
    """[{ten, slug, bac, ghi_chu, chuong: [{ten, path}], chu_de: [...]}]. Chủ đề xếp phẳng theo thứ tự
    trong file; chủ đề của học phần đại học có thêm tầng chương trong `names` và `path` (đường dẫn
    slug trùng cách đặt thẻ)."""
    with open(curriculum_path(), "rb") as f:
        data = tomllib.load(f)
    grades = []
    for g in data.get("lop", []):
        topics = [_topic(t, [g["ten"], t["ten"]], None) for t in g.get("chu_de", [])]
        chapters = []
        for ch in g.get("chuong", []):
            chapters.append({"ten": ch["ten"], "path": f"{slugify(g['ten'])}/{slugify(ch['ten'])}"})
            topics += [_topic(t, [g["ten"], ch["ten"], t["ten"]], ch) for t in ch.get("chu_de", [])]
        grades.append({
            "ten": g["ten"],
            "slug": slugify(g["ten"]),
            "bac": g.get("bac", "THPT"),
            "ghi_chu": g.get("ghi_chu", ""),
            "chuong": chapters,
            "chu_de": topics,
        })
    return grades


def curriculum_order() -> dict[str, int]:
    """Đường dẫn slug -> thứ tự trong khung chương trình (lớp, chương, chủ đề, dạng)."""
    paths: list[str] = []
    for g in load_curriculum():
        paths.append(g["slug"])
        paths += [c["path"] for c in g["chuong"]]
        for t in g["chu_de"]:
            paths.append(t["path"])
            paths += [f"{t['path']}/{slugify(d)}" for d in t["dang"]]
    return {p: i for i, p in enumerate(dict.fromkeys(paths))}


def load_tag_moves() -> list[dict]:
    """Quy tắc chuyển thẻ từ khung cũ ([[doi_the]] tu, den), quy tắc cụ thể hơn đứng trước."""
    with open(curriculum_path(), "rb") as f:
        data = tomllib.load(f)
    rules = [{"from": r["tu"], "to": r["den"]} for r in data.get("doi_the", [])]
    return sorted(rules, key=lambda r: -len(r["from"].split("/")))


def find_topic(grade: str, topic: str) -> dict | None:
    gslug, tslug = slugify(grade), slugify(topic)
    for g in load_curriculum():
        if g["slug"] == gslug:
            return next((t for t in g["chu_de"] if t["slug"] == tslug), None)
    return None


def topic_names(grade: str, topic: str) -> list[str]:
    """Đường dẫn tên thẻ của chủ đề, có tầng chương nếu khung chương trình có."""
    t = find_topic(grade, topic)
    return list(t["names"]) if t else [grade, topic]


def coverage(session: Session, grade: str) -> dict:
    """Số câu theo chủ đề × mức độ của một lớp (gồm các chủ đề trong khung chương trình và
    các chủ đề đã có trong ngân hàng). Đếm riêng câu đã duyệt và câu nháp. Câu chỉ gắn tới
    tầng chương (hoặc tầng lớp) được đếm vào một dòng riêng của chương đó."""
    gslug = slugify(grade)
    cur = next((g for g in load_curriculum() if g["slug"] == gslug), None)
    topic_paths = [t["path"] for t in cur["chu_de"]] if cur else []
    chapters = {c["path"]: c["ten"] for c in cur["chuong"]} if cur else {}
    rows = session.execute(
        select(TaxonomyNode.path, Question.id, Question.level, Question.status)
        .join(QuestionTag, QuestionTag.node_id == TaxonomyNode.id)
        .join(Question, Question.id == QuestionTag.question_id)
        .where((TaxonomyNode.path == gslug) | TaxonomyNode.path.startswith(gslug + "/"))
    ).all()

    def topic_of(path: str) -> str:
        for tp in topic_paths:
            if path == tp or path.startswith(tp + "/"):
                return tp
        parts = path.split("/")
        if len(parts) >= 2 and "/".join(parts[:2]) in chapters:
            return "/".join(parts[:3])
        return "/".join(parts[:2])

    seen: set[tuple[str, int]] = set()
    counts: dict[str, dict] = {}
    for path, qid, level, status in rows:
        topic = topic_of(path)
        if (topic, qid) in seen:
            continue
        seen.add((topic, qid))
        cell = counts.setdefault(topic, {}).setdefault(level.value if level else "", {"approved": 0, "draft": 0})
        cell[status.value] += 1

    def empty() -> dict:
        return {lv.value: {"approved": 0, "draft": 0} for lv in LEVEL_ORDER}

    topics = []
    for t in cur["chu_de"] if cur else []:
        topics.append({"name": t["ten"], "path": t["path"], "chuong": t["chuong"], "dang": t["dang"],
                       "in_curriculum": True, "counts": {**empty(), **counts.pop(t["path"], {})}})
    names = {n.path: n.name for n in session.scalars(select(TaxonomyNode).where(TaxonomyNode.path.in_(list(counts))))}
    for path in sorted(counts):
        chapter = next((name for cp, name in chapters.items() if path == cp or path.startswith(cp + "/")), "")
        row = {"name": names.get(path, path), "path": path, "chuong": chapter, "dang": [],
               "in_curriculum": False, "counts": {**empty(), **counts[path]}}
        if path in chapters:
            row["label"] = "Câu chưa gắn chủ đề"
        elif path == gslug:
            row["label"] = "Câu chưa gắn chương" if chapters else "Câu chưa gắn chủ đề"
        topics.append(row)
    # Dòng ngoài khung đứng cuối chương của nó (hoặc cuối bảng)
    chapter_order = {c["ten"]: i for i, c in enumerate(cur["chuong"])} if cur else {}
    topics = [t for _, t in sorted(
        enumerate(topics),
        key=lambda x: (chapter_order.get(x[1]["chuong"], len(chapter_order)), not x[1]["in_curriculum"], x[0]),
    )]
    grade_name = cur["ten"] if cur else grade
    return {"grade": grade_name, "slug": gslug, "topics": topics}


# ---------- Prompt ----------

SYSTEM_PROMPT = r"""Bạn là giáo viên Toán giàu kinh nghiệm ra đề ở Việt Nam, soạn câu hỏi cho ngân hàng đề bám sát
Chương trình giáo dục phổ thông 2018 và cấu trúc đề thi tốt nghiệp THPT môn Toán từ năm 2025
(với bậc đại học: theo đề cương các học phần toán của Đại học Bách khoa Hà Nội như Giải tích 1, 2, 3,
Đại số, Xác suất thống kê; khi yêu cầu có kèm kiến thức trọng tâm thì bám sát phần đó).
Câu hỏi viết bằng tiếng Việt, công thức viết bằng LaTeX, theo định dạng gói ex_test như mô tả dưới đây.

# Định dạng đầu ra

Chỉ trả về các khối câu hỏi, không viết lời dẫn, không đặt trong khối mã markdown. Mỗi câu gồm một
dòng chú thích khai báo thẻ và mức độ, ngay sau đó là khối \begin{ex}...\end{ex}:

% @tags: <Lớp> / <Chủ đề> / <Dạng bài> ; @level: <NB|TH|VD|VDC>

(Dòng thẻ chính xác cho từng lần sinh được ghi trong phần yêu cầu; với học phần đại học có thêm tầng chương.)
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
- Tự kiểm đáp án: với câu trắc nghiệm và trả lời ngắn có đáp án là một số hoặc một bộ số (tọa độ),
  thêm dòng `% @kiemtra: <biểu thức> = <đáp án>` ngay dưới dòng @tags. Biểu thức tính đáp án trực tiếp
  từ số liệu của đề (thể hiện cách tính, không chép lại đáp án), máy sẽ tính lại để đối chiếu. Cú pháp:
  số thập phân dùng dấu chấm; phép + - * / ^; hàm sqrt, cbrt, ln, log10, log(a, x) (lôgarit cơ số a của x),
  exp, sin, cos, tan (theo radian), abs, comb(n, k), perm(n, k), factorial(n); hằng pi, e; bộ số viết
  (a, b, c). Không dùng dấu chấm phẩy hay chữ cái khác trong dòng này. Đáp án không phải số (biểu thức
  chứa biến, khoảng, mệnh đề) thì bỏ dòng này. Ví dụ: % @kiemtra: 1*2 + 2*0 + (-1)*1 = 1
- Lời giải trình bày ngắn gọn các bước chính để học sinh tự đọc hiểu được. Không nhắc tới chữ cái
  của phương án ("chọn A", "đáp án B") vì thứ tự phương án sẽ bị đảo khi ra đề; nêu giá trị đúng thay vào đó.
- Không chèn ảnh (\includegraphics). Hình vẽ nếu có thì vẽ bằng TikZ theo mục "Hình vẽ" dưới đây.
- Các câu trong cùng một lần sinh phải khác nhau về tình huống, dạng hỏi và số liệu; không chép lại câu
  đã có trong ngân hàng (nếu được liệt kê).

# Hình vẽ

Phần yêu cầu sẽ nói câu có cần hình hay không. Khi vẽ, mỗi hình là một khối
\begin{tikzpicture}...\end{tikzpicture} đặt trong đề bài (hoặc trong lời giải nếu chỉ lời giải cần hình),
thường đặt giữa \begin{center}...\end{center}. Hình được biên dịch bằng XeLaTeX, đã nạp sẵn: tikz
(thư viện calc, angles, quotes, arrows.meta, patterns, intersections, positioning, decorations.markings),
pgfplots (compat=1.18), tkz-euclide, tkz-tab. Không dùng \usepackage, \usetikzlibrary hay gói nào khác,
không dùng \input, không định nghĩa lệnh mới bằng \def hay \newcommand.

- Đồ thị hàm số: dùng pgfplots, trục qua gốc toạ độ (axis lines=middle), ghi nhãn $x$, $y$, $O$,
  đánh dấu các điểm đặc biệt (cực trị, giao trục) có toạ độ nguyên; hình rộng khoảng 6 đến 7 cm.
  Đồ thị phải khớp chính xác với hàm số trong lời giải (cùng cực trị, giao điểm, tiệm cận).
- Bảng biến thiên, bảng xét dấu: dùng tkz-tab (\tkzTabInit, \tkzTabLine, \tkzTabVar) trong tikzpicture.
- Hình phẳng: dùng tkz-euclide hoặc tikz với toạ độ tính sẵn, ghi tên điểm, kí hiệu góc vuông, đoạn bằng nhau.
- Hình không gian (chóp, lăng trụ, hộp): vẽ theo phép chiếu song song như sách giáo khoa, cạnh khuất nét đứt
  (dashed), cạnh thấy nét liền, đáy là hình bình hành nhìn nghiêng; khai báo toạ độ các đỉnh bằng \coordinate
  rồi nối cạnh, ghi tên đỉnh không đè lên nét vẽ.
- Hệ trục Oxyz: trục Oz thẳng đứng, Oy nằm ngang, Ox chéo xuống trái; có mũi tên và nhãn trục.
- Hình chỉ thể hiện đúng dữ kiện trong đề, không ghi thêm đáp số lên hình.
- Mã hình gọn: không quá khoảng 40 dòng, không dùng vòng lặp phức tạp.

Câu đúng/sai có hình: đề dẫn đưa hình (đồ thị, bảng biến thiên hoặc hình không gian) kèm dữ kiện chung,
bốn mệnh đề a) đến d) là các nhận định đọc hoặc suy ra từ hình (khoảng đồng biến, nghịch biến, cực trị,
giá trị lớn nhất, số nghiệm của phương trình; quan hệ vuông góc, song song, góc, khoảng cách, thể tích),
độ khó tăng dần, mệnh đề d) cần kết hợp hình với tính toán.
"""

TYPE_NAMES = {
    QuestionType.MCQ: "trắc nghiệm nhiều phương án (mcq)",
    QuestionType.TRUE_FALSE: "đúng/sai (tf)",
    QuestionType.SHORT: "trả lời ngắn (short)",
    QuestionType.ESSAY: "tự luận (essay)",
}
LEVEL_NAMES = {Level.NB: "Nhận biết", Level.TH: "Thông hiểu", Level.VD: "Vận dụng", Level.VDC: "Vận dụng cao"}


PARAM_TYPES = (QuestionType.MCQ, QuestionType.SHORT)

PARAM_RULES = r"""# Câu tham số

Mỗi câu là một MẪU câu tham số: số liệu thay bằng tham số, mỗi lần ra đề hệ thống bốc một bộ số mới
rồi tự tính lại đáp án, phương án nhiễu và lời giải theo công thức trong mẫu.

- Ngay dưới dòng @tags (trước \begin{ex}) khai báo tham số:
  % @thamso: a = 1..6; b = -5..5; k = 2..10 buoc 2; r = {1/2, 3, -1}
  % @dieukien: b != 0; a != b
  % @tinh: d = 2*a + b; S = sqrt(a^2 + b^2)
  @thamso là miền giá trị (đoạn số nguyên, có thể có bước, hoặc tập liệt kê). @dieukien (tuỳ chọn) là các
  điều kiện cách nhau bằng dấu chấm phẩy, dùng != < <= > >= =, va, hoac. @tinh (tuỳ chọn) là các đại lượng
  tính từ tham số, theo thứ tự, dùng được ở các @tinh sau và trong đề.
- Tên tham số là chữ cái Latinh, có thể kèm chữ số (a, b, m1, x0); không trùng tên hàm.
- Trong đề, các phương án, \shortans và lời giải, mọi số phụ thuộc tham số viết dạng {{biểu thức}}, ví dụ
  {{a}}, {{2*a - b}}, {{d}}. Biểu thức dùng + - * / ^, ngoặc tròn và các hàm sqrt, abs, min, max, gcd, lcm,
  floor, ceil, round, comb, perm, factorial, cbrt, ln, log, exp, sin, cos, tan. Máy tính chính xác bằng phân số
  (1/3 giữ nguyên là phân số và in thành \dfrac{1}{3}; sqrt giữ chính xác khi khai được).
- Cách in cho gọn, viết sau dấu hai chấm: {{b:+}} luôn kèm dấu ("+ 3" hoặc "- 3"), dùng cho số hạng đứng sau:
  $x^2 {{b:c+}}x {{c:+}}$; {{a:c}} hệ số đứng đầu (1 thành rỗng, -1 thành "-"): ${{a:c}}x^2$; {{b:c+}} hệ số
  kèm dấu ở giữa biểu thức; {{b:()}} số âm đặt trong ngoặc: $2\cdot {{b:()}}$; {{I:.1}} làm tròn 1 chữ số
  thập phân (dấu phẩy thập phân).
- Số mũ, chỉ số nhiều chữ số thì bọc ngoặc và để cách: $x^{ {{n}} }$, $\sqrt{ {{d}} }$.
- Phương án nhiễu cũng viết bằng công thức theo tham số, lấy từ lỗi sai thường gặp. Dùng @dieukien để
  loại các bộ số làm phương án trùng nhau hay trùng đáp án (máy cũng loại các bộ số đó khi bốc).
- Trả lời ngắn: đáp số trong \shortans{ {{biểu thức}} } phải là số tối đa 4 kí tự với mọi bộ số; giới hạn
  miền hoặc yêu cầu làm tròn ({{I:.1}}) để thoả.
- Chọn miền và điều kiện để có ít nhất 10 bộ số hợp lệ khác nhau, mọi bộ số đều cho đề có nghĩa, số liệu và
  kết quả gọn. Phần chữ không phụ thuộc số (cách hỏi, kết luận) phải đúng với MỌI bộ số thoả điều kiện.
- Không thêm dòng @kiemtra (đáp án đã được tính từ công thức). Không vẽ hình.

Ví dụ một mẫu câu tham số đúng định dạng:

% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
% @thamso: a = 1..6; b = -5..5; c = -4..4
% @dieukien: c != 0; b != 0
% @tinh: d = 2*a + c
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=({{a}};{{b}};{{c}})$ và $\vec v=(2;0;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice
    {\True ${{d}}$}
    {${{2*a - c}}$}
    {${{d + 1}}$}
    {${{-d - 2}}$}
  \loigiai{$\vec u\cdot\vec v = {{a}}\cdot 2 + {{b:()}}\cdot 0 + {{c:()}}\cdot 1 = {{d}}$.}
\end{ex}"""


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
    param = bool(p.get("param"))
    if param and qtype not in PARAM_TYPES and not p.get("variants_of"):
        raise GenError("câu tham số chỉ áp dụng cho trắc nghiệm và trả lời ngắn")
    return {
        "grade": grade,
        "topic": topic,
        "dang": (p.get("dang") or "").strip() or None,
        "level": level.value,
        "type": qtype.value,
        "count": count,
        "notes": (p.get("notes") or "").strip() or None,
        "figure": bool(p.get("figure")) and not param,
        # soạn mẫu câu tham số (sinh mới), hoặc chuyển các câu gốc `variants_of` thành câu tham số
        "param": param,
        "variant_of": (p.get("variant_of") or "").strip() or None,
        # sinh biến thể cho nhiều câu gốc trong một lần gọi: mỗi câu gốc `per` biến thể
        "variants_of": [c.strip() for c in p.get("variants_of") or [] if c and c.strip()] or None,
        "per": int(p.get("per") or 0) or None,
    }


def _short(text: str, n: int = 220) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def build_prompt(session: Session, params: dict, n_examples: int = 2, n_avoid: int = 40,
                 rules: bool = True) -> tuple[str, str]:
    """Trả về (prompt hệ thống, prompt yêu cầu). Prompt hệ thống không đổi giữa các lần gọi.
    `rules=False`: bỏ phần quy tắc câu tham số (prompt gộp ghi phần đó một lần ở đầu)."""
    p = normalize_params(params)
    if p["variants_of"] and p["param"]:
        return SYSTEM_PROMPT, convert_prompt(session, p)
    if p["variants_of"]:
        return SYSTEM_PROMPT, multi_variant_prompt(session, p)
    if p["variant_of"]:
        return SYSTEM_PROMPT, variant_prompt(session, p)
    level, qtype = Level(p["level"]), QuestionType(p["type"])
    cur_topic = find_topic(p["grade"], p["topic"])
    names = topic_names(p["grade"], p["topic"])
    topic_path = "/".join(slugify(n) for n in names)

    tag_line = " / ".join(names) + (f" / {p['dang']}" if p["dang"] else " / <Dạng bài>")
    lines = [PARAM_RULES, "", "# Yêu cầu cụ thể", ""] if p["param"] and rules else []
    lines += [
        f"Hãy soạn {p['count']} " + ("mẫu câu tham số mới (theo mục \"Câu tham số\"):" if p["param"]
                                      else "câu hỏi mới:"),
        f"- Lớp / học phần: {p['grade']}",
    ]
    if cur_topic and cur_topic["chuong"]:
        lines.append(f"- Chương: {cur_topic['chuong']}")
    lines.append(f"- Chủ đề: {p['topic']}" + (f" ({cur_topic['ghi_chu']})" if cur_topic and cur_topic["ghi_chu"] else ""))
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
    if cur_topic and cur_topic["noi_dung"]:
        lines += ["", "Kiến thức trọng tâm của chủ đề (theo đề cương):", cur_topic["noi_dung"]]
    hints = cur_topic and (cur_topic["goi_y_tu_luan"] if qtype == QuestionType.ESSAY else cur_topic["goi_y_trac_nghiem"])
    if hints:
        kind = "tự luận" if qtype == QuestionType.ESSAY else "trắc nghiệm"
        lines += ["", f"Định hướng câu hỏi {kind} của chương (chỉ dùng các ý thuộc chủ đề trên):"]
        lines += [f"- {h}" for h in hints]
    if p["param"]:
        lines.append("- Câu tham số: mỗi câu có dòng @thamso, các số trong đề viết bằng {{...}}, không vẽ hình")
    elif p["figure"]:
        lines.append("- Hình vẽ: MỖI câu phải có hình vẽ TikZ trong đề bài (đồ thị, bảng biến thiên, hình phẳng"
                     " hoặc hình không gian tuỳ chủ đề), câu hỏi khai thác thông tin từ hình, theo mục \"Hình vẽ\"")
    else:
        lines.append("- Hình vẽ: chỉ vẽ khi đề bài thật sự cần hình mới hiểu được; còn lại không vẽ")
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


def convert_prompt(session: Session, p: dict) -> str:
    """Prompt chuyển các câu gốc thành câu tham số; mỗi câu kết quả ghi mã câu gốc ở dòng @bienthe."""
    from .serialize import question_to_ex

    codes = p["variants_of"]
    lines = [
        PARAM_RULES, "", "# Yêu cầu cụ thể", "",
        f"Hãy chuyển {len(codes)} câu gốc dưới đây thành câu tham số, mỗi câu gốc đúng một mẫu "
        f"(tổng cộng {len(codes)} câu).",
        "- Giữ nguyên loại câu, mức độ, cách hỏi, số bước giải và kiểu phương án nhiễu của câu gốc; số liệu của "
        "câu gốc phải là một bộ số hợp lệ của mẫu.",
        "- Phương án nhiễu viết thành công thức mô tả đúng lỗi sai mà nhiễu của câu gốc thể hiện.",
        "- Lời giải viết lại theo tham số, các bước tính dùng {{...}}.",
        "- Mỗi mẫu bắt đầu bằng dòng `% @bienthe: <mã câu gốc>`, rồi dòng @tags (chép đúng dòng thẻ ghi ở câu gốc "
        "đó), các dòng @thamso, @dieukien, @tinh, rồi khối \\begin{ex}...\\end{ex}.",
        "- Câu nào không thể tham số hoá hợp lý (đáp án không phải số hay biểu thức tính được từ số liệu, hoặc "
        "kết luận đổi theo số liệu) thì bỏ qua, không trả về câu đó.",
    ]
    for i, code in enumerate(codes, 1):
        q = bank.get_question(session, code)
        if q is None:
            raise GenError(f"không có câu {code}")
        tags = " ; ".join(" / ".join(bank.tag_names(t)) for t in q.tags)
        level = (q.level or Level.TH).value
        lines += ["", f"## Câu gốc {i}: % @bienthe: {q.code}",
                  f"Dòng thẻ: % @tags: {tags} ; @level: {level}", "", question_to_ex(q).strip()]
    lines += ["", "Trả về các mẫu câu tham số theo thứ tự các câu gốc, không kèm lời dẫn."]
    return "\n".join(lines)


# ---------- Biến thể: cùng dạng, khác số liệu ----------


def variant_params(session: Session, code: str, count: int = 5) -> dict:
    """Tham số lần sinh biến thể cho câu `code`: lớp, chủ đề, dạng lấy từ thẻ của câu (để lịch sử
    sinh xếp đúng chỗ), mức độ và loại câu giữ nguyên."""
    q = bank.get_question(session, code)
    if q is None:
        raise GenError(f"không có câu {code}")
    names = bank.tag_names(q.tags[0]) if q.tags else []
    if not names:
        raise GenError(f"câu {code} chưa gắn thẻ lớp/chủ đề")
    grade, topic, dang = names[0], names[-1], None
    g = next((g for g in load_curriculum() if g["slug"] == slugify(names[0])), None)
    for t in g["chu_de"] if g else []:
        n = len(t["names"])
        if [slugify(x) for x in names[:n]] == [slugify(x) for x in t["names"]]:
            topic, dang = t["ten"], names[n] if len(names) > n else None
            break
    else:
        if len(names) > 1:
            topic = names[1]
            dang = names[2] if len(names) > 2 else None
    return normalize_params({
        "grade": grade, "topic": topic, "dang": dang, "level": (q.level or Level.TH).value, "type": q.type.value,
        "count": count, "variant_of": q.code, "figure": bool(figures.find_figures(q.stem_latex)),
    })


def variant_prompt(session: Session, p: dict) -> str:
    from .serialize import question_to_ex

    q = bank.get_question(session, p["variant_of"])
    if q is None:
        raise GenError(f"không có câu {p['variant_of']}")
    tags = " ; ".join(" / ".join(bank.tag_names(t)) for t in q.tags)
    lines = [
        f"Hãy soạn {p['count']} biến thể của câu gốc dưới đây.",
        "- Giữ nguyên loại câu, mức độ, cách hỏi, số bước giải và kiểu phương án nhiễu (nhiễu vẫn lấy từ "
        "cùng các lỗi sai như câu gốc); chỉ thay số liệu, và nếu cần thì tên điểm, tên hàm.",
        "- Chọn số liệu để kết quả vẫn gọn; đáp án của mỗi biến thể phải khác đáp án câu gốc và khác nhau.",
        "- Lời giải viết lại đầy đủ theo số liệu mới, tự giải lại từ đầu chứ không sửa số trong lời giải cũ.",
        "- Câu gốc có hình thì vẽ lại hình đúng theo số liệu mới.",
        f"- Dòng thẻ của mỗi biến thể: % @tags: {tags} ; @level: {p['level']}",
        *_label_rule(session, q),
        "",
        "Câu gốc:",
        "",
        question_to_ex(q).strip(),
    ]
    others = [o for o in bank.variant_members(session, q) if o.id != q.id]
    if others:
        lines += ["", "Nhóm đã có các biến thể sau, biến thể mới phải dùng số liệu khác:"]
        lines += [f"- {_short(o.stem_latex)}" for o in others[:40]]
    lines += ["", f"Trả về đúng {p['count']} khối câu hỏi theo định dạng đã nêu, không kèm lời dẫn."]
    return "\n".join(lines)


VARIANT_RULES = [
    "- Giữ nguyên loại câu, mức độ, cách hỏi, số bước giải và kiểu phương án nhiễu (nhiễu vẫn lấy từ "
    "cùng các lỗi sai như câu gốc); chỉ thay số liệu, và nếu cần thì tên điểm, tên hàm.",
    "- Chọn số liệu để kết quả vẫn gọn; đáp án của mỗi biến thể phải khác đáp án câu gốc và khác nhau.",
    "- Lời giải viết lại đầy đủ theo số liệu mới, tự giải lại từ đầu chứ không sửa số trong lời giải cũ.",
    "- Câu gốc có hình thì vẽ lại hình đúng theo số liệu mới.",
]


def _label_rule(session: Session, q: Question) -> list[str]:
    """Nhóm chưa có mô tả dạng bài thì xin mô tả ở biến thể đầu tiên."""
    g = bank.get_group(session, q.variant_group)
    if g is not None and g.label:
        return []
    return ["- Ở biến thể đầu tiên, thêm một dòng `% @dang-bien-the: <mô tả ngắn dạng bài, dưới 12 chữ>` "
            "(ví dụ: Độ dài vectơ từ toạ độ) ngay trên dòng @tags."]


def multi_variant_prompt(session: Session, p: dict) -> str:
    """Prompt sinh biến thể cho nhiều câu gốc cùng lúc; mỗi biến thể ghi mã câu gốc ở dòng @bienthe."""
    from .serialize import question_to_ex

    per, codes = p["per"], p["variants_of"]
    lines = [
        f"Hãy soạn biến thể cho {len(codes)} câu gốc dưới đây, mỗi câu gốc đúng {per} biến thể "
        f"(tổng cộng {per * len(codes)} câu).",
        *VARIANT_RULES,
        "- Mỗi biến thể bắt đầu bằng dòng `% @bienthe: <mã câu gốc>`, rồi tới dòng @tags (chép đúng dòng thẻ "
        "ghi ở câu gốc đó), dòng @kiemtra nếu có, rồi khối \\begin{ex}...\\end{ex}.",
        "- Câu gốc nào ghi \"cần mô tả dạng\" thì ở biến thể đầu tiên của câu đó thêm dòng "
        "`% @dang-bien-the: <mô tả ngắn dạng bài, dưới 12 chữ>` ngay dưới dòng @bienthe.",
    ]
    for i, code in enumerate(codes, 1):
        q = bank.get_question(session, code)
        if q is None:
            raise GenError(f"không có câu {code}")
        tags = " ; ".join(" / ".join(bank.tag_names(t)) for t in q.tags)
        level = (q.level or Level.TH).value
        lines += ["", f"## Câu gốc {i}: % @bienthe: {q.code}"
                  + (" (cần mô tả dạng)" if _label_rule(session, q) else ""),
                  f"Dòng thẻ: % @tags: {tags} ; @level: {level}", "", question_to_ex(q).strip()]
        others = [o for o in bank.variant_members(session, q) if o.id != q.id]
        if others:
            lines += ["", "Nhóm của câu này đã có các biến thể sau, biến thể mới phải dùng số liệu khác:"]
            lines += [f"- {_short(o.stem_latex)}" for o in others[:20]]
    lines += ["", f"Trả về đúng {per * len(codes)} khối câu hỏi ({per} biến thể cho mỗi câu gốc, theo thứ tự "
              "các câu gốc), không kèm lời dẫn."]
    return "\n".join(lines)


SOURCE_RE = re.compile(r"^\s*%\s*@bienthe\s*:\s*(\S+)", re.MULTILINE)
LABEL_RE = re.compile(r"^\s*%\s*@dang-bien-the\s*:\s*(.+?)\s*$", re.MULTILINE)
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_of(stem: str) -> tuple[str, ...]:
    """Dãy số xuất hiện trong đề, để nhận ra biến thể trùng số liệu với câu khác cùng nhóm."""
    return tuple(NUM_RE.findall(stem))


def plan_variants(session: Session, questions: list[Question], computational_only: bool = False) -> dict:
    """Chọn câu gốc cho đợt sinh biến thể hàng loạt từ các câu được chọn (theo chủ đề, theo đề, hoặc chọn
    tay): chỉ câu đã duyệt, đã gắn thẻ; mỗi nhóm biến thể một câu (ưu tiên câu gốc của nhóm); tối đa
    MAX_SOURCES câu. Trả về {"sources": [...], "skipped": [{code, reason}]}."""
    sources: list[Question] = []
    skipped: list[dict] = []
    taken: dict[str, str] = {}  # nhóm -> câu đã lấy
    seen: set[int] = set()
    # câu gốc của nhóm đứng trước để được chọn làm đại diện
    origins = {g.code: g.origin_code for g in session.scalars(select(bank.VariantGroup))}
    ordered = sorted((q for q in questions if q is not None),
                     key=lambda q: (origins.get(q.variant_group) != q.code, q.id))
    for q in ordered:
        if q.id in seen:
            continue
        seen.add(q.id)
        if q.status != Status.APPROVED:
            skipped.append({"code": q.code, "reason": "chưa duyệt"})
        elif q.params:
            skipped.append({"code": q.code, "reason": "câu tham số (đã tự đổi số mỗi lần ra đề)"})
        elif not q.tags:
            skipped.append({"code": q.code, "reason": "chưa gắn thẻ lớp / chủ đề"})
        elif computational_only and q.type in (QuestionType.ESSAY, QuestionType.TRUE_FALSE):
            skipped.append({"code": q.code, "reason": "không phải câu tính toán (tự luận, đúng/sai)"})
        elif q.variant_group and q.variant_group in taken:
            skipped.append({"code": q.code, "reason": f"cùng nhóm {q.variant_group} với câu {taken[q.variant_group]}"})
        elif len(sources) >= MAX_SOURCES:
            skipped.append({"code": q.code, "reason": f"vượt {MAX_SOURCES} câu gốc mỗi đợt"})
        else:
            sources.append(q)
            if q.variant_group:
                taken[q.variant_group] = q.code
    return {"sources": sources, "skipped": skipped}


def variant_packs(session: Session, codes: list[str], per: int, param: bool = False) -> list[dict]:
    """Chia các câu gốc thành các lần gọi: mỗi lần tối đa PACK câu cùng loại, cùng thẻ chính, và tổng số
    biến thể không quá MAX_COUNT. Trả về tham số từng lần sinh."""
    if not 1 <= per <= MAX_PER:
        raise GenError(f"số biến thể mỗi câu gốc từ 1 đến {MAX_PER}")
    if not codes:
        raise GenError("chưa chọn câu gốc nào")
    if len(codes) > MAX_SOURCES:
        raise GenError(f"mỗi đợt tối đa {MAX_SOURCES} câu gốc")
    qs = []
    for code in dict.fromkeys(codes):
        q = bank.get_question(session, code)
        if q is None:
            raise GenError(f"không có câu {code}")
        if q.status != Status.APPROVED:
            raise GenError(f"câu {code} chưa duyệt, không dùng làm câu gốc")
        if param and (q.params or q.type not in PARAM_TYPES):
            raise GenError(f"câu {code} không chuyển thành câu tham số được (đã là câu tham số, hoặc không phải "
                           "trắc nghiệm / trả lời ngắn)")
        qs.append(q)
    if param:
        per = 1
    size = max(1, min(PACK, MAX_COUNT // per))
    qs.sort(key=lambda q: (q.type.value, q.tags[0].path if q.tags else "", q.id))
    packs: list[list[Question]] = []
    for q in qs:
        last = packs[-1] if packs else None
        if last and len(last) < size and last[0].type == q.type and (
                (last[0].tags[0].path if last[0].tags else "") == (q.tags[0].path if q.tags else "")):
            last.append(q)
        else:
            packs.append([q])
    out = []
    for pack in packs:
        base = variant_params(session, pack[0].code, per * len(pack))
        out.append({**base, "variant_of": None, "variants_of": [q.code for q in pack], "per": per, "param": param,
                    "figure": not param and any(figures.find_figures(q.stem_latex) for q in pack)})
    return out


def create_variant_group(session: Session, codes: list[str], per: int, mode: str, output: str | None = None,
                         user_id: int | None = None, username: str | None = None,
                         group_id: str | None = None, notes: str | None = None,
                         param: bool = False) -> list[GenerationBatch]:
    """Đợt sinh biến thể hàng loạt (hoặc chuyển thành câu tham số khi `param`): mỗi gói câu gốc một lần
    sinh, chung mã đợt. Dán tay thì `codes` là đúng một gói (một prompt)."""
    packs = variant_packs(session, codes, per, param)
    if mode == "manual" and len(packs) != 1:
        raise GenError("dán tay: mỗi lần lưu đúng một phần (một prompt)")
    group = group_id if group_id and re.fullmatch(r"[0-9a-f]{10}", group_id) else uuid.uuid4().hex[:10]
    batches = [create_batch(session, {**p, "notes": notes}, mode, output, user_id=user_id, username=username,
                            group_id=group) for p in packs]
    session.commit()
    return batches


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


def question_text(pq: ParsedQuestion) -> str:
    return "\n".join([pq.stem, *(c.content for c in pq.choices), pq.solution or ""])


def check_output(session: Session, params: dict, text: str) -> list[dict]:
    """Phân tích kết quả, ép thẻ và mức độ theo yêu cầu. Trả về danh sách kết quả từng câu
    (chưa lưu). Mỗi phần tử: index, state (new | duplicate | error), stem, type, tags, errors,
    warnings, duplicate_of và `parsed` (ParsedQuestion, bỏ đi khi lưu vào lần sinh)."""
    p = normalize_params(params)
    level, qtype = Level(p["level"]), QuestionType(p["type"])
    base = topic_names(p["grade"], p["topic"])
    text = strip_fences(text)
    parsed = parse_text(text)
    chunks = split_blocks(text)
    lines = [kiemtra.find_line(chunk) for chunk in chunks]
    # biến thể: câu gốc của từng câu (một câu gốc, hoặc nhiều câu gốc nhận ra qua dòng @bienthe)
    originals: dict[str, Question] = {}
    for code in p["variants_of"] or ([p["variant_of"]] if p["variant_of"] else []):
        q = bank.get_question(session, code)
        if q is None:
            raise GenError(f"không có câu {code}")
        originals[q.code] = q
    source_of: dict[int, Question | None] = {}
    labels: dict[int, str] = {}
    for i, pq in enumerate(parsed):
        chunk = chunks[i] if i < len(chunks) else ""
        m = SOURCE_RE.search(chunk)
        if p["variants_of"]:
            source_of[id(pq)] = originals.get(m.group(1)) if m else None
            if source_of[id(pq)] is None:
                pq.errors.append("thiếu dòng % @bienthe hoặc mã câu gốc không nằm trong yêu cầu"
                                 + (f" ({m.group(1)})" if m else ""))
        elif originals:
            source_of[id(pq)] = next(iter(originals.values()))
        lm = LABEL_RE.search(chunk)
        if lm:
            labels[id(pq)] = lm.group(1)[:200]
    for pq in parsed:
        original = source_of.get(id(pq))
        if original is not None:
            level, qtype = original.level or Level(p["level"]), original.type
        else:
            level, qtype = Level(p["level"]), QuestionType(p["type"])
        pq.code = None  # mã và nguồn do hệ thống đặt
        pq.source = None
        pq.level = level
        dang = p["dang"]
        if not dang:
            # Giữ dạng bài mô hình ghi nếu dòng thẻ đúng lớp và chủ đề
            for t in pq.tags:
                if len(t) > len(base) and [slugify(x) for x in t[: len(base)]] == [slugify(x) for x in base]:
                    dang = t[len(base)]
                    break
        # biến thể giữ nguyên mọi thẻ của câu gốc
        pq.tags = ([bank.tag_names(t) for t in original.tags] if original is not None
                   else [base + ([dang] if dang else [])])
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
        if p["param"] and not pq.params:
            pq.errors.append("chưa phải câu tham số (thiếu dòng % @thamso)")
        if p["figure"] and not figures.find_figures(question_text(pq)):
            pq.warnings.append("yêu cầu câu có hình nhưng câu này chưa có hình vẽ")

    # Biên dịch thử mọi hình vẽ; hình lỗi không chặn câu mà được đánh dấu để người soạn sửa
    with ThreadPoolExecutor(2) as pool:
        fig_errors = dict(zip(map(id, parsed), pool.map(
            lambda pq: [] if pq.params else figures.check_text(question_text(pq)), parsed)))

    # câu tham số: đáp án đã tính từ công thức (và được kiểm khi phân tích), không kiểm @kiemtra
    answer_errors = {id(pq): [] if pq.params else kiemtra.check_question(pq, line)
                     for pq, line in zip(parsed, lines)}
    # biến thể không được trùng số liệu với câu khác trong nhóm (kể cả câu khác của lần sinh này)
    signatures: dict[str, dict[tuple, str]] = {}
    out = []
    for item in bank.preview_import(session, parsed):
        pq = item.parsed
        original = source_of.get(id(pq))
        if original is not None and item.state == "new" and not pq.params:
            sigs = signatures.get(original.code)
            if sigs is None:
                sigs = signatures[original.code] = {numbers_of(m.stem_latex): m.code
                                                    for m in bank.variant_members(session, original)}
            sig = numbers_of(pq.stem)
            if sig and sig in sigs:
                item.state = "duplicate"
                item.duplicate_of = sigs[sig] or "câu khác trong lần sinh này"
                pq.warnings.append("trùng số liệu với một câu cùng nhóm biến thể")
            elif sig:
                sigs[sig] = ""
        out.append({
            "index": item.index,
            "state": item.state,
            "line": pq.line,
            "type": pq.type.value,
            "stem": pq.stem,
            "tags": pq.tags,
            "errors": pq.errors,
            "warnings": pq.warnings,
            "figure_errors": fig_errors.get(id(pq), []),
            "answer_errors": answer_errors.get(id(pq), []),
            "answer_checked": bool(pq.params) or (item.index < len(lines) and lines[item.index] is not None),
            "param": bool(pq.params),
            "sample_stem": _sample_stem(pq),
            "duplicate_of": item.duplicate_of,
            "code": None,
            "variant_of": original.code if original is not None else None,
            "variant_label": labels.get(id(pq)),
            "parsed": pq,
        })
    return out


def _sample_stem(pq: ParsedQuestion) -> str | None:
    """Câu tham số: đề bài với một bộ số mẫu, để xem kết quả sinh dễ hơn."""
    if not pq.params or pq.errors:
        return None
    try:
        return params_mod.instantiate(pq.type, pq.params, pq.stem, [(c.content, c.is_correct, c.pinned) for c in pq.choices],
                                      pq.short_answer, pq.solution, random.Random(1)).stem
    except params_mod.ParamError:
        return None


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
        q.check_note = "; ".join(it["figure_errors"] + it["answer_errors"]) or None
        original = bank.get_question(session, it["variant_of"]) if it.get("variant_of") else None
        if original is not None:
            q.variant_group = bank.ensure_group(session, original, it.get("variant_label")).code
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


def create_batch(session: Session, params: dict, mode: str, output: str | None = None,
                 user_id: int | None = None, username: str | None = None,
                 group_id: str | None = None) -> GenerationBatch:
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
        user_id=user_id,
        username=username,
        group_id=group_id,
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


# ---------- Sinh nhiều ô trong một đợt ----------
# Mỗi ô (chủ đề × dạng × mức độ × loại câu × số câu) là một lần sinh riêng, các lần cùng đợt có chung
# `group_id`. Gọi Claude API thì mỗi ô một yêu cầu (prompt ngắn, ô lỗi chạy lại riêng); chép prompt thì
# gộp thành một prompt, kết quả dán lại được chia về từng ô theo dòng @tags và @level của từng câu.


def normalize_rows(rows: list[dict], limit: int = MAX_PROMPT) -> list[dict]:
    if not rows:
        raise GenError("chưa chọn ô nào để sinh")
    out = [normalize_params(r) for r in rows]
    total = sum(r["count"] for r in out)
    if total > limit:
        what = "mỗi đợt" if limit == MAX_TOTAL else "mỗi phần dán tay"
        raise GenError(f"{what} tối đa {limit} câu (đang chọn {total} câu)")
    return out


def build_multi_prompt(session: Session, rows: list[dict]) -> tuple[str, str]:
    """Prompt gộp cho nhiều ô (cách chép prompt sang Claude)."""
    rows = normalize_rows(rows)
    if len(rows) == 1:
        return build_prompt(session, rows[0])
    total = sum(r["count"] for r in rows)
    parts = [PARAM_RULES] if any(r["param"] for r in rows) else []
    parts += [f"Lần này cần soạn tổng cộng {total} câu cho {len(rows)} ô khác nhau, lần lượt từng ô. "
             "Mỗi câu ghi đúng dòng @tags và @level của ô nó thuộc về."]
    for i, r in enumerate(rows, 1):
        # ít câu mẫu hơn để prompt gộp không quá dài; bỏ dòng kết của từng ô
        _, user = build_prompt(session, r, n_examples=1, n_avoid=20, rules=False)
        parts.append(f"## Ô {i}\n\n" + user.rsplit("\n\n", 1)[0])
    counts = " + ".join(str(r["count"]) for r in rows)
    parts.append(f"Trả về đúng {total} khối câu hỏi ({counts} theo thứ tự các ô), không kèm lời dẫn.")
    return SYSTEM_PROMPT, "\n\n".join(parts)


def _row_of(pq: ParsedQuestion, rows: list[dict]) -> int | None:
    """Ô của một câu trong kết quả gộp: cùng loại câu, cùng mức độ, dòng thẻ thuộc chủ đề của ô;
    nhiều ô cùng chủ đề thì xét thêm dạng bài."""
    def matches(r: dict, check_level: bool) -> bool:
        if pq.type != QuestionType(r["type"]) or (check_level and pq.level != Level(r["level"])):
            return False
        if check_level and bool(pq.params) != bool(r.get("param")):
            return False
        base = [slugify(x) for x in topic_names(r["grade"], r["topic"])]
        return any([slugify(x) for x in t[: len(base)]] == base for t in pq.tags)

    for check_level in (True, False):  # thiếu hoặc sai @level thì chỉ xét chủ đề và loại câu
        cands = [i for i, r in enumerate(rows) if matches(r, check_level)]
        if cands:
            for i in cands:
                dang = rows[i]["dang"]
                if dang and any(slugify(dang) in [slugify(x) for x in t] for t in pq.tags):
                    return i
            return cands[0]
    return None


def route_output(rows: list[dict], text: str) -> tuple[list[str], list[dict]]:
    """Chia kết quả gộp về từng ô. Trả về (văn bản của từng ô, các câu không xếp được vào ô nào)."""
    texts: list[list[str]] = [[] for _ in rows]
    unmatched = []
    for n, chunk in enumerate(split_blocks(strip_fences(text)), 1):
        if len(rows) == 1:
            texts[0].append(chunk)
            continue
        pq = parse_text(chunk)[0]
        i = _row_of(pq, rows)
        if i is None:
            unmatched.append({"index": n, "stem": _short(pq.stem, 160), "tags": pq.tags,
                              "level": pq.level.value if pq.level else None, "type": pq.type.value})
        else:
            texts[i].append(chunk)
    return ["\n".join(t) for t in texts], unmatched


def check_multi(session: Session, rows: list[dict], text: str) -> dict:
    rows = normalize_rows(rows)
    texts, unmatched = route_output(rows, text)
    out = []
    for r, t in zip(rows, texts):
        items = check_output(session, r, t) if t else []
        for it in items:
            it.pop("parsed")
        out.append(items)
    return {"rows": out, "unmatched": unmatched}


def create_group(session: Session, rows: list[dict], mode: str, output: str | None = None,
                 user_id: int | None = None, username: str | None = None,
                 group_id: str | None = None) -> list[GenerationBatch]:
    """Tạo một đợt sinh: mỗi ô một lần sinh, chung mã đợt. Dán tay thì mỗi phần (tối đa MAX_PROMPT
    câu) lưu riêng; truyền `group_id` của phần trước để các phần chung một đợt."""
    rows = normalize_rows(rows, MAX_TOTAL if mode == "api" else MAX_PROMPT)
    group = group_id if group_id and re.fullmatch(r"[0-9a-f]{10}", group_id) else uuid.uuid4().hex[:10]
    if mode == "manual":
        if not (output or "").strip():
            raise GenError("chưa dán kết quả")
        texts, unmatched = route_output(rows, output)
        if not any(texts):
            raise GenError("không có câu nào khớp với các ô đã chọn")
    else:
        texts = [None] * len(rows)
    batches = []
    for r, t in zip(rows, texts):
        if mode == "manual" and not t:
            # ô không nhận được câu nào: vẫn ghi lại để thấy ô bị thiếu
            system, user = build_prompt(session, r)
            b = GenerationBatch(mode=mode, status=BuildStatus.FAILED, params=r, system_prompt=system,
                                user_prompt=user, items=[], user_id=user_id, username=username, group_id=group,
                                error="kết quả dán vào không có câu nào cho ô này", finished_at=datetime.now())
            session.add(b)
            session.commit()
        else:
            b = create_batch(session, r, mode, t, user_id=user_id, username=username, group_id=group)
        batches.append(b)
    session.commit()
    return batches


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
