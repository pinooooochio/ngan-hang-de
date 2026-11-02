"""Câu tham số: câu mẫu có biến, mỗi lần ra đề hoặc luyện thì bốc số mới và tính lại đáp án.

Câu mẫu là một câu ex_test bình thường, thêm các dòng chú thích phía trên:

    % @thamso: a = 1..5; b = -4..4; c = {1, 2, 3}; k = 2..10 buoc 2
    % @dieukien: b != 0; a != c
    % @tinh: d = 2*a + c; s = a/b

và trong đề, phương án, đáp số, lời giải viết chỗ thay số là ``{{bieu_thuc}}`` hoặc ``{{bieu_thuc:kieu}}``:

- ``{{a}}``, ``{{2*a + c}}``: giá trị (phân số viết \\dfrac, số thập phân dùng dấu phẩy);
- ``{{b:+}}``: số hạng có dấu, ví dụ "+ 3", "- 3" (viết ``x {{b:+}}`` thay cho ``x + {{b}}``);
- ``{{a:c}}``: hệ số đứng đầu, 1 thành rỗng, -1 thành "-" (``{{a:c}}x^2``);
- ``{{b:c+}}``: hệ số có dấu ở giữa biểu thức, 1 thành "+", -1 thành "-" (``x^2 {{b:c+}}x``);
- ``{{b:()}}``: số âm đặt trong ngoặc, ví dụ (-3);
- ``{{s:.2}}``: làm tròn 2 chữ số thập phân.

Tính toán dùng phân số đúng (không sai số) khi có thể; căn, lôgarit, lượng giác dùng số thực. Bộ tính an
toàn: chỉ có phép toán, so sánh và một số hàm, không chạy mã tuỳ ý.
"""

from __future__ import annotations

import ast
import math
import operator
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction

from .models import QuestionType

PARAM_RE = re.compile(r"^\s*%\s*@thamso\s*:\s*(.+?)\s*$", re.MULTILINE)
COND_RE = re.compile(r"^\s*%\s*@dieukien\s*:\s*(.+?)\s*$", re.MULTILINE)
CALC_RE = re.compile(r"^\s*%\s*@tinh\s*:\s*(.+?)\s*$", re.MULTILINE)
SLOT_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
RANGE_RE = re.compile(r"^(-?\d+)\s*\.\.\s*(-?\d+)(?:\s+(?:buoc|bước|step)\s+(\d+))?$")
NAME_RE = re.compile(r"^[A-Za-z_]\w*$")

MAX_DOMAIN = 100_000  # số bộ số tối đa để đếm chính xác
TRIES = 400  # số lần bốc thử khi ra một bộ số

Value = Fraction | float | bool


class ParamError(Exception):
    pass


# ---------- Bộ tính ----------


def _sqrt(x):
    if isinstance(x, Fraction) and x >= 0:
        n, d = math.isqrt(x.numerator), math.isqrt(x.denominator)
        if n * n == x.numerator and d * d == x.denominator:
            return Fraction(n, d)
    return math.sqrt(x)


def _int(x) -> int:
    if isinstance(x, Fraction) and x.denominator == 1:
        return int(x)
    if isinstance(x, float) and x.is_integer():
        return int(x)
    raise ParamError(f"cần số nguyên, nhận {x}")


def _frac(f):
    """Hàm số thực, kết quả nguyên thì trả về phân số đúng."""
    def g(*args):
        v = f(*(float(a) for a in args))
        return Fraction(round(v)) if abs(v - round(v)) < 1e-12 else v
    return g


