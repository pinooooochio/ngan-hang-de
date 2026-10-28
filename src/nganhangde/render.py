"""Ghép dữ liệu mã đề vào template LaTeX."""

from __future__ import annotations

import copy
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).parent / "templates"

TEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex_escape(s: object) -> str:
    """Thoát ký tự đặc biệt cho văn bản thường (tiêu đề, tên phần), không dùng cho nội dung LaTeX."""
    return "".join(TEX_SPECIAL.get(ch, ch) for ch in str(s))


def date_text(value: str | None) -> str:
    """'2026-10-22' -> 'Ngày 22 tháng 10 năm 2026'."""
    if not value:
        return ""
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return tex_escape(value)
    return f"Ngày {d.day} tháng {d.month} năm {d.year}"


def make_env() -> Environment:
    env = Environment(
        loader=PackageLoader("nganhangde", "templates"),
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,
    )
    env.filters["tex"] = tex_escape
    return env


def _prepare(data: dict) -> dict:
    """Thêm các trường tiện cho template: chỉ số đáp án đúng (1..4), số thứ tự câu."""
    for sec in data["sections"]:
        for n, q in enumerate(sec["questions"], 1):
            q["number"] = n
            q["correct_index"] = next((i + 1 for i, c in enumerate(q["choices"]) if c["correct"]), 0)
    return data


def render_exam(data: dict, solutions: bool = False) -> str:
    v = _prepare(copy.deepcopy(data))
    return make_env().get_template("de.tex.j2").render(v=v, solutions=solutions, date_text=date_text(v.get("date")))


def render_answer_key(title: str, exam_date: str | None, variants: list[tuple[dict, dict]]) -> str:
    """`variants` là danh sách (data, answer_key) của từng mã đề."""
    rows = []
    for data, key in variants:
        sections = []
        for sec, keys in zip(data["sections"], key["sections"]):
            qs = [{"number": i + 1, "key": tex_escape(k)} for i, k in enumerate(keys)]
            sections.append({"name": sec["name"], "type": sec["type"], "questions": qs})
        rows.append({"code": data["code"], "sections": sections})
    return make_env().get_template("dapan.tex.j2").render(
        title=title, date_text=date_text(exam_date), variants=rows
    )


STYLE_FILES = ("nhd.sty", "nhd-hinh.sty")


def copy_style(dest: Path) -> None:
    for name in STYLE_FILES:
        shutil.copy(TEMPLATE_DIR / name, dest / name)
