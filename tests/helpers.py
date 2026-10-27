"""Tiện ích dùng chung cho test API."""

ADMIN = {"username": "admin", "password": "matkhau-admin", "display_name": "Quản trị"}


def login_admin(client):
    """Tạo tài khoản admin đầu tiên (nếu chưa có) và đăng nhập; cookie phiên giữ trong client."""
    r = client.post("/api/auth/setup", json=ADMIN)
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"username": ADMIN["username"], "password": ADMIN["password"]})
    assert r.status_code in (200, 201), r.text
    return r.json()