FUNCS = {
    "sqrt": _sqrt,
    "abs": abs,
    "min": min,
    "max": max,
    "gcd": lambda a, b: Fraction(math.gcd(_int(a), _int(b))),
    "lcm": lambda a, b: Fraction(math.lcm(_int(a), _int(b))),
    "floor": lambda x: Fraction(math.floor(x)),
    "ceil": lambda x: Fraction(math.ceil(x)),
    "round": lambda x, n=0: Fraction(round(Fraction(x), _int(n))),
    "comb": lambda n, k: Fraction(math.comb(_int(n), _int(k))),
    "perm": lambda n, k: Fraction(math.perm(_int(n), _int(k))),
    "factorial": lambda n: Fraction(math.factorial(_int(n))),
    "cbrt": _frac(lambda x: math.copysign(abs(x) ** (1 / 3), x)),
    "ln": _frac(math.log),
    "log": _frac(lambda a, x=None: math.log10(a) if x is None else math.log(x) / math.log(a)),
    "exp": _frac(math.exp),
    "sin": _frac(math.sin),
    "cos": _frac(math.cos),
    "tan": _frac(math.tan),
}
CONSTS = {"pi": math.pi, "e": math.e}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
CMPOPS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
          ast.Gt: operator.gt, ast.GtE: operator.ge}


def _close(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _eval(node: ast.AST, env: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value)) if isinstance(node.value, float) else Fraction(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in CONSTS:
            return CONSTS[node.id]
        raise ParamError(f"chưa khai báo {node.id}")
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        if isinstance(node.op, ast.Not):
            return not v
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow):
            if isinstance(b, Fraction) and b.denominator == 1 and abs(b) <= 64 and not (a == 0 and b < 0):
                return Fraction(a) ** int(b) if isinstance(a, Fraction) else a ** int(b)
            if abs(float(b)) > 64:
                raise ParamError("số mũ quá lớn")
            return float(a) ** float(b)
        if type(node.op) in BINOPS:
            if isinstance(node.op, (ast.Div, ast.Mod, ast.FloorDiv)) and b == 0:
                raise ParamError("chia cho 0")
            return BINOPS[type(node.op)](a, b)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, env)
            if type(op) not in CMPOPS:
                break
            if isinstance(op, ast.Eq):
                ok = _close(left, right)
            elif isinstance(op, ast.NotEq):
                ok = not _close(left, right)
            else:
                ok = CMPOPS[type(op)](left, right)
            if not ok:
                return False
            left = right
        else:
            return True
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, env) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
        return FUNCS[node.func.id](*(_eval(a, env) for a in node.args))
    raise ParamError("biểu thức có thành phần không hỗ trợ")


def _prep(expr: str) -> str:
    e = expr.strip().replace("^", "**").replace("×", "*").replace("−", "-").replace("≠", "!=")
    e = re.sub(r"(?<![<>=!])=(?!=)", "==", e)  # "a = b" trong điều kiện
    e = re.sub(r"\bva\b|\bvà\b", " and ", e)
    e = re.sub(r"\bhoac\b|\bhoặc\b", " or ", e)
    return e


_CACHE: dict[str, ast.AST] = {}


def compile_expr(expr: str) -> ast.AST:
    tree = _CACHE.get(expr)
    if tree is None:
        e = _prep(expr)
        if len(e) > 400:
            raise ParamError("biểu thức quá dài")
        try:
            tree = ast.parse(e, mode="eval")
        except SyntaxError as err:
            raise ParamError(f"biểu thức sai cú pháp: {expr}") from err
        _CACHE[expr] = tree
    return tree


def evaluate(expr: str, env: dict):
    try:
        return _eval(compile_expr(expr), env)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
        raise ParamError(f"không tính được {expr} ({e})") from e


# ---------- Khai báo tham số ----------


@dataclass
class Spec:
    params: list[tuple[str, list[Fraction]]] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    derived: list[tuple[str, str]] = field(default_factory=list)

    @property
    def names(self) -> set[str]:
        return {n for n, _ in self.params} | {n for n, _ in self.derived}

    def domain_size(self) -> int:
        n = 1
        for _, vals in self.params:
            n *= len(vals)
        return n


