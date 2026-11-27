from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import login_admin
from nganhangde import theory
from nganhangde.api import create_app

EXAMPLES = Path(__file__).parent.parent / "examples"
PATH = "lop-11/goc-trong-khong-gian"

LESSON = r"""
\begin{dinhnghia}[Góc giữa hai mặt phẳng]
  Góc giữa hai mặt phẳng là góc giữa hai đường thẳng lần lượt vuông góc với hai mặt phẳng đó.
\end{dinhnghia}

% @dang: Góc nhị diện
\begin{phuongphap}
  Bước 1: xác định cạnh của góc nhị diện.
\end{phuongphap}
\begin{vidu}[Hình chóp đều]
  Tính số đo góc nhị diện $[S, BC, A]$.
  \begin{loigiai}
    Gọi $M$ là trung điểm $BC$ ...
  \end{loigiai}
\end{vidu}
"""

FOREIGN = r"""\documentclass{article}
\usepackage{amsmath}
\newtheorem{definition}{Định nghĩa}
\begin{document}
% @chude: Lớp 11 / Góc trong không gian
\section{Kiến thức cần nhớ}
Phần này nhắc lại các khái niệm.
\begin{definition}[Góc nhị diện $[P, d, Q]$]
  Hình gồm hai nửa mặt phẳng chung bờ.
  \begin{itemize}
    \item \begin{remark} lồng trong danh sách, giữ nguyên \end{remark}
  \end{itemize}
\end{definition}
\subsection{Dạng 4. Góc nhị diện}
\begin{example}
  Ví dụ một.
\end{example}
\cauhoi{Q-KHONG-CO}

% @chude: Lớp 10 / Vectơ
\begin{note}Hai vectơ bằng nhau khi cùng hướng và cùng độ dài.\end{note}
\end{document}
"""


def test_parse_lesson_and_round_trip():
    topic = theory.find_topic(PATH)
    r = theory.parse(LESSON, topic)
    assert not r.errors
    blocks = r.sections[0].blocks
    assert [(b.kind, b.dang) for b in blocks] == [
        ("dinhnghia", None), ("phuongphap", "Góc nhị diện"), ("vidu", "Góc nhị diện")]
    assert blocks[0].title == "Góc giữa hai mặt phẳng"
    assert blocks[2].content.startswith("Tính số đo") and "\\begin{loigiai}" in blocks[2].content
    again = theory.parse(theory.to_source(blocks), topic).sections[0].blocks
    assert [b.key() for b in again] == [b.key() for b in blocks]


def test_parse_foreign_file():
    r = theory.parse(FOREIGN)
    assert not r.errors
    a, b = r.sections
    assert a.topic["path"] == PATH and b.topic["path"] == "lop-10/vecto"
    assert [x.kind for x in a.blocks] == ["doan", "dinhnghia", "vidu", "vidu"]
    assert a.blocks[1].title == "Góc nhị diện $[P, d, Q]$"
    assert "\\begin{remark}" in a.blocks[1].content  # khối lồng trong danh sách không bị tách
    assert a.blocks[2].dang == "Góc nhị diện" and a.blocks[3].ref == "Q-KHONG-CO"
    assert b.blocks[0].kind == "luuy" and b.blocks[0].dang is None


def test_parse_errors():
    r = theory.parse("\\begin{dinhly} x \\end{dinhly}")
    assert "chưa có dòng % @chude" in r.errors[0][1]
    r = theory.parse("% @chude: Lớp 11 / Không có\n")
    assert "không có chủ đề" in r.errors[0][1]
    r = theory.parse("% @dang: Không có\n\\begin{dinhly}\nx\n", theory.find_topic(PATH))
    assert "không có dạng" in r.errors[0][1] and "thiếu \\end{dinhly}" in r.errors[1][1]
    assert r.errors[1][0] == 2


