import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from helpers import login_admin
from nganhangde import backup, builds
from nganhangde.api import create_app
from nganhangde.models import Build, BuildStatus

EXAMPLES = Path(__file__).parent.parent / "examples"

EXAM = {
    "title": "Kiểm tra Vectơ",
    "date": "2026-10-26",
    "variants": 2,
    "seed": 3,
    "sections": [{"name": "PHẦN I", "type": "mcq", "pick": [{"tag": "lop-12", "count": 4}]}],
}
TEMPLATE = {"name": "Giữa kỳ", "description": "", "duration": 45, "variants": 2, "sections": [{"name": "PHẦN I", "type": "mcq", "pick": [{"tag": "lop-12", "count": 2}]}]}

NEW_Q = r"""
\begin{ex} % @tags: Lớp 12 / Vectơ ; @level: NB
Câu mới sau khôi phục?
\choice{\True $1$}{$2$}{$3$}{$4$}
\end{ex}
"""


@pytest.fixture
def client(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    monkeypatch.setenv("NHD_BACKUPS", str(tmp_path / "backups"))
    app = create_app(db_url)
    with TestClient(app) as c:
        login_admin(c)
        source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
        assert c.post("/api/import/commit", json={"source": source}).status_code == 200
        exam = c.post("/api/exams", json=EXAM).json()
        assert c.post("/api/attempts", json={"exam_id": exam["id"], "variant": "101"}).status_code == 201
        assert c.post("/api/exam-templates", json=TEMPLATE).status_code == 201
        c.app = app
        yield c
    app.state.engine.dispose()


def fake_pdf(client) -> Path:
    """Giả một PDF đã biên dịch (không cần XeLaTeX)."""
    engine = client.app.state.engine
    with Session(engine) as s:
        b = s.scalars(select(Build).order_by(Build.id)).first()
        target = builds.files_dir() / "exams" / str(b.exam_id) / f"{b.name}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.5 gia")
        b.status, b.pdf_path = BuildStatus.DONE, str(target)
        s.commit()
        return target


def test_info_lists_tables(client):
    info = client.get("/api/backup/info").json()
    counts = {t["name"]: t["count"] for t in info["tables"]}
    assert counts["questions"] == 15 and counts["exams"] == 1 and counts["attempts"] == 1 and counts["exam_templates"] == 1
    assert info["backups"] == []


