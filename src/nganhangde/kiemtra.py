"""Tự kiểm tra đáp án câu sinh bằng AI.

Mỗi câu trắc nghiệm hoặc trả lời ngắn có đáp án là số (hoặc bộ số như tọa độ) kèm một dòng

    % @kiemtra: <biểu thức tính từ số liệu của đề> = <đáp án>

Máy chủ tự tính lại biểu thức (bộ tính an toàn, chỉ có phép toán và vài hàm, không chạy mã tuỳ ý),
so với đáp án ghi ở vế phải, rồi so vế phải với đáp án đúng trong câu (đọc từ LaTeX). Câu lệch thì bị
đánh dấu để người duyệt xem lại. Đáp án không đọc được thành số (biểu thức chứa x, khoảng, chữ)
thì bỏ qua, không báo lỗi.
"""

from __future__ import annotations

import ast
import math
import operator
import re

from .models import QuestionType
from .parser import ParsedQuestion

LINE_RE = re.compile(r"^\s*%\s*@kiemtra\s*:\s*(.+?)\s*$", re.MULTILINE)

Value = float | tuple[float, ...]


class CheckError(Exception):
    pass


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def _log(a: float, x: float | None = None) -> float:
    # log(x) = log cơ số 10; log(a, x) = log cơ số a của x (như kí hiệu log_a x)
    return math.log10(a) if x is None else math.log(x) / math.log(a)


FUNCS = {
    "sqrt": math.sqrt, "cbrt": _cbrt, "ln": math.log, "log": _log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan, "cot": lambda x: 1 / math.tan(x),
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "abs": abs,
    "factorial": lambda n: float(math.factorial(int(n))) if n == int(n) and 0 <= n <= 170 else math.nan,
    "comb": lambda n, k: float(math.comb(int(n), int(k))), "perm": lambda n, k: float(math.perm(int(n), int(k))),
}
CONSTS = {"pi": math.pi, "e": math.e}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.Pow: operator.pow, ast.Mod: operator.mod}


def _eval(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Tuple):
        return tuple(float(_eval(x)) for x in node.elts)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in CONSTS:
        return CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(a, tuple) or isinstance(b, tuple):
            raise CheckError("không tính toán trên bộ số")
        if isinstance(node.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e100):
            raise CheckError("số mũ quá lớn")
        return BINOPS[type(node.op)](a, b)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
        return float(FUNCS[node.func.id](*(_eval(a) for a in node.args)))
    raise CheckError("biểu thức có thành phần không hỗ trợ")


def evaluate(expr: str) -> Value:
    """Tính biểu thức số (dấu chấm thập phân, ^ là luỹ thừa, bộ số viết (a, b, c))."""
    expr = expr.strip().replace("^", "**").replace("×", "*").replace("−", "-")
    if len(expr) > 500:
        raise CheckError("biểu thức quá dài")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CheckError("biểu thức sai cú pháp") from e
    try:
        v = _eval(tree)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
        raise CheckError(f"không tính được ({e})") from e
    if any(math.isnan(x) or math.isinf(x) for x in (v if isinstance(v, tuple) else (v,))):
        raise CheckError("kết quả không xác định")
    return v


# ---------- Đọc đáp án viết bằng LaTeX ----------


def _group(s: str, i: int) -> tuple[str, int] | None:
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return None
    if s[i] != "{":
        return s[i], i + 1  # \frac12: một kí tự
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return None


def _latex_expr(s: str) -> str:
    """LaTeX của một số -> biểu thức cho `evaluate`; lỗi nếu còn kí hiệu không hiểu."""
    out = []
    i = 0
    while i < len(s):
        m = re.match(r"\\(dfrac|tfrac|frac)(?![A-Za-z])", s[i:])
        if m:
            a = _group(s, i + m.end())
            b = a and _group(s, a[1])
            if not b:
                raise CheckError("phân số thiếu tử hoặc mẫu")
            out.append(f"(({_latex_expr(a[0])})/({_latex_expr(b[0])}))")
            i = b[1]
            continue
        m = re.match(r"\\sqrt(?:\[([^\]]+)\])?", s[i:])
        if m:
            g = _group(s, i + m.end())
            if not g:
                raise CheckError("căn thiếu biểu thức")
            inner = _latex_expr(g[0])
            out.append(f"(({inner})**(1/({_latex_expr(m.group(1))})))" if m.group(1) else f"sqrt({inner})")
            i = g[1]
            continue
        if s[i] == "^":
            g = _group(s, i + 1)
            if not g:
                raise CheckError("luỹ thừa thiếu số mũ")
            out.append(f"**({_latex_expr(g[0])})")
            i = g[1]
            continue
        m = re.match(r"\\(pi|ln|log|sin|cos|tan|cot)(?![A-Za-z])", s[i:])
        if m:
            out.append(f" {m.group(1)} ")
            i += m.end()
            continue
        m = re.match(r"\\(cdot|times)(?![A-Za-z])", s[i:])
        if m:
            out.append("*")
            i += m.end()
            continue
        if s[i] == "\\":
            raise CheckError("có lệnh LaTeX chưa đọc được")
        out.append(s[i])
        i += 1
    expr = "".join(out).replace("{", "(").replace("}", ")")
    # nhân ngầm: 2sqrt(3), 3pi, 2(1+x), )(
    expr = re.sub(r"(?<=[\d.)])\s*(?=[a-z(])", "*", expr)
    expr = re.sub(r"\b(ln|log|sin|cos|tan|cot)\s*\*?\s*(\d[\d.]*)", r"\1(\2)", expr)  # \ln 2 -> ln(2)
    return expr


