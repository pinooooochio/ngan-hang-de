"""Biên dịch .tex sang PDF bằng latexmk + XeLaTeX."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 120  # giây cho mỗi file
MARKER_RE = re.compile(r"^% @@CAU (\S+)")


@dataclass
class CompileResult:
    ok: bool
    pdf: Path | None
    error: str = ""
    question: str | None = None  # mã câu gây lỗi, nếu xác định được


def latex_available() -> bool:
    return shutil.which("latexmk") is not None and shutil.which("xelatex") is not None


def question_at_line(tex: Path, line: int) -> str | None:
    """Tìm mã câu hỏi gần nhất phía trên dòng `line` của file .tex."""
    code = None
    for i, text in enumerate(tex.read_text(encoding="utf-8").splitlines(), 1):
        if i > line:
            break
        m = MARKER_RE.match(text)
        if m:
            code = m.group(1)
    return code


def first_error(log: str) -> tuple[str, int | None]:
    lines = log.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("!"):
            msg = ln[1:].strip()
            for nxt in lines[i + 1 : i + 15]:
                m = re.match(r"l\.(\d+)", nxt)
                if m:
                    return msg, int(m.group(1))
            return msg, None
    return "", None


def compile_tex(tex: Path) -> CompileResult:
    tex = tex.resolve()
    cmd = [
        "latexmk",
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",
        tex.name,
    ]
    try:
        subprocess.run(cmd, cwd=tex.parent, capture_output=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return CompileResult(False, None, f"quá {TIMEOUT} giây")
    pdf = tex.with_suffix(".pdf")
    log_path = tex.with_suffix(".log")
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    msg, line = first_error(log)
    if msg or not pdf.exists():
        code = question_at_line(tex, line) if line else None
        return CompileResult(False, None, msg or "không tạo được PDF", code)
    subprocess.run(["latexmk", "-c", tex.name], cwd=tex.parent, capture_output=True, check=False)
    return CompileResult(True, pdf)
