"""Hình vẽ TikZ trong câu hỏi: biên dịch từng hình ra ảnh SVG để xem trên web.

Mỗi khối \\begin{tikzpicture}...\\end{tikzpicture} được ghép vào một trang `standalone` dùng chung
gói vẽ hình với đề in (templates/nhd-hinh.sty), biên dịch bằng XeLaTeX rồi đổi PDF sang SVG bằng
pdftocairo. Kết quả lưu trong thư mục file (NHD_FILES/hinh) theo mã băm của mã hình và gói vẽ,
nên mỗi hình chỉ biên dịch một lần; hình lỗi cũng được lưu lại kèm thông báo lỗi.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .builds import files_dir
from .compile import first_error, latex_available
from .render import TEMPLATE_DIR

TIKZ_RE = re.compile(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", re.DOTALL)
ID_RE = re.compile(r"^[0-9a-f]{32}$")
TIMEOUT = 60  # giây cho mỗi hình
MAX_LEN = 20000  # độ dài tối đa mã một hình

DOCUMENT = r"""\documentclass[border=2pt]{standalone}
\usepackage{fontspec}
\setmainfont{Latin Modern Roman}
\usepackage{amsmath,amssymb}
\usepackage{nhd-hinh}
\begin{document}
%s
\end{document}
"""

# Mỗi lúc chỉ biên dịch vài hình, tránh làm nghẽn máy chủ khi một trang có nhiều hình
_slots = threading.BoundedSemaphore(2)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass
class Figure:
    id: str
    ok: bool
    error: str = ""


def find_figures(text: str) -> list[str]:
    return TIKZ_RE.findall(text or "")


def available() -> bool:
    return latex_available() and shutil.which("pdftocairo") is not None


def _style() -> str:
    return (TEMPLATE_DIR / "nhd-hinh.sty").read_text(encoding="utf-8")


def figure_id(code: str) -> str:
    """Mã hình: đổi khi mã TikZ hoặc gói vẽ hình đổi."""
    return hashlib.sha256((_style() + "\n" + code.strip()).encode("utf-8")).hexdigest()[:32]


def cache_dir() -> Path:
    return files_dir() / "hinh"


def svg_path(fid: str) -> Path:
    return cache_dir() / f"{fid}.svg"


def cached(fid: str) -> Figure | None:
    if svg_path(fid).exists():
        return Figure(fid, True)
    err = cache_dir() / f"{fid}.err"
    if err.exists():
        return Figure(fid, False, err.read_text(encoding="utf-8"))
    return None


CODE_LINE = DOCUMENT.split("%s")[0].count("\n") + 1  # dòng đầu của mã hình trong file .tex


def _describe(msg: str, line: int | None, log: str) -> str:
    """Thông báo lỗi kèm dòng của mã hình và đoạn mã ngay trước chỗ lỗi (TeX in ở dòng `l.<số>`)."""
    if line is None:
        return msg
    m = re.search(rf"^l\.{line} (.*)$", log, re.MULTILINE)
    near = m.group(1).strip()[-60:] if m else ""
    where = f"dòng {line - CODE_LINE + 1} của hình"
    return f"{msg} ({where}: {near})" if near else f"{msg} ({where})"


def _compile(code: str) -> tuple[bytes | None, str]:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        shutil.copy(TEMPLATE_DIR / "nhd-hinh.sty", folder / "nhd-hinh.sty")
        (folder / "hinh.tex").write_text(DOCUMENT % code.strip(), encoding="utf-8")
        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "hinh.tex"]
        try:
            subprocess.run(cmd, cwd=folder, capture_output=True, timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            return None, f"biên dịch quá {TIMEOUT} giây"
        log = folder / "hinh.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        msg, line = first_error(text)
        if msg or not (folder / "hinh.pdf").exists():
            return None, _describe(msg, line, text) if msg else "không tạo được hình"
        r = subprocess.run(["pdftocairo", "-svg", "hinh.pdf", "hinh.svg"], cwd=folder, capture_output=True, check=False)
        if r.returncode != 0 or not (folder / "hinh.svg").exists():
            return None, "không đổi được hình sang SVG"
        return (folder / "hinh.svg").read_bytes(), ""


def render(code: str) -> Figure:
    """Biên dịch một hình (hoặc lấy bản đã lưu)."""
    code = code.strip()
    fid = figure_id(code)
    if (hit := cached(fid)) is not None:
        return hit
    if len(code) > MAX_LEN:
        return Figure(fid, False, "mã hình quá dài")
    if not TIKZ_RE.fullmatch(code) or len(find_figures(code)) != 1:
        return Figure(fid, False, "không phải một khối tikzpicture")
    if not available():
        return Figure(fid, False, "máy chủ chưa cài XeLaTeX/pdftocairo")
    with _locks_guard:
        lock = _locks.setdefault(fid, threading.Lock())
    with lock:  # hai yêu cầu cùng một hình thì chỉ biên dịch một lần
        if (hit := cached(fid)) is not None:
            return hit
        with _slots:
            svg, error = _compile(code)
        cache_dir().mkdir(parents=True, exist_ok=True)
        target = svg_path(fid) if svg else cache_dir() / f"{fid}.err"
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(svg) if svg else tmp.write_text(error, encoding="utf-8")
        tmp.replace(target)
    with _locks_guard:
        _locks.pop(fid, None)
    return Figure(fid, svg is not None, error)


def check_text(text: str) -> list[str]:
    """Biên dịch mọi hình trong đoạn LaTeX, trả về thông báo lỗi của các hình lỗi."""
    errors = []
    figs = find_figures(text)
    for i, code in enumerate(figs, 1):
        f = render(code)
        if not f.ok:
            name = f"hình {i}" if len(figs) > 1 else "hình vẽ"
            errors.append(f"{name} không biên dịch được: {f.error}")
    return errors
