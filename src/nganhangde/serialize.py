"""Chuyển câu hỏi trong ngân hàng ngược lại định dạng soạn (ex_test) để sửa hoặc xuất file."""

from __future__ import annotations

from .bank import tag_names
from .models import Question, QuestionType


def question_to_ex(q: Question) -> str:
    meta = []
    if q.tags:
        meta.append("@tags: " + ", ".join(" / ".join(tag_names(t)) for t in q.tags))
    if q.level:
        meta.append(f"@level: {q.level.value}")
    meta.append(f"@id: {q.code}")
    if q.source:
        meta.append(f"@source: {q.source}")
    lines = ["% " + " ; ".join(meta)]
    lines.append("\\begin{ex}" + (f"%[{q.ex_id}]" if q.ex_id else ""))
    lines.append(indent(q.stem_latex))
    if q.type in (QuestionType.MCQ, QuestionType.TRUE_FALSE):
        lines.append("  \\choice" if q.type == QuestionType.MCQ else "  \\choiceTF")
        for c in q.choices:
            marks = ("\\True" if c.is_correct else "") + ("\\Pin" if c.pinned else "")
            lines.append("    {" + (marks + " " if marks else "") + c.content_latex + "}")
    if q.type == QuestionType.SHORT:
        lines.append("  \\shortans{" + (q.short_answer or "") + "}")
    if q.solution_latex:
        lines.append("  \\loigiai{" + q.solution_latex + "}")
    lines.append("\\end{ex}")
    return "\n".join(lines) + "\n"


def indent(text: str) -> str:
    return "\n".join(("  " + ln) if ln.strip() else "" for ln in text.splitlines())


NEW_TEMPLATE = """% Điền thẻ theo dạng "Lớp 12 / Tên chủ đề / Tên dạng bài"; mức độ: NB, TH, VD hoặc VDC
% @tags:  ; @level: NB
\\begin{ex}
  Nội dung câu hỏi, công thức đặt trong $...$.
  \\choice
    {\\True Đáp án đúng}
    {Phương án 2}
    {Phương án 3}
    {Phương án 4}
  \\loigiai{Lời giải chi tiết.}
\\end{ex}
"""