def find_lines(text: str) -> str | None:
    """Các dòng khai báo tham số (giữ nguyên dạng chú thích) trong mã nguồn một câu; None nếu không có."""
    out = []
    for regex, key in ((PARAM_RE, "thamso"), (COND_RE, "dieukien"), (CALC_RE, "tinh")):
        out += [f"% @{key}: {m}" for m in regex.findall(text)]
    return "\n".join(out) or None


def parse_spec(lines: str) -> Spec:
    spec = Spec()
    for m in PARAM_RE.findall(lines):
        for part in filter(None, (p.strip() for p in _split(m))):
            name, _, dom = part.partition("=")
            name, dom = name.strip(), dom.strip()
            if not NAME_RE.match(name) or name in FUNCS or name in CONSTS:
                raise ParamError(f"tên tham số không hợp lệ: {name!r}")
            r = RANGE_RE.match(dom)
            if r:
                lo, hi, step = int(r.group(1)), int(r.group(2)), int(r.group(3) or 1)
                if hi < lo:
                    raise ParamError(f"{name}: khoảng {lo}..{hi} rỗng")
                vals = [Fraction(v) for v in range(lo, hi + 1, step)]
            elif dom.startswith("{") and dom.endswith("}"):
                vals = []
                for v in dom[1:-1].split(","):
                    if v.strip():
                        x = evaluate(v, {})
                        if not isinstance(x, Fraction):
                            raise ParamError(f"{name}: giá trị {v.strip()} phải là số hữu tỉ")
                        vals.append(x)
            else:
                raise ParamError(f"{name}: miền giá trị viết dạng 1..5, -3..3 buoc 2 hoặc {{1, 2, 1/2}}")
            if not vals:
                raise ParamError(f"{name}: chưa có giá trị nào")
            if name in spec.names:
                raise ParamError(f"tham số {name} khai báo hai lần")
            spec.params.append((name, vals))
    for m in COND_RE.findall(lines):
        for part in filter(None, (p.strip() for p in _split(m))):
            compile_expr(part)
            spec.conditions.append(part)
    for m in CALC_RE.findall(lines):
        for part in filter(None, (p.strip() for p in _split(m))):
            name, eq, expr = part.partition("=")
            name = name.strip()
            if not eq or not NAME_RE.match(name) or name in FUNCS or name in CONSTS:
                raise ParamError(f"dòng @tinh viết dạng ten = bieu_thuc: {part!r}")
            if name in spec.names:
                raise ParamError(f"{name} đã được khai báo")
            compile_expr(expr)
            spec.derived.append((name, expr.strip()))
    if not spec.params:
        raise ParamError("chưa có dòng % @thamso nào")
    return spec


def _split(s: str) -> list[str]:
    """Tách theo dấu ; nằm ngoài ngoặc nhọn."""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == ";" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def draw(spec: Spec, rng: random.Random) -> dict | None:
    """Một bộ số thoả điều kiện (kèm các giá trị @tinh), hoặc None nếu lần bốc này không đạt."""
    env = {name: rng.choice(vals) for name, vals in spec.params}
    for cond in spec.conditions:
        if not evaluate(cond, env):
            return None
    for name, expr in spec.derived:
        env[name] = evaluate(expr, env)
    return env


# ---------- Viết số ----------


def _dec(v: float, n: int | None = None) -> str:
    s = f"{v:.{n}f}" if n is not None else f"{v:.4f}".rstrip("0").rstrip(".")
    if n is None and s in ("-0", ""):
        s = "0"
    return s.replace(".", "{,}")