def test_backup_restore_roundtrip(client, tmp_path):
    pdf = fake_pdf(client)
    r = client.get("/api/backup/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    data = r.content
    before = backup.table_counts(client.app.state.engine)

    z = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["tables"] == before and manifest["files"] == 1

    # Làm hỏng dữ liệu: xoá đề, xoá câu, xoá PDF
    exam_id = client.get("/api/exams").json()[0]["id"]
    assert client.delete(f"/api/exams/{exam_id}").status_code == 204
    assert client.delete("/api/questions/12V-015").status_code == 204
    assert not pdf.exists()

    info = client.post("/api/backup/inspect", content=data).json()
    assert info["tables"]["questions"] == 15 and info["files"] == 1

    r = client.post("/api/backup/restore", content=data)
    assert r.status_code == 200, r.text
    assert r.json()["safety_backup"].startswith(backup.SAFETY_PREFIX)
    assert backup.table_counts(client.app.state.engine) == before
    assert pdf.read_bytes() == b"%PDF-1.5 gia"
    assert client.get(f"/api/exams/{exam_id}/files/de-101.pdf").status_code == 200
    assert client.get("/api/questions/12V-015").status_code == 200

    # Bản an toàn có dữ liệu trước khi khôi phục (đã mất đề)
    stored = client.get("/api/backup/info").json()["backups"]
    assert len(stored) == 1 and stored[0]["safety"]
    info = client.post(f"/api/backup/inspect?name={stored[0]['name']}").json()
    assert info["tables"]["exams"] == 0 and info["tables"]["questions"] == 14

    # Bộ đếm id đã chỉnh: thêm câu, đề, lượt luyện mới không trùng id
    assert client.post("/api/import/commit", json={"source": NEW_Q}).json()["added"]
    assert client.post("/api/exams", json=EXAM).status_code == 201
    assert client.post("/api/attempts", json={"exam_id": exam_id, "variant": "102"}).status_code == 201


def test_restore_into_other_database_and_files_dir(client, tmp_path, monkeypatch):
    """Chuyển sang máy khác: CSDL trống, thư mục file khác."""
    fake_pdf(client)
    data = client.get("/api/backup/download").content
    before = backup.table_counts(client.app.state.engine)

    monkeypatch.setenv("NHD_FILES", str(tmp_path / "may-moi" / "files"))
    other = create_app(f"sqlite:///{tmp_path / 'may-moi.db'}")
    with TestClient(other) as c:
        login_admin(c)
        r = c.post("/api/backup/restore", content=data).json()
        assert r["safety_backup"] is None  # CSDL trống thì không cần bản an toàn
        assert backup.table_counts(other.state.engine) == before
        exam_id = c.get("/api/exams").json()[0]["id"]
        pdf = c.get(f"/api/exams/{exam_id}/files/de-101.pdf")
        assert pdf.status_code == 200 and pdf.content == b"%PDF-1.5 gia"
    other.state.engine.dispose()


def test_backup_without_files(client):
    fake_pdf(client)
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/backup/download?files=false").content))
    assert not [n for n in z.namelist() if n.startswith("files/")]


def test_running_jobs_requeued(client):
    engine = client.app.state.engine
    with engine.begin() as conn:
        conn.execute(update(Build).values(status=BuildStatus.RUNNING))
    data = client.get("/api/backup/download").content
    client.post("/api/backup/restore", content=data)
    with Session(engine) as s:
        assert {b.status for b in s.scalars(select(Build))} == {BuildStatus.PENDING}


def test_bad_files_rejected(client):
    before = backup.table_counts(client.app.state.engine)
    assert client.post("/api/backup/restore", content=b"khong phai zip").status_code == 422
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "x")
    assert "manifest" in client.post("/api/backup/restore", content=buf.getvalue()).json()["detail"]
    # File bị cắt mất một bảng
    good = zipfile.ZipFile(io.BytesIO(client.get("/api/backup/download").content))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in good.namelist():
            if n != "data/questions.jsonl":
                z.writestr(n, good.read(n))
    r = client.post("/api/backup/restore", content=buf.getvalue())
    assert r.status_code == 422 and "questions" in r.json()["detail"]
    assert client.post("/api/backup/restore").status_code == 422
    assert backup.table_counts(client.app.state.engine) == before


def test_stored_backups(client):
    name = client.post("/api/backup/save").json()["name"]
    assert name.startswith(backup.PREFIX)
    assert client.get(f"/api/backup/stored/{name}").status_code == 200
    assert client.get("/api/backup/stored/..%2Fx.zip").status_code == 404
    assert client.post(f"/api/backup/restore?name={name}").status_code == 200
    assert client.delete(f"/api/backup/stored/{name}").status_code == 204
    assert [b for b in client.get("/api/backup/info").json()["backups"] if not b["safety"]] == []


def test_keep_rotation(client, monkeypatch):
    engine = client.app.state.engine
    names = []
    for i in range(4):
        monkeypatch.setattr(backup, "backup_name", lambda now=None, prefix=backup.PREFIX, i=i: f"{prefix}2026010{i}.zip")
        names.append(backup.save_backup(engine, keep=2).name)
    assert sorted(p.name for p in backup.backups_dir().glob("*.zip")) == names[2:]


def test_export_questions_tex_reimports(client, tmp_path):
    r = client.get("/api/export/questions.tex")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    other = create_app(f"sqlite:///{tmp_path / 'tex.db'}")
    with TestClient(other) as c:
        login_admin(c)
        res = c.post("/api/import/commit", json={"source": r.text}).json()
        assert len(res["added"]) == 15 and res["failed"] == 0
    other.state.engine.dispose()
