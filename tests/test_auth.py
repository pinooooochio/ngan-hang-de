import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from helpers import ADMIN, login_admin
from nganhangde import auth, backup, builds
from nganhangde.api import create_app
from nganhangde.models import Build, BuildStatus, User

EXAMPLES = Path(__file__).parent.parent / "examples"
EXAM = {
    "title": "Kiểm tra Vectơ",
    "variants": 1,
    "seed": 3,
    "sections": [{"name": "PHẦN I", "type": "mcq", "pick": [{"tag": "lop-12", "count": 4}]}],
}
Q = r"""% @tags: Lớp 10 / Lượng giác ; @level: NB ; @id: LG-9
\begin{ex}
  Giá trị $\sin 30^\circ$ bằng
  \choice{\True $\dfrac12$}{$1$}{$0$}{$2$}
\end{ex}
"""


@pytest.fixture
def app(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    monkeypatch.setenv("NHD_BACKUPS", str(tmp_path / "backups"))
    app = create_app(db_url)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def admin(app):
    with TestClient(app) as c:
        login_admin(c)
        source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
        assert c.post("/api/import/commit", json={"source": source}).status_code == 200
        yield c


def make_user(admin, app, username: str, role: str) -> TestClient:
    r = admin.post("/api/users", json={"username": username, "password": "matkhau-" + username, "role": role})
    assert r.status_code == 201, r.text
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": username, "password": "matkhau-" + username}).status_code == 200
    return c


def sample_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_api_needs_login(app):
    """Duyệt mọi API: chưa đăng nhập thì 401 (trừ nhóm /api/auth), để không API nào bị quên kiểm tra quyền."""
    c = TestClient(app)
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path.startswith("/api/auth/"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            r = c.request(method, sample_path(path), json={})
            assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
            checked += 1
    assert checked > 50


def test_setup_once_and_login_lock(app):
    c = TestClient(app)
    r = c.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["setup"] is True
    login_admin(c)
    assert c.get("/api/auth/me").json()["role"] == "admin"
    other = TestClient(app)
    assert other.get("/api/auth/me").json()["setup"] is False
    assert other.post("/api/auth/setup", json={"username": "ke-gian", "password": "123456"}).status_code == 409

    for _ in range(auth.MAX_FAILED):
        assert other.post("/api/auth/login", json={"username": "admin", "password": "sai-roi"}).status_code == 401
    r = other.post("/api/auth/login", json={"username": "admin", "password": ADMIN["password"]})
    assert r.status_code == 401 and "thử lại sau" in r.json()["detail"]
    # hết thời gian khoá thì đăng nhập lại được
    with Session(app.state.engine) as s:
        u = s.scalar(select(User))
        u.locked_until = datetime.now() - timedelta(seconds=1)
        s.commit()
    assert other.post("/api/auth/login", json={"username": "admin", "password": ADMIN["password"]}).status_code == 200

    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/questions").status_code == 401


def test_password_hash():
    h = auth.hash_password("bí mật")
    assert h.startswith("scrypt$") and "bí mật" not in h
    assert auth.verify_password("bí mật", h) and not auth.verify_password("bi mat", h)


def test_editor_rights(admin, app):
    ed = make_user(admin, app, "ban-soan", "editor")
    # soạn câu được nhưng luôn vào nháp, không tự duyệt
    assert ed.post("/api/questions", json={"source": Q, "status": "approved"}).status_code == 403
    r = ed.post("/api/questions", json={"source": Q})
    assert r.status_code == 201 and r.json()["status"] == "draft"
    src = r.json()["ex_source"]
    assert ed.put("/api/questions/LG-9", json={"source": src, "status": "approved"}).status_code == 403
    assert ed.put("/api/questions/LG-9", json={"source": src.replace("@level: NB", "@level: TH")}).status_code == 200
    assert ed.post("/api/questions/bulk", json={"codes": ["LG-9"], "status": "approved"}).status_code == 403
    assert ed.post("/api/questions/bulk", json={"codes": ["LG-9"], "level": "VD"}).status_code == 200
    # import luôn vào nháp dù gửi trạng thái đã duyệt
    q2 = Q.replace("LG-9", "LG-10").replace("30", "60")
    assert ed.post("/api/import/commit", json={"source": q2, "status": "approved"}).json()["added"] == ["LG-10"]
    assert admin.get("/api/questions/LG-10").json()["status"] == "draft"
    # không xoá, không quản lý thẻ, không sao lưu, không quản lý người dùng
    assert ed.delete("/api/questions/LG-9").status_code == 403
    assert ed.post("/api/questions/bulk-delete", json={"codes": ["LG-9"]}).status_code == 403
    assert ed.post("/api/tags/move", json={"source": "lop-10", "target": "Lớp 11"}).status_code == 403
    assert ed.get("/api/backup/info").status_code == 403
    assert ed.get("/api/users").status_code == 403
    assert ed.put("/api/settings", json={"student_quick": True}).status_code == 403
    # ghép đề được, xoá đề thì không
    exam = ed.post("/api/exams", json=EXAM)
    assert exam.status_code == 201
    assert ed.put(f"/api/exams/{exam.json()['id']}/published", json={"published": True}).status_code == 200
    assert ed.delete(f"/api/exams/{exam.json()['id']}").status_code == 403
    # admin duyệt được
    assert admin.put("/api/questions/LG-9", json={"source": src, "status": "approved"}).json()["status"] == "approved"

    log = admin.get("/api/questions/LG-9/log").json()
    actions = [(e["username"], e["action"]) for e in log]
    assert ("admin", "duyet") in actions and ("ban-soan", "sua") in actions and ("ban-soan", "tao") in actions
    assert ("ban-soan", "hang-loat") in actions
    sua = next(e for e in log if e["action"] == "sua" and e["username"] == "ban-soan")
    assert "@level: NB" in admin.get(f"/api/question-logs/{sua['id']}").json()["before"]
    assert admin.get("/api/question-logs?username=ban-soan").json()["total"] >= 4
    assert ed.get("/api/question-logs").status_code == 403


def fake_pdfs(app, exam_id: int) -> None:
    with Session(app.state.engine) as s:
        for b in s.scalars(select(Build).where(Build.exam_id == exam_id)):
            target = builds.files_dir() / "exams" / str(exam_id) / f"{b.name}.pdf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"%PDF-1.5 gia")
            b.status, b.pdf_path = BuildStatus.DONE, str(target)
        s.commit()


def test_student_rights(admin, app):
    st = make_user(admin, app, "hoc-vien", "student")
    exam_id = admin.post("/api/exams", json=EXAM).json()["id"]
    fake_pdfs(app, exam_id)

    # không thấy ngân hàng, không soạn, không ghép đề
    assert st.get("/api/questions").status_code == 403
    assert st.post("/api/questions", json={"source": Q}).status_code == 403
    assert st.post("/api/exams", json=EXAM).status_code == 403
    assert st.get("/api/gen/curriculum").status_code == 403

    # đề chưa mở thì không thấy, không làm được
    assert st.get("/api/exams").json() == []
    assert st.post("/api/attempts", json={"exam_id": exam_id}).status_code == 404
    assert st.get(f"/api/exams/{exam_id}/files/de-101.pdf").status_code == 403

    admin.put(f"/api/exams/{exam_id}/published", json={"published": True})
    exams = st.get("/api/exams").json()
    assert [e["id"] for e in exams] == [exam_id]
    assert {f["kind"] for f in exams[0]["files"]} == {"de"}
    assert "variants" not in st.get(f"/api/exams/{exam_id}").json()  # không lộ đáp án
    assert st.get(f"/api/exams/{exam_id}/files/de-101.pdf").status_code == 200
    assert st.get(f"/api/exams/{exam_id}/files/dapan.pdf").status_code == 403
    assert st.get(f"/api/exams/{exam_id}/files.zip").status_code == 403

    # xin tải đáp án, admin đồng ý thì tải được
    r = st.post(f"/api/exams/{exam_id}/answer-request")
    assert r.status_code == 201 and r.json()["request"]["status"] == "pending"
    assert admin.get("/api/auth/me").json()["pending_requests"] == 1
    req = admin.get("/api/answer-requests?status=pending").json()
    assert req[0]["user"]["username"] == "hoc-vien" and req[0]["exam"]["id"] == exam_id
    assert st.put(f"/api/answer-requests/{req[0]['id']}", json={"status": "approved"}).status_code == 403
    assert admin.put(f"/api/answer-requests/{req[0]['id']}", json={"status": "approved"}).status_code == 200
    assert st.get(f"/api/exams/{exam_id}/files/dapan.pdf").status_code == 200
    assert {f["kind"] for f in st.get("/api/exams").json()[0]["files"]} == {"de", "dapan", "loigiai"}

    # làm đề; lượt làm chỉ của mình
    a = st.post("/api/attempts", json={"exam_id": exam_id})
    assert a.status_code == 201
    aid = a.json()["id"]
    assert st.post(f"/api/attempts/{aid}/submit", json={"answers": {}}).status_code == 200
    assert [x["id"] for x in st.get("/api/attempts").json()] == [aid]
    assert st.get("/api/attempts/stats").json()["attempts"] == 1
    assert admin.get("/api/attempts").json() == []
    assert [x["user_name"] for x in admin.get("/api/attempts?all=true").json()] == ["hoc-vien"]
    assert admin.get(f"/api/attempts/{aid}").status_code == 200  # admin xem được
    assert admin.post(f"/api/attempts/{aid}/submit", json={"answers": {}}).status_code == 404  # nhưng không làm thay
    assert st.delete(f"/api/attempts/{aid}").status_code == 403

    # luyện nhanh chỉ khi admin bật
    quick = {"quick": {"mcq": 2}}
    assert st.post("/api/attempts", json=quick).status_code == 403
    assert st.post("/api/attempts", json={"retry_of": aid}).status_code == 403
    assert admin.put("/api/settings", json={"student_quick": True}).json()["student_quick"] is True
    assert st.post("/api/attempts", json=quick).status_code == 201
    assert st.get("/api/auth/me").json()["settings"]["student_quick"] is True


def test_attempts_of_others_hidden(admin, app):
    ed = make_user(admin, app, "ban-soan", "editor")
    exam_id = admin.post("/api/exams", json=EXAM).json()["id"]
    aid = admin.post("/api/attempts", json={"exam_id": exam_id}).json()["id"]
    assert ed.get(f"/api/attempts/{aid}").status_code == 404
    assert ed.delete(f"/api/attempts/{aid}").status_code == 404
    mine = ed.post("/api/attempts", json={"exam_id": exam_id}).json()["id"]
    assert ed.delete(f"/api/attempts/{mine}").status_code == 204
    assert ed.get("/api/attempts/stats?user_id=1").status_code == 403


def test_user_management(admin, app):
    st = make_user(admin, app, "hoc-vien", "student")
    users = {u["username"]: u for u in admin.get("/api/users").json()}
    me_id, st_id = users["admin"]["id"], users["hoc-vien"]["id"]
    # phải còn một admin
    assert admin.put(f"/api/users/{me_id}", json={"role": "editor"}).status_code == 409
    assert admin.put(f"/api/users/{me_id}", json={"active": False}).status_code == 409
    # khoá tài khoản thì phiên đang mở mất hiệu lực, không đăng nhập lại được
    assert admin.put(f"/api/users/{st_id}", json={"active": False}).status_code == 200
    assert st.get("/api/exams").status_code == 401
    r = st.post("/api/auth/login", json={"username": "hoc-vien", "password": "matkhau-hoc-vien"})
    assert r.status_code == 401 and "khoá" in r.json()["detail"]
    # mở khoá, đặt lại mật khẩu, nâng quyền
    assert admin.put(f"/api/users/{st_id}", json={"active": True, "password": "mat-khau-moi", "role": "editor"}).json()["role"] == "editor"
    assert st.post("/api/auth/login", json={"username": "hoc-vien", "password": "mat-khau-moi"}).status_code == 200
    assert st.get("/api/questions").status_code == 200
    # tự đổi mật khẩu
    assert st.post("/api/auth/password", json={"old_password": "sai", "new_password": "abcdef"}).status_code == 422
    assert st.post("/api/auth/password", json={"old_password": "mat-khau-moi", "new_password": "123"}).status_code == 422
    assert st.post("/api/auth/password", json={"old_password": "mat-khau-moi", "new_password": "abcdef"}).status_code == 204
    assert st.get("/api/questions").status_code == 200  # phiên hiện tại vẫn giữ
    # tên trùng, tên sai dạng
    assert admin.post("/api/users", json={"username": "Hoc-Vien", "password": "123456", "role": "student"}).status_code == 422
    assert admin.post("/api/users", json={"username": "có dấu", "password": "123456", "role": "student"}).status_code == 422


def test_backup_keeps_accounts(admin, app):
    """Tài khoản nằm trong bản sao lưu; khôi phục bản cũ chưa có tài khoản thì giữ tài khoản hiện tại."""
    make_user(admin, app, "hoc-vien", "student")
    data = admin.get("/api/backup/download?files=false").content
    info = admin.post("/api/backup/inspect", content=data).json()
    assert info["tables"]["users"] == 2 and "user_sessions" not in info["tables"]

    r = admin.post("/api/backup/restore", content=data)
    assert r.status_code == 200 and r.json()["relogin"] is False
    assert admin.get("/api/users").status_code == 200  # vẫn đăng nhập

    # bản sao lưu cũ (trước khi có tài khoản): bỏ bảng users khỏi file
    import io
    import json
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in src.namelist():
            if n == "manifest.json":
                m = json.loads(src.read(n))
                for t in ("users", "question_logs", "answer_requests", "settings"):
                    m["tables"].pop(t)
                z.writestr(n, json.dumps(m))
            elif n not in ("data/users.jsonl", "data/question_logs.jsonl", "data/answer_requests.jsonl", "data/settings.jsonl"):
                z.writestr(n, src.read(n))
    r = admin.post("/api/backup/restore", content=buf.getvalue())
    assert r.status_code == 200, r.text
    assert {u["username"] for u in admin.get("/api/users").json()} == {"admin", "hoc-vien"}
    assert backup.table_counts(app.state.engine)["questions"] == 15


def test_old_database_gets_new_columns(tmp_path):
    """CSDL tạo từ bản trước (chưa có cột published, user_id) tự được thêm cột khi khởi động."""
    from sqlalchemy import create_engine, inspect, text

    url = f"sqlite:///{tmp_path / 'cu.db'}"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE exams (id INTEGER PRIMARY KEY, title VARCHAR(300), exam_date VARCHAR(20), "
                          "duration INTEGER, config JSON, created_at DATETIME)"))
        conn.execute(text("INSERT INTO exams (id, title, config) VALUES (1, 'Đề cũ', '{}')"))
    eng.dispose()
    app = create_app(url)
    cols = {c["name"] for c in inspect(app.state.engine).get_columns("exams")}
    assert "published" in cols
    with app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT published FROM exams")).scalar() in (0, False)
    app.state.engine.dispose()


def test_select_all_codes(admin):
    """Chọn tất cả câu khớp bộ lọc (mọi trang) rồi duyệt một lần."""
    codes = admin.get("/api/questions/codes?tag=lop-12").json()
    assert len(codes) == 15 and codes == sorted(codes)
    assert len(admin.get("/api/questions/codes?q=12V-01").json()) == 6
    assert admin.post("/api/questions/bulk", json={"codes": codes, "status": "draft"}).json()["updated"] == 15
    assert admin.get("/api/questions/codes?status=draft").json() == codes