@pytest.fixture
def app(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    yield app
    app.state.engine.dispose()


def user(admin, app, name, role):
    assert admin.post("/api/users", json={"username": name, "password": "matkhau-" + name, "role": role}).status_code == 201
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": name, "password": "matkhau-" + name}).status_code == 200
    return c


def test_theory_api(app):
    admin = TestClient(app)
    login_admin(admin)
    source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
    assert admin.post("/api/import/commit", json={"source": source, "status": "approved"}).status_code == 200
    code = admin.get("/api/questions").json()["items"][0]["code"]
    ed = user(admin, app, "ban-soan", "editor")
    hv = user(admin, app, "hoc-vien", "student")

    # soạn đề lưu được nhưng không tự duyệt
    assert ed.put("/api/theory/topic", json={"path": PATH, "source": LESSON, "approve": True}).status_code == 403
    r = ed.put("/api/theory/topic", json={"path": PATH, "source": LESSON + f"\n\\cauhoi{{{code}}}\n"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["added"] == 4 and all(b["status"] == "draft" for b in data["blocks"])
    assert data["blocks"][3]["question"]["code"] == code
    assert hv.get(f"/api/theory/topic?path={PATH}").json()["blocks"] == []
    assert PATH not in str(hv.get("/api/theory/topics").json())

    # admin duyệt; học viên thấy, không thấy mã nguồn và nhật ký
    assert ed.post("/api/theory/topic/approve", json={"path": PATH}).status_code == 403
    assert admin.post("/api/theory/topic/approve", json={"path": PATH}).json()["approved"] == 4
    seen = hv.get(f"/api/theory/topic?path={PATH}").json()
    assert len(seen["blocks"]) == 4 and "source" not in seen and "logs" not in seen
    assert hv.put("/api/theory/topic", json={"path": PATH, "source": ""}).status_code == 403
    topics = hv.get("/api/theory/topics").json()["grades"]
    assert any(t["path"] == PATH and t["approved"] == 4 for g in topics for t in g["topics"])

    # sửa một khối: khối khác giữ mã và trạng thái đã duyệt, khối sửa vào nháp
    src = admin.get(f"/api/theory/topic?path={PATH}").json()["source"]
    before = admin.get(f"/api/theory/topic?path={PATH}").json()["blocks"]
    r = ed.put("/api/theory/topic", json={"path": PATH, "source": src.replace("Bước 1", "Bước một")}).json()
    assert (r["added"], r["kept"], r["removed"]) == (1, 3, 1)
    assert [b["status"] for b in r["blocks"]] == ["approved", "draft", "approved", "approved"]
    assert r["blocks"][0]["code"] == before[0]["code"] and r["blocks"][1]["code"] != before[1]["code"]
    assert len(hv.get(f"/api/theory/topic?path={PATH}").json()["blocks"]) == 3
    log = r["logs"][0]
    assert log["action"] == "sua" and log["username"] == "ban-soan"
    assert "Bước 1" in admin.get(f"/api/theory/logs/{log['id']}").json()["before"]

    # trang soạn chủ đề không nhận chủ đề khác; lỗi trả dòng
    bad = ed.put("/api/theory/topic", json={"path": PATH, "source": "% @chude: Lớp 10 / Vectơ\nabc"})
    assert bad.status_code == 422 and "Import" in bad.json()["detail"]
    bad = ed.put("/api/theory/topic", json={"path": PATH, "source": "\n\\begin{dinhly}"})
    assert bad.status_code == 422 and bad.json()["detail"].startswith("dòng 2")

    # import nhiều chủ đề: xem trước rồi thêm vào cuối
    pv = ed.post("/api/theory/import/preview", json={"source": FOREIGN}).json()
    assert [s["topic"]["path"] for s in pv["sections"]] == [PATH, "lop-10/vecto"]
    assert pv["sections"][0]["existing"] == 4
    assert any("Q-KHONG-CO" in w["message"] for w in pv["warnings"])
    r = ed.post("/api/theory/import/commit", json={"source": FOREIGN, "filename": "goc.tex", "approve": True})
    assert r.status_code == 403
    r = ed.post("/api/theory/import/commit", json={"source": FOREIGN, "filename": "goc.tex", "only": [PATH]}).json()
    assert r["topics"] == [{"path": PATH, "ten": "Góc trong không gian", "added": 4, "kept": 0, "removed": 0}]
    blocks = admin.get(f"/api/theory/topic?path={PATH}").json()["blocks"]
    assert len(blocks) == 8 and blocks[-1]["source"] == "goc.tex"
    assert admin.get("/api/theory/topic?path=lop-10/vecto").json()["blocks"] == []

    # import thay thế cả chủ đề
    r = admin.post("/api/theory/import/commit",
                   json={"source": FOREIGN, "mode": "replace", "approve": True}).json()
    assert [(t["kept"], t["removed"]) for t in r["topics"]] == [(4, 4), (0, 0)]
    assert len(hv.get(f"/api/theory/topic?path={PATH}").json()["blocks"]) == 3  # câu không có trong ngân hàng bị ẩn
