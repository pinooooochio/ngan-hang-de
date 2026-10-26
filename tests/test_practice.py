from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nganhangde.api import create_app
from nganhangde.practice import grade_question, public_data, short_matches

EXAMPLES = Path(__file__).parent.parent / "examples"

EXAM = {
    "title": "Kiểm tra Vectơ",
    "duration": 45,
    "variants": 2,
    "seed": 7,
    "sections": [
        {"name": "PHẦN I", "type": "mcq", "points": 0.25, "pick": [{"tag": "lop-12", "count": 4}]},
        {"name": "PHẦN II", "type": "tf", "pick": [{"count": 1}]},
        {"name": "PHẦN III", "type": "short", "pick": [{"count": 2}]},
        {"name": "PHẦN IV", "type": "essay", "ids": ["12V-015"]},
    ],
}


@pytest.fixture
def client(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    with TestClient(app) as c:
        source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
        assert c.post("/api/import/commit", json={"source": source, "status": "approved"}).status_code == 200
        yield c
    app.state.engine.dispose()


def mcq(right: int) -> dict:
    return {"type": "mcq", "choices": [{"content": "x", "correct": i == right} for i in range(4)]}


def test_grade_rules():
    assert grade_question(mcq(2), 2, 0.25) == (0.25, True)
    assert grade_question(mcq(2), 1, 0.25) == (0.0, False)
    assert grade_question(mcq(2), None, 0.25) == (0.0, False)
    assert grade_question(mcq(0), False, 0.25) == (0.0, False)  # False không được hiểu là lựa chọn 0

    tf = {"type": "tf", "choices": [{"content": "", "correct": c} for c in (True, False, True, True)]}
    assert grade_question(tf, [True, False, True, True], 1) == (1.0, True)
    assert grade_question(tf, [True, False, True, False], 1) == (0.5, False)
    assert grade_question(tf, [True, False, None, None], 1) == (0.25, False)
    assert grade_question(tf, [True, None, None, None], 1) == (0.1, False)
    assert grade_question(tf, None, 1) == (0.0, False)

    assert short_matches("1,5", "1.5") and short_matches(" -2 ", "-2") and short_matches("0.50", "0,5")
    assert not short_matches("", "0") and not short_matches("3", "5")
    assert short_matches("x = 2", "x=2")
    assert grade_question({"type": "essay"}, "bài làm", 1) == (0.0, None)


def test_public_data_hides_answers():
    data = {"sections": [{"type": "mcq", "questions": [{**mcq(1), "short_answer": None, "solution": "chọn B"}]}]}
    pub = public_data(data)
    q = pub["sections"][0]["questions"][0]
    assert all("correct" not in c for c in q["choices"]) and q["solution"] == ""
    assert data["sections"][0]["questions"][0]["choices"][1]["correct"]  # bản gốc không đổi


def test_exam_attempt_flow(client):
    exam = client.post("/api/exams", json=EXAM).json()
    r = client.post("/api/attempts", json={"exam_id": exam["id"], "variant": "102"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["variant_code"] == "102" and a["duration"] == 45 and a["deadline"] and a["submitted_at"] is None
    assert a["n_questions"] == 8 and a["results"] is None
    q0 = a["data"]["sections"][0]["questions"][0]
    assert "correct" not in q0["choices"][0] and q0["solution"] == ""

    # Đáp án đúng lấy từ bảng đáp án của mã 102
    key = next(v for v in exam["variants"] if v["code"] == "102")["answer_key"]["sections"]
    answers = {f"0.{i}": "ABCD".index(k) for i, k in enumerate(key[0])}
    answers["0.0"] = ("ABCD".index(key[0][0]) + 1) % 4  # cố ý sai câu 1
    answers["1.0"] = [c == "Đ" for c in key[1][0]]
    answers["2.0"] = key[2][0].replace(".", ",")
    answers["2.1"] = "khong biet"
    answers["3.0"] = "bài tự luận"

    assert client.put(f"/api/attempts/{a['id']}/answers", json={"answers": {"0.1": 0}}).status_code == 204
    assert client.get(f"/api/attempts/{a['id']}").json()["answers"] == {"0.1": 0}

    done = client.post(f"/api/attempts/{a['id']}/submit", json={"answers": answers}).json()
    assert done["score"] == pytest.approx(0.75 + 1 + 0.5) and done["max_score"] == pytest.approx(1 + 1 + 1)
    assert done["results"]["0.0"]["correct"] is False and done["results"]["3.0"]["correct"] is None
    assert done["data"]["sections"][0]["questions"][0]["solution"]  # sau khi nộp thì thấy lời giải
    assert not done["late"]

    assert client.post(f"/api/attempts/{a['id']}/submit", json={"answers": {}}).status_code == 409
    assert client.put(f"/api/attempts/{a['id']}/answers", json={"answers": {}}).status_code == 409

    stats = client.get("/api/attempts/stats").json()
    assert stats["attempts"] == 1
    lop12 = next(t for t in stats["by_tag"] if t["path"] == "lop-12")
    assert lop12["names"] == ["Lớp 12"] and lop12["n"] == 7 and lop12["ratio"] == pytest.approx(2.25 / 3)
    assert sum(b["n"] for b in stats["by_level"].values()) == 7

    # Luyện lại câu sai: câu 1 trắc nghiệm và câu trả lời ngắn thứ hai
    retry = client.post("/api/attempts", json={"retry_of": a["id"]}).json()
    assert retry["kind"] == "quick" and retry["n_questions"] == 2

    # Xoá đề vẫn giữ lượt luyện
    assert client.delete(f"/api/exams/{exam['id']}").status_code == 204
    kept = client.get(f"/api/attempts/{a['id']}").json()
    assert kept["exam_id"] is None and kept["score"] == done["score"]
    assert len(client.get("/api/attempts").json()) == 2


def test_quick_practice(client):
    r = client.post("/api/attempts", json={"quick": {"tag": "lop-12", "level": "NB", "mcq": 2, "short": 1, "duration": 10}})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "quick" and a["n_questions"] == 3 and a["duration"] == 10
    assert [s["type"] for s in a["data"]["sections"]] == ["mcq", "short"]
    done = client.post(f"/api/attempts/{a['id']}/submit").json()
    assert done["score"] == 0 and done["max_score"] == pytest.approx(1.0)

    bad = client.post("/api/attempts", json={"quick": {"level": "VDC", "mcq": 1}})
    assert bad.status_code == 422 and "VDC" in bad.json()["detail"]
    assert client.post("/api/attempts", json={"quick": {}}).status_code == 422
    assert client.post("/api/attempts", json={}).status_code == 422
    assert client.delete(f"/api/attempts/{a['id']}").status_code == 204
    assert client.get(f"/api/attempts/{a['id']}").status_code == 404
