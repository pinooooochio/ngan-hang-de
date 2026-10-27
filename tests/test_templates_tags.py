from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import login_admin
from nganhangde.api import create_app

EXAMPLES = Path(__file__).parent.parent / "examples"

TEMPLATE = {
    "name": "Giữa kỳ Giải tích 1",
    "description": "Chương 1 và 2",
    "duration": 60,
    "variants": 4,
    "sections": [
        {
            "name": "PHẦN I",
            "type": "mcq",
            "points": 0.25,
            "pick": [{"tag": "lop-12", "level": "NB", "count": 2}],
            "ids": ["12V-001"],
        },
        {"name": "PHẦN II", "type": "tf", "pick": [{"tag": "lop-12", "count": 1}]},
    ],
}


@pytest.fixture
def client(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    with TestClient(app) as c:
        login_admin(c)
        source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
        assert c.post("/api/import/commit", json={"source": source}).status_code == 200
        yield c
    app.state.engine.dispose()


def test_template_crud(client):
    c = client
    r = c.post("/api/exam-templates", json=TEMPLATE)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["name"] == "Giữa kỳ Giải tích 1" and t["duration"] == 60 and t["variants"] == 4
    assert t["n_questions"] == 3
    sec = t["sections"][0]
    assert "ids" not in sec and sec["pick"] == [{"tag": "lop-12", "level": "NB", "count": 2}]  # bỏ câu chọn tay, dòng trống

    assert c.post("/api/exam-templates", json=TEMPLATE).status_code == 409  # trùng tên
    edited = {**TEMPLATE, "name": "Giữa kỳ GT1", "sections": TEMPLATE["sections"][1:]}
    r = c.put(f"/api/exam-templates/{t['id']}", json=edited).json()
    assert r["name"] == "Giữa kỳ GT1" and len(r["sections"]) == 1
    assert [x["name"] for x in c.get("/api/exam-templates").json()] == ["Giữa kỳ GT1"]

    # Khung dùng lại được để tạo đề
    exam = {"title": "Đề từ khung", "variants": 1, "sections": r["sections"]}
    assert c.post("/api/exams", json=exam).status_code == 201

    assert c.delete(f"/api/exam-templates/{t['id']}").status_code == 204
    assert c.get("/api/exam-templates").json() == []
    assert c.put(f"/api/exam-templates/{t['id']}", json=edited).status_code == 404


def test_move_tag_and_old_curriculum_rules(client):
    c = client
    c.post("/api/questions/bulk", json={"codes": ["12V-001", "12V-002"], "set_tag": "Đại học / Giải tích / Tích phân"})
    c.post("/api/questions/bulk", json={"codes": ["12V-005"], "set_tag": "Đại học / Giải tích / Cực trị"})
    c.post("/api/questions/bulk", json={"codes": ["12V-006"], "set_tag": "Đại học / Xác suất thống kê / Biến ngẫu nhiên"})
    q = c.get("/api/questions/12V-001").json()
    assert [t["names"] for t in q["tags"]] == [["Đại học", "Giải tích", "Tích phân"]]

    moves = {m["from"]: m for m in c.get("/api/tags/moves").json()}
    assert moves["Đại học / Giải tích / Tích phân"]["count"] == 2
    assert moves["Đại học / Giải tích"]["count"] == 3
    assert list(moves).index("Đại học / Giải tích / Tích phân") < list(moves).index("Đại học / Giải tích")

    assert c.post("/api/tags/moves/apply").json()["moved"] == 4
    tags = {t["path"] for t in c.get("/api/tags").json()}
    assert not any(p.startswith("dai-hoc") for p in tags)  # nút cũ đã trống thì bị xoá
    q1 = c.get("/api/questions/12V-001").json()
    assert [t["names"] for t in q1["tags"]] == [["Giải tích 1", "Chương 2. Phép tính tích phân một biến số"]]
    assert [t["names"] for t in c.get("/api/questions/12V-005").json()["tags"]] == [["Giải tích 1"]]
    assert c.get("/api/questions/12V-006").json()["tags"][0]["names"][0] == "Xác suất thống kê"

    # Chuyển tay một nhánh, giữ các thẻ khác của câu
    c.post("/api/questions/bulk", json={"codes": ["12V-001"], "add_tag": "Lớp 12 / Ôn tập"})
    r = c.post("/api/tags/move", json={"source": "giai-tich-1/chuong-2-phep-tinh-tich-phan-mot-bien-so",
                                      "target": "Giải tích 1 / Chương 2. Phép tính tích phân một biến số / Tích phân xác định"})
    assert r.json() == {"moved": 2}
    names = sorted(" / ".join(t["names"]) for t in c.get("/api/questions/12V-001").json()["tags"])
    assert names == ["Giải tích 1 / Chương 2. Phép tính tích phân một biến số / Tích phân xác định", "Lớp 12 / Ôn tập"]
    bad = c.post("/api/tags/move", json={"source": "Giải tích 1", "target": "giai tich 1"})
    assert bad.status_code == 422


def test_bulk_delete_keeps_questions_in_exams(client):
    c = client
    exam = {"title": "Đề", "variants": 1, "sections": [{"type": "essay", "ids": ["12V-015"]}]}
    assert c.post("/api/exams", json=exam).status_code == 201
    r = c.post("/api/questions/bulk-delete", json={"codes": ["12V-001", "12V-015"]}).json()
    assert r == {"deleted": 1, "kept": ["12V-015"]}
    assert c.get("/api/questions/12V-001").status_code == 404