def fmt(v, kind: str = "") -> str:
    if isinstance(v, bool):
        raise ParamError("giá trị đúng/sai không viết vào câu được")
    m = re.fullmatch(r"\.(\d)", kind)
    if m:
        return _dec(float(v), int(m.group(1)))
    if kind == "+":
        return ("- " if v < 0 else "+ ") + fmt(abs(v))
    if kind == "c":
        return "" if v == 1 else "-" if v == -1 else fmt(v)
    if kind == "c+":
        return "+ " if v == 1 else "- " if v == -1 else ("- " if v < 0 else "+ ") + fmt(abs(v))
    if kind == "()":
        return f"({fmt(v)})" if v < 0 else fmt(v)
    if kind not in ("", "f"):
        raise ParamError(f"kiểu viết số không hỗ trợ: {kind!r}")
    if isinstance(v, Fraction):
        if v.denominator == 1:
            return str(v.numerator)
        sign = "-" if v < 0 else ""
        return f"{sign}\\dfrac{{{abs(v.numerator)}}}{{{v.denominator}}}"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return _dec(v)


def render(text: str, env: dict) -> str:
    def sub(m: re.Match) -> str:
        expr, _, kind = m.group(1).rpartition(":") if ":" in m.group(1) else (m.group(1), "", "")
        return fmt(evaluate(expr, env), kind.strip())
    return SLOT_RE.sub(sub, text or "")


def slots(text: str) -> list[str]:
    return SLOT_RE.findall(text or "")


# ---------- Một bản cụ thể của câu mẫu ----------


@dataclass
class Instance:
    values: dict
    stem: str
    choices: list[tuple[str, bool, bool]]  # (nội dung, đúng, ghim)
    short_answer: str | None
    solution: str

    def values_text(self) -> dict[str, str]:
        return {k: fmt(v) if not isinstance(v, bool) else str(v) for k, v in self.values.items()}


def make_instance(qtype: QuestionType, stem: str, choices: list[tuple[str, bool, bool]], short_answer: str | None,
                  solution: str, env: dict) -> Instance:
    inst = Instance(
        values=env,
        stem=render(stem, env),
        choices=[(render(c, env), ok, pin) for c, ok, pin in choices],
        short_answer=render(short_answer, env).replace("{,}", ",") if short_answer else short_answer,
        solution=render(solution, env),
    )
    problem = validate(qtype, inst)
    if problem:
        raise ParamError(problem)
    return inst


def validate(qtype: QuestionType, inst: Instance) -> str | None:
    """Lỗi của một bản cụ thể (phương án trùng nhau, đáp số trả lời ngắn quá dài...), None nếu ổn."""
    from .kiemtra import close, latex_value

    if qtype == QuestionType.MCQ:
        texts = [" ".join(c.split()) for c, _, _ in inst.choices]
        if len(set(texts)) < len(texts):
            return "hai phương án giống nhau"
        vals = [latex_value(c) for c, _, _ in inst.choices]
        right = [v for v, (_, ok, _) in zip(vals, inst.choices) if ok]
        wrong = [v for v, (_, ok, _) in zip(vals, inst.choices) if not ok]
        if right and right[0] is not None and any(w is not None and close(w, right[0]) for w in wrong):
            return "phương án nhiễu bằng đáp án đúng"
        known = [v for v in vals if v is not None]
        if any(close(a, b) for i, a in enumerate(known) for b in known[i + 1:]):
            return "hai phương án cùng giá trị"
    if qtype == QuestionType.SHORT:
        t = (inst.short_answer or "").replace(" ", "").replace("$", "")
        if len(t) > 4:
            return f"đáp số {t} dài quá 4 kí tự"
        try:
            float(t.replace(",", "."))
        except ValueError:
            return f"đáp số {t!r} không phải số"
    return None


@dataclass
class Report:
    ok: bool
    errors: list[str]
    warnings: list[str]
    tried: int = 0
    valid: int = 0
    distinct: int = 0
    domain: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    samples: list[Instance] = field(default_factory=list)


