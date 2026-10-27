from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from helpers import login_admin
from nganhangde import builds
from nganhangde.api import create_app
from nganhangde.compile import latex_available

EXAMPLES = Path(__file__).parent.parent / "examples"

needs_latex = pytest.mark.skipif(not latex_available(), reason="chưa cài latexmk/xelatex")

EXAM = {
    "title": "Kiểm tra Vectơ",
    "date": "2026-10-26",
    "duration": 45,
    "variants": 2,
    "seed": 7,
    "sections": [
        {
            "name": "PHẦN I",
            "type": "mcq",
            "points": 0.25,
            "pick": [{"tag": "lop-12", "level": "NB", "count": 2}, {"tag": "lop-12", "level": "VD", "count": 2}],
        },
        {"name": "PHẦN II", "type": "tf", "pick": [{"tag": "lop-12", "count": 1}]},
        {"name": "PHẦN IV", "type": "essay", "ids": ["12V-015"]},
    ],
}


@pytest.fixture
def app(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    with TestClient(app) as c:
        login_admin(c)
        source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
        assert c.post("/api/import/commit", json={"source": source}).status_code == 200
        app.state.client = c
        yield app
    app.state.engine.dispose()


def run_worker(app) -> int:
    with Session(app.state.engine) as s:
        return builds.run_pending(s)


def test_availability(app):
    c = app.state.client
    body = {
        "sections": [
            {"type": "mcq", "pick": [{"tag": "lop-12", "level": "NB"}, {"tag": "lop-12", "level": "VDC"}]},
            {"type": "essay", "ids": ["12V-015", "12V-001", "KHONG-CO"]},
        ]
    }
    r = c.post("/api/exams/availability", json=body).json()
    assert r["sections"][0]["rows"] == [3, 0]
    assert len(r["sections"][1]["problems"]) == 2


def test_create_exam_shortage_is_422(app):
    c = app.state.client
    bad = {**EXAM, "sections": [{"type": "mcq", "pick": [{"tag": "lop-12", "level": "VDC", "count": 1}]}]}
    r = c.post("/api/exams", json=bad)
    assert r.status_code == 422 and "VDC" in r.json()["detail"]
    assert c.get("/api/exams").json() == []


def test_create_exam_queues_builds(app):
    c = app.state.client
    r = c.post("/api/exams", json=EXAM)
    assert r.status_code == 201, r.text
    exam = r.json()
    assert exam["n_variants"] == 2 and exam["n_questions"] == 6
    assert [f["name"] for f in exam["files"]] == ["de-101", "loigiai-101", "de-102", "loigiai-102", "dapan"]
    assert all(f["status"] == "pending" for f in exam["files"])
    assert exam["config"]["seed"] == 7
    for v in exam["variants"]:
        assert len(v["answer_key"]["sections"][0]) == 4
    assert c.get("/api/exams").json()[0]["builds"]["pending"] == 5


@needs_latex
def test_build_download_cache_and_delete(app, tmp_path):
    c = app.state.client
    exam = c.post("/api/exams", json=EXAM).json()
    assert run_worker(app) == 5
    detail = c.get(f"/api/exams/{exam['id']}").json()
    assert all(f["status"] == "done" for f in detail["files"]), detail["files"]
    assert not any(f["cached"] for f in detail["files"])

    pdf = c.get(detail["files"][0]["url"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    z = c.get(f"/api/exams/{exam['id']}/files.zip")
    assert z.status_code == 200 and z.content.startswith(b"PK")

    # Biên dịch lại: nội dung không đổi nên dùng lại PDF đã có
    c.post(f"/api/exams/{exam['id']}/rebuild")
    run_worker(app)
    files = c.get(f"/api/exams/{exam['id']}").json()["files"]
    assert all(f["status"] == "done" and f["cached"] for f in files)

    assert c.delete(f"/api/exams/{exam['id']}").status_code == 204
    assert not (tmp_path / "files" / "exams" / str(exam["id"])).exists()


@needs_latex
def test_build_error_names_question(app):
    c = app.state.client
    bad = r"""% @tags: Lớp 12 ; @level: NB ; @id: HONG-1
\begin{ex} Câu hỏng $\lenhkhongco$. \choice{\True a}{b}{c}{d} \end{ex}"""
    c.post("/api/questions", json={"source": bad, "status": "approved"})
    exam = c.post(
        "/api/exams", json={"title": "Lỗi", "sections": [{"type": "mcq", "ids": ["HONG-1"]}]}
    ).json()
    run_worker(app)
    files = c.get(f"/api/exams/{exam['id']}").json()["files"]
    de = next(f for f in files if f["name"] == "de-101")
    assert de["status"] == "failed" and de["error_question"] == "HONG-1"
