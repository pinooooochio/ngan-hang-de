import random
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from helpers import login_admin
from nganhangde import params
from nganhangde.api import create_app
from nganhangde.models import QuestionType
from nganhangde.parser import parse_text

DOT = r"""% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
% @thamso: a = 1..6; b = -5..5; c = -4..4
% @dieukien: c != 0; b != 0
% @tinh: d = 2*a + c
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=({{a}};{{b}};{{c}})$ và $\vec v=(2;0;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice{\True ${{d}}$}{${{2*a - c}}$}{${{d + 1}}$}{${{-d - 2}}$}
  \loigiai{$\vec u\cdot\vec v = {{a}}\cdot 2 + {{b:()}}\cdot 0 + {{c:()}}\cdot 1 = {{d}}$.}
\end{ex}
"""

SHORT = r"""% @tags: Lớp 12 / Nguyên hàm và tích phân ; @level: TH
% @thamso: a = 1..4; b = 1..3
% @tinh: I = a*b^2/2
\begin{ex}
  Tính $\displaystyle\int_0^{{b}} {{a:c}}x\,dx$ (kết quả viết dạng số thập phân).
  \shortans{{{I:.1}}}
  \loigiai{$\displaystyle\int_0^{{b}} {{a:c}}x\,dx = \dfrac{ {{a}}\cdot {{b}}^2}{2} = {{I}}$.}
\end{ex}
"""


def one(src: str):
    pqs = parse_text(src)
    assert len(pqs) == 1
    return pqs[0]


def test_format_helpers():
    assert params.fmt(Fraction(3)) == "3"
    assert params.fmt(Fraction(-3, 4)) == "-\\dfrac{3}{4}"
    assert params.fmt(Fraction(-3), "+") == "- 3" and params.fmt(Fraction(2), "+") == "+ 2"
    assert params.fmt(Fraction(1), "c") == "" and params.fmt(Fraction(-1), "c") == "-"
    assert params.fmt(Fraction(-1), "c+") == "- " and params.fmt(Fraction(4), "c+") == "+ 4"
    assert params.fmt(Fraction(-2), "()") == "(-2)"
    assert params.fmt(2.345, ".1") == "2{,}3" and params.fmt(Fraction(5, 2), ".1") == "2{,}5"
    assert params.render("x^2 {{b:c+}}x {{c:+}}", {"b": Fraction(-1), "c": Fraction(-7)}) == "x^2 - x - 7"


def test_spec_parsing_and_exact_values():
    spec = params.parse_spec("% @thamso: a = 1..5; k = 2..10 buoc 4; r = {1/2, 3}\n% @tinh: s = sqrt(a^2 + 9)")
    assert dict(spec.params)["k"] == [2, 6, 10] and dict(spec.params)["r"] == [Fraction(1, 2), 3]
    env = {"a": Fraction(4)}
    assert params.evaluate("sqrt(a^2 + 9)", env) == 5 and isinstance(params.evaluate("sqrt(a^2 + 9)", env), Fraction)
    assert params.evaluate("a/3", env) == Fraction(4, 3)
    with pytest.raises(params.ParamError):
        params.parse_spec("% @thamso: a = 5..1")
    with pytest.raises(params.ParamError):
        params.evaluate("__import__('os')", {})


def test_template_is_checked_when_parsed():
    pq = one(DOT)
    assert pq.ok, pq.errors
    assert pq.params.startswith("% @thamso: a = 1..6")
    rep = params.check(pq.type, pq.params, pq.stem, [(c.content, c.is_correct, c.pinned) for c in pq.choices],
                       pq.short_answer, pq.solution, rng=random.Random(1))
    assert rep.ok and rep.distinct >= 3 and len(rep.samples) == 3
    s = rep.samples[0]
    a, c = Fraction(s.values["a"]), Fraction(s.values["c"])
    assert s.choices[0][0] == f"${2 * a + c}$" and s.choices[0][1]
    assert "{{" not in s.stem and "{{" not in s.solution

    short = one(SHORT)
    assert short.ok, short.errors
    inst = params.instantiate(QuestionType.SHORT, short.params, short.stem, [], short.short_answer, short.solution,
                              random.Random(3))
    a, b = Fraction(inst.values["a"]), Fraction(inst.values["b"])
    assert float(inst.short_answer.replace(",", ".")) == pytest.approx(float(a * b * b / 2))


def test_bad_templates_are_rejected():
    narrow = DOT.replace("a = 1..6; b = -5..5; c = -4..4", "a = 1..1; b = 1..1; c = 1..2")
    assert any("bộ số khác nhau" in e for e in one(narrow).errors)
    unknown = DOT.replace("{{d + 1}}", "{{z + 1}}")
    assert any("chưa khai báo z" in e for e in one(unknown).errors)
    # phương án luôn trùng nhau: không có bộ số nào hợp lệ
    clash = DOT.replace("{{d + 1}}", "{{d}}")
    assert any("không bốc được" in e for e in one(clash).errors)


@pytest.fixture
def client(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    with TestClient(app) as c:
        login_admin(c)
        yield c
    app.state.engine.dispose()


def test_exam_and_practice_draw_new_numbers(client):
    c = client
    q = c.post("/api/questions", json={"source": DOT, "status": "approved"}).json()
    assert q["params"] and "{{a}}" in q["stem"]
    assert "% @thamso: a = 1..6" in c.get(f"/api/questions/{q['code']}").json()["ex_source"]
    parsed = c.post("/api/parse", json={"source": DOT}).json()[0]
    assert parsed["param_report"]["ok"] and len(parsed["param_report"]["samples"]) == 3

    spec = {"title": "Đề tham số", "variants": 4, "vary": True, "sections": [{"type": "mcq", "ids": [q["code"]]}]}
    exam = c.post("/api/exams", json=spec).json()
    stems = set()
    for v in exam["variants"]:
        item = v["data"]["sections"][0]["questions"][0]
        a, cc = Fraction(item["values"]["a"]), Fraction(item["values"]["c"])
        right = next(ch for ch in item["choices"] if ch["correct"])
        assert right["content"] == f"${2 * a + cc}$"  # đáp án tính lại đúng theo bộ số của mã đề
        stems.add(item["stem"])
    assert len(stems) > 1  # các mã đề khác số liệu

    c.put(f"/api/exams/{exam['id']}/published", json={"published": True})
    seen = set()
    for _ in range(4):
        a = c.post("/api/attempts", json={"exam_id": exam["id"]}).json()
        seen.add(a["data"]["sections"][0]["questions"][0]["stem"])
    assert len(seen) > 1  # mỗi lượt luyện bốc số mới


def test_bank_list_shows_sample_and_variants_skip_params(client):
    c = client
    q = c.post("/api/questions", json={"source": DOT, "status": "approved"}).json()
    item = next(x for x in c.get("/api/questions").json()["items"] if x["code"] == q["code"])
    assert item["sample"] and "{{" not in item["sample"]["stem"]
    full = c.get(f"/api/questions/{q['code']}").json()
    assert full["sample"]["choices"] and "{{" not in full["sample"]["solution"]
    plan = c.post("/api/gen/variants/plan", json={"codes": [q["code"]]}).json()
    assert not plan["sources"] and "câu tham số" in plan["skipped"][0]["reason"]
