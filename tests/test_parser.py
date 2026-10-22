from nganhangde.models import Level, QuestionType
from nganhangde.parser import parse_text, slugify

MCQ = r"""
% @tags: Lớp 12 / Vectơ trong không gian ; @level: TH ; @id: T-1
\begin{ex}
  Cho $\vec u=(1;2;3)$. Chọn khẳng định đúng.
  \choice
    {$|\vec u|=14$}
    {\True $|\vec u|=\sqrt{14}$}
    {$\{1\}$}
    {\True\Pin Không có}
  \loigiai{Ta có $|\vec u|=\sqrt{14}$.}
\end{ex}
"""


def test_slugify_vietnamese():
    assert slugify("Lớp 12") == "lop-12"
    assert slugify("Vectơ trong không gian") == "vecto-trong-khong-gian"
    assert slugify("Đường thẳng") == "duong-thang"


def test_mcq_fields_and_two_true_is_error():
    [q] = parse_text(MCQ)
    assert q.type == QuestionType.MCQ
    assert q.code == "T-1"
    assert q.level == Level.TH
    assert q.tags == [["Lớp 12", "Vectơ trong không gian"]]
    assert [c.is_correct for c in q.choices] == [False, True, False, True]
    assert q.choices[3].pinned and q.choices[3].content == "Không có"
    assert q.choices[2].content == r"$\{1\}$"
    assert q.solution == r"Ta có $|\vec u|=\sqrt{14}$."
    assert any("đúng 1" in e for e in q.errors)


def test_true_false_short_essay():
    text = r"""
\begin{ex} Mệnh đề. \choiceTF{\True a}{b}{\True c}{d} \end{ex}
\begin{ex} Tính. \shortans[oly]{2,5} \end{ex}
\begin{ex} Chứng minh. \loigiai{Hiển nhiên.} \end{ex}
"""
    tf, short, essay = parse_text(text)
    assert tf.type == QuestionType.TRUE_FALSE and tf.ok
    assert [c.is_correct for c in tf.choices] == [True, False, True, False]
    assert short.type == QuestionType.SHORT and short.short_answer == "2,5"
    assert essay.type == QuestionType.ESSAY and essay.solution == "Hiển nhiên."


def test_ex_id_gives_grade_and_level():
    [q] = parse_text(r"\begin{ex}%[2H3V1-1]" "\n" r"Câu. \choice{\True a}{b}{c}{d}\end{ex}")
    assert q.ex_id == "2H3V1-1"
    assert q.level == Level.VD
    assert q.tags == [["Lớp 12"]]


def test_block_inside_comment_is_ignored():
    text = "% ví dụ: \\begin{ex} ... \\end{ex}\n\\begin{ex} Câu thật. \\choice{\\True a}{b}{c}{d}\\end{ex}"
    [q] = parse_text(text)
    assert q.stem == "Câu thật."


def test_letter_reference_in_solution_warns():
    [q] = parse_text(r"\begin{ex} X. \choice{\True a}{b}{c}{d} \loigiai{Vậy chọn A.}\end{ex}")
    assert q.ok
    assert any("chữ cái" in w for w in q.warnings)


def test_wrong_choice_count_is_error():
    [q] = parse_text(r"\begin{ex} X. \choice{\True a}{b}{c} \end{ex}")
    assert not q.ok
