from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import login_admin
from nganhangde.api import create_app
from nganhangde.compile import latex_available

EXAMPLES = Path(__file__).parent.parent / "examples"

ONE = r"""% @tags: Lớp 10 / Lượng giác ; @level: NB ; @id: LG-1
\begin{ex}
  Giá trị $\sin 30^\circ$ bằng
  \choice{\True $\dfrac12$}{$1$}{$0$}{$\dfrac{\sqrt3}2$}
  \loigiai{$\sin 30^\circ=\dfrac12$.}
\end{ex}
"""


@pytest.fixture
def client(db_url):
    app = create_app(db_url)
    with TestClient(app) as c:
        login_admin(c)
        yield c
    app.state.engine.dispose()


def test_create_get_update_delete(client):
    r = client.post("/api/questions", json={"source": ONE})
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["code"] == "LG-1" and q["status"] == "draft"
    assert q["tags"][0]["names"] == ["Lớp 10", "Lượng giác"]

    # Nội dung xuất ra định dạng soạn có thể sửa và lưu lại
    source = client.get("/api/questions/LG-1").json()["ex_source"]
    assert "\\True" in source and "@id: LG-1" in source
    r = client.put("/api/questions/LG-1", json={"source": source.replace("@level: NB", "@level: TH"), "status": "approved"})
    assert r.status_code == 200, r.text
    assert r.json()["level"] == "TH" and r.json()["status"] == "approved" and r.json()["version"] == 2

    # Lưu lại y nguyên nhiều lần không làm đổi nội dung
    again = client.get("/api/questions/LG-1").json()["ex_source"]
    client.put("/api/questions/LG-1", json={"source": again})
    assert client.get("/api/questions/LG-1").json()["ex_source"] == again

    assert client.delete("/api/questions/LG-1").status_code == 204
    assert client.get("/api/questions/LG-1").status_code == 404


def test_create_rejects_invalid_and_duplicate(client):
    bad = ONE.replace("{\\True $\\dfrac12$}", "{$\\dfrac12$}")
    assert client.post("/api/questions", json={"source": bad}).status_code == 422
    assert client.post("/api/questions", json={"source": ONE}).status_code == 201
    r = client.post("/api/questions", json={"source": ONE.replace("@id: LG-1", "@id: LG-2")})
    assert r.status_code == 422 and "trùng" in r.json()["detail"]


def test_import_preview_commit_and_filters(client):
    text = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
    preview = client.post("/api/import/preview", json={"source": text + ONE + ONE.replace("LG-1", "LG-9")}).json()
    states = [p["state"] for p in preview]
    assert states.count("new") == 16
    assert states[-1] == "duplicate"  # trùng với câu ngay trước trong cùng file

    r = client.post(
        "/api/import/commit",
        json={"source": text, "only": [0, 1, 2], "extra_tag": "Đề mẫu", "default_level": "VD"},
    ).json()
    assert len(r["added"]) == 3

    tags = {t["path"]: t["count"] for t in client.get("/api/tags").json()}
    assert tags["de-mau"] == 3
    assert client.get("/api/questions", params={"tag": "lop-12", "level": "NB"}).json()["total"] == 3
    assert client.get("/api/questions", params={"q": "trung điểm"}).json()["total"] == 1


def test_bulk_update(client):
    client.post("/api/questions", json={"source": ONE})
    r = client.post("/api/questions/bulk", json={"codes": ["LG-1"], "add_tag": "Ôn thi / Học kỳ 1", "status": "approved"})
    assert r.json()["updated"] == 1
    q = client.get("/api/questions/LG-1").json()
    assert q["status"] == "approved"
    assert ["Ôn thi", "Học kỳ 1"] in [t["names"] for t in q["tags"]]


@pytest.mark.skipif(not latex_available(), reason="chưa cài latexmk/xelatex")
def test_preview_pdf(client):
    r = client.post("/api/preview/pdf", json={"source": ONE})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    r = client.post("/api/preview/pdf", json={"source": ONE.replace("\\dfrac12$}{", "\\lenhsai$}{")})
    assert r.status_code == 422 and "LaTeX" in r.json()["detail"]
