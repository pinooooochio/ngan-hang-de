from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import login_admin
from nganhangde import figures
from nganhangde.api import create_app

EXAMPLES = Path(__file__).parent.parent / "examples"
needs_tools = pytest.mark.skipif(not figures.available(), reason="chưa cài xelatex/pdftocairo")

GRAPH = r"""\begin{tikzpicture}
  \begin{axis}[axis lines=middle, xlabel=$x$, ylabel=$y$, width=6cm]
    \addplot[domain=-2:2, smooth, thick] {x^3-3*x};
  \end{axis}
\end{tikzpicture}"""

TABLE = r"""\begin{tikzpicture}
  \tkzTabInit{$x$ / 1, $y'$ / 1, $y$ / 2}{$-\infty$, $-1$, $1$, $+\infty$}
  \tkzTabLine{, +, 0, -, 0, +, }
  \tkzTabVar{-/ $-\infty$, +/ $2$, -/ $-2$, +/ $+\infty$}
\end{tikzpicture}"""

BROKEN = r"""\begin{tikzpicture}
  \draw (0,0) -- (1,1) \lenhkhongco;
\end{tikzpicture}"""

PARAMS = {"grade": "Lớp 12", "topic": "Ứng dụng đạo hàm để khảo sát và vẽ đồ thị hàm số", "level": "TH",
          "type": "tf", "count": 2, "figure": True}

OUTPUT = rf"""% @tags: Lớp 12 / Ứng dụng đạo hàm để khảo sát và vẽ đồ thị hàm số ; @level: TH
\begin{{ex}}
  Cho hàm số $y=x^3-3x$ có đồ thị như hình vẽ.
  \begin{{center}}
  {GRAPH}
  \end{{center}}
  \choiceTF{{\True Hàm số đạt cực đại tại $x=-1$}}{{Hàm số đồng biến trên $(-1;1)$}}{{\True Giá trị cực tiểu bằng $-2$}}{{Phương trình $y=1$ có 2 nghiệm}}
  \loigiai{{$y'=3x^2-3$.}}
\end{{ex}}

% @tags: Lớp 12 / Ứng dụng đạo hàm để khảo sát và vẽ đồ thị hàm số ; @level: TH
\begin{{ex}}
  Cho hình vẽ lỗi.
  {BROKEN}
  \choiceTF{{\True a}}{{b}}{{\True c}}{{d}}
  \loigiai{{Lời giải.}}
\end{{ex}}

% @tags: Lớp 12 / Ứng dụng đạo hàm để khảo sát và vẽ đồ thị hàm số ; @level: TH
\begin{{ex}}
  Câu không có hình, hàm số $y=x^2$.
  \choiceTF{{\True a}}{{b}}{{\True c}}{{d}}
  \loigiai{{Lời giải.}}
\end{{ex}}
"""


@pytest.fixture
def app(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    with TestClient(app) as c:
        login_admin(c)
        app.state.client = c
        yield app
    app.state.engine.dispose()


def test_find_figures():
    text = f"Đề {GRAPH} và $x$ {TABLE}"
    assert figures.find_figures(text) == [GRAPH, TABLE]
    assert figures.figure_id(GRAPH) == figures.figure_id("  " + GRAPH + "\n")
    assert figures.figure_id(GRAPH) != figures.figure_id(TABLE)


@needs_tools
def test_render_and_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path))
    for code in (GRAPH, TABLE):
        f = figures.render(code)
        assert f.ok, f.error
        assert figures.svg_path(f.id).read_text().lstrip().startswith("<?xml")
    bad = figures.render(BROKEN)
    assert not bad.ok and "lenhkhongco" in bad.error
    assert figures.cached(bad.id) == bad  # lỗi cũng được lưu, không biên dịch lại
    assert not figures.render(r"\input{/etc/passwd}").ok
    assert figures.check_text(f"{GRAPH} {BROKEN}") == [f"hình 2 không biên dịch được: {bad.error}"]


@needs_tools
def test_figure_api_and_permissions(app):
    c = app.state.client
    r = c.post("/api/figures", json={"code": GRAPH})
    assert r.status_code == 200 and r.json()["ok"], r.text
    svg = c.get(f"/api/figures/{r.json()['id']}.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert c.get("/api/figures/" + "0" * 32 + ".svg").status_code == 404
    assert c.get("/api/figures/..%2Fx.svg").status_code == 404

    # Học viên: hình đã có sẵn thì xem được, không được nhờ máy chủ biên dịch mã tuỳ ý
    assert c.post("/api/users", json={"username": "hocvien", "password": "matkhau-hocvien", "role": "student"}).status_code == 201
    hv = TestClient(app)
    hv.post("/api/auth/login", json={"username": "hocvien", "password": "matkhau-hocvien"})
    assert hv.post("/api/figures", json={"code": GRAPH}).json()["ok"]
    assert hv.post("/api/figures", json={"code": TABLE}).status_code == 403
    q = f"% @tags: Lớp 12 / Hàm số ; @level: NB\n\\begin{{ex}}\n  Bảng biến thiên\n  {TABLE}\n  \\shortans{{2}}\n\\end{{ex}}\n"
    assert c.post("/api/questions", json={"source": q}).status_code == 201
    assert hv.post("/api/figures", json={"code": TABLE}).json()["ok"]


def test_prompt_figure_option(app):
    c = app.state.client
    r = c.post("/api/gen/prompt", json=PARAMS).json()
    assert "tkz-tab" in r["system"] and "Câu đúng/sai có hình" in r["system"]
    assert "MỖI câu phải có hình vẽ" in r["user"]
    plain = c.post("/api/gen/prompt", json={**PARAMS, "figure": False}).json()
    assert plain["system"] == r["system"] and "chỉ vẽ khi đề bài thật sự cần" in plain["user"]


@needs_tools
def test_generated_figures_checked(app):
    c = app.state.client
    items = c.post("/api/gen/check", json={"params": PARAMS, "output": OUTPUT}).json()
    assert [it["state"] for it in items] == ["new", "new", "new"]
    assert items[0]["figure_errors"] == []
    assert "lenhkhongco" in items[1]["figure_errors"][0]
    assert any("chưa có hình vẽ" in w for w in items[2]["warnings"])
    # Câu có hình lỗi vẫn vào nháp để sửa
    b = c.post("/api/gen/batches", json={"params": PARAMS, "mode": "manual", "output": OUTPUT}).json()
    assert b["n_added"] == 3 and b["items"][1]["figure_errors"]