def check(qtype: QuestionType, lines: str, stem: str, choices: list[tuple[str, bool, bool]],
          short_answer: str | None, solution: str, n: int = 200, n_samples: int = 3,
          rng: random.Random | None = None) -> Report:
    """Chạy thử `n` lần bốc số: đếm số bộ hợp lệ, gom lý do hỏng, lấy vài bản mẫu để người duyệt xem."""
    rng = rng or random.Random()
    try:
        spec = parse_spec(lines)
    except ParamError as e:
        return Report(False, [str(e)], [])
    errors, warnings = [], []
    used = set()
    for t in [stem, solution, short_answer or "", *(c for c, _, _ in choices)]:
        for s in slots(t):
            expr = s.rpartition(":")[0] if ":" in s else s
            try:
                used |= {node.id for node in ast.walk(compile_expr(expr)) if isinstance(node, ast.Name)}
            except ParamError as e:
                errors.append(f"chỗ thay số {{{{{s}}}}}: {e}")
    if not any(slots(t) for t in [stem, *(c for c, _, _ in choices)]):
        errors.append("đề bài và phương án chưa có chỗ thay số {{...}} nào")
    unused = [name for name, _ in spec.params if name not in used and not any(
        name in c for c in spec.conditions + [e for _, e in spec.derived])]
    if unused:
        warnings.append(f"tham số không dùng tới: {', '.join(unused)}")
    if errors:
        return Report(False, errors, warnings)

    rep = Report(True, errors, warnings, domain=spec.domain_size())
    reasons: Counter = Counter()
    seen: set = set()
    for _ in range(n):
        rep.tried += 1
        try:
            env = draw(spec, rng)
            if env is None:
                reasons["không thoả @dieukien"] += 1
                continue
            inst = make_instance(qtype, stem, choices, short_answer, solution, env)
        except ParamError as e:
            reasons[str(e)] += 1
            continue
        rep.valid += 1
        key = tuple(sorted((k, str(v)) for k, v in env.items()))
        if key not in seen:
            seen.add(key)
            if len(rep.samples) < n_samples:
                rep.samples.append(inst)
    rep.distinct = len(seen)
    rep.reasons = dict(reasons.most_common(6))
    if rep.valid == 0:
        rep.ok = False
        rep.errors.append("không bốc được bộ số nào hợp lệ: " + "; ".join(f"{k} ({v} lần)" for k, v in rep.reasons.items()))
    elif rep.distinct < 3:
        rep.ok = False
        rep.errors.append(f"chỉ có {rep.distinct} bộ số khác nhau, cần ít nhất 3 (mở rộng miền giá trị)")
    else:
        bad = rep.tried - rep.valid - reasons.get("không thoả @dieukien", 0)
        if bad:
            warnings.append(f"{bad}/{rep.tried} lần bốc cho câu lỗi (" + "; ".join(
                f"{k}" for k in rep.reasons if k != "không thoả @dieukien") + "), các bộ số đó bị bỏ")
        if rep.valid * 5 < rep.tried:
            warnings.append(f"chỉ {rep.valid}/{rep.tried} lần bốc đạt điều kiện, nên nới miền giá trị")
    return rep


def instantiate(qtype: QuestionType, lines: str, stem: str, choices: list[tuple[str, bool, bool]],
                short_answer: str | None, solution: str, rng: random.Random) -> Instance:
    """Một bản cụ thể ngẫu nhiên (theo `rng`); lỗi nếu bốc TRIES lần không được bộ số hợp lệ."""
    spec = parse_spec(lines)
    last = "không thoả @dieukien"
    for _ in range(TRIES):
        try:
            env = draw(spec, rng)
            if env is None:
                continue
            return make_instance(qtype, stem, choices, short_answer, solution, env)
        except ParamError as e:
            last = str(e)
    raise ParamError(f"không bốc được bộ số hợp lệ ({last})")


def instantiate_question(q, rng: random.Random) -> Instance:
    """Bản cụ thể của câu tham số trong ngân hàng (models.Question có `params`)."""
    return instantiate(q.type, q.params, q.stem_latex,
                       [(c.content_latex, c.is_correct, c.pinned) for c in q.choices],
                       q.short_answer, q.solution_latex, rng)
