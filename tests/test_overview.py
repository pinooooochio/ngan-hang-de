from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import login_admin
from nganhangde.api import create_app

EXAMPLES = Path(__file__).parent.parent / "examples"
PATH = "lop-12/vecto-trong-khong-gian"


@pytest.fixture
def app(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    yield app
    app.state.engine.dispose()


def test_overview(app):
    admin = TestClient(app)
    login_admin(admin)
    source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
    assert admin.post("/api/import/commit", json={"source": source, "status": "approved"}).status_code == 200
    # một câu chuyển về nháp
    code = admin.get("/api/questions").json()["items"][0]["code"]
    assert admin.post("/api/questions/bulk", json={"codes": [code], "status": "draft"}).status_code in (200, 204)
    lesson = "\\begin{dinhnghia}Vectơ.\\end{dinhnghia}\n% @dang: Tích vô hướng\n\\begin{congthuc}$a.b$\\end{congthuc}\n"
    assert admin.put("/api/theory/topic", json={"path": PATH, "source": lesson, "approve": True}).status_code == 200

    r = admin.get("/api/overview")
    assert r.status_code == 200
    data = r.json()
    g12 = next(g for g in data["grades"] if g["slug"] == "lop-12")
    t = next(t for t in g12["topics"] if t["path"] == PATH)
    n = data["total"]["approved"] + data["total"]["draft"]
    # 14 câu gắn chủ đề, 1 câu chỉ suy ra được "Lớp 12"
    assert t["approved"] + t["draft"] == 14 and t["draft"] == 1
    assert g12["approved"] + g12["draft"] == n == 15 and data["other"] == 0
    assert sum(t["levels"].values()) == t["approved"]
    dang = {d["name"]: d for d in t["dang"]}
    assert dang["Tích vô hướng"]["approved"] + dang["Tích vô hướng"]["draft"] == 6
    assert dang["Tích vô hướng"]["theory"]["approved"] == 1 and dang["Vectơ và các phép toán"]["theory"]["approved"] == 0
    assert t["theory"] == {"approved": 2, "draft": 0}
    g10 = next(g for g in data["grades"] if g["slug"] == "lop-10")
    assert g10["approved"] == 0 and all(x["approved"] == 0 for x in g10["topics"])

    # học viên không xem được
    assert admin.post("/api/users", json={"username": "hoc-vien", "password": "matkhau-hocvien", "role": "student"}).status_code == 201
    hv = TestClient(app)
    hv.post("/api/auth/login", json={"username": "hoc-vien", "password": "matkhau-hocvien"})
    assert hv.get("/api/overview").status_code == 403