def latex_value(text: str) -> Value | None:
    """Giá trị số của đáp án viết bằng LaTeX ("$\\dfrac{1}{2}$", "2,5", "$(1;-2;3)$"); None nếu
    không phải một số hay bộ số đọc được."""
    s = (text or "").strip().replace("$", "")
    s = re.sub(r"\\(left|right|displaystyle|,|;|!|quad)(?![A-Za-z])", "", s)
    s = re.sub(r"\\(text|mathrm)\{[^}]*\}(\^\{?\d\}?)?", "", s)  # đơn vị, kể cả cm^3
    s = s.replace("{,}", ".").replace("\\{", "(").replace("\\}", ")")
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)  # dấu phẩy thập phân
    s = s.strip().rstrip(".")
    if not s:
        return None
    m = re.fullmatch(r"\(\s*(.+?)\s*\)", s)
    if m and ";" in m.group(1):  # tọa độ (a;b;c)
        parts = [latex_value(p) for p in m.group(1).split(";")]
        if any(p is None or isinstance(p, tuple) for p in parts):
            return None
        return tuple(parts)  # type: ignore[arg-type]
    try:
        v = evaluate(_latex_expr(s))
    except CheckError:
        return None
    return v


def close(a: Value, b: Value, tol: float = 0.0) -> bool:
    if isinstance(a, tuple) or isinstance(b, tuple):
        return isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b) and all(
            close(x, y, tol) for x, y in zip(a, b))
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=max(1e-9, tol))


def _decimals(text: str) -> int:
    m = re.search(r"[.,](\d+)\s*$", text.strip())
    return len(m.group(1)) if m else 0


def check_question(pq: ParsedQuestion, line: str | None) -> list[str]:
    """Các lỗi phát hiện được ở câu (rỗng nếu khớp hoặc không kiểm được)."""
    if pq.type not in (QuestionType.MCQ, QuestionType.SHORT):
        return []
    if pq.type == QuestionType.MCQ:
        correct = next((c.content for c in pq.choices if c.is_correct), None)
        answer = latex_value(correct) if correct else None
        others = [latex_value(c.content) for c in pq.choices if not c.is_correct]
    else:
        correct = pq.short_answer
        answer = latex_value(correct) if correct else None
        others = []
    errors = []
    if answer is not None and any(o is not None and close(o, answer) for o in others):
        errors.append("có phương án nhiễu bằng đúng đáp án")
    if not line:
        return errors
    if "=" not in line:
        return errors + ["dòng @kiemtra thiếu dấu ="]
    lhs, rhs = line.rsplit("=", 1)
    try:
        computed = evaluate(lhs)
        claimed = evaluate(rhs.replace(",", ".") if "(" not in rhs else rhs)
    except CheckError as e:
        return errors + [f"không tính được dòng @kiemtra: {e}"]
    # câu trả lời ngắn có yêu cầu làm tròn: cho phép lệch nửa đơn vị của chữ số cuối
    tol = 0.0
    if pq.type == QuestionType.SHORT and "làm tròn" in pq.stem.lower():
        tol = 0.5 * 10 ** -_decimals(rhs) + 1e-12
    if not close(computed, claimed, tol):
        errors.append(f"tính lại được {_fmt(computed)}, khác đáp số ghi trong @kiemtra ({rhs.strip()})")
    if answer is not None and not close(claimed, answer, 1e-12):
        errors.append(f"đáp án trong câu ({(correct or '').strip()}) khác đáp số @kiemtra ({rhs.strip()})")
    return errors


def _fmt(v: Value) -> str:
    if isinstance(v, tuple):
        return "(" + "; ".join(_fmt(x) for x in v) + ")"
    return f"{v:.6g}"


def find_line(chunk: str) -> str | None:
    m = LINE_RE.search(chunk)
    return m.group(1) if m else None
