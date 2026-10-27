"""Tài khoản, mật khẩu và phiên đăng nhập. Mật khẩu băm bằng scrypt có sẵn trong Python."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .models import Attempt, Role, User, UserSession

SESSION_DAYS = 30
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 6
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,64}$")

_N, _R, _P = 2**14, 8, 1


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, key = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(base64.b64decode(key))
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(key))


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"mật khẩu cần ít nhất {MIN_PASSWORD} ký tự")


def normalize_username(username: str) -> str:
    name = username.strip().lower()
    if not USERNAME_RE.match(name):
        raise AuthError("tên đăng nhập 3–64 ký tự, chỉ gồm chữ không dấu, số và . _ -")
    return name


def has_users(session: Session) -> bool:
    return (session.scalar(select(func.count(User.id))) or 0) > 0


def get_user(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username.strip().lower()))


def create_user(session: Session, username: str, password: str, role: Role, display_name: str | None = None) -> User:
    name = normalize_username(username)
    check_password(password)
    if get_user(session, name) is not None:
        raise AuthError(f"đã có tài khoản {name}")
    user = User(username=name, display_name=(display_name or "").strip() or name, role=role,
                password_hash=hash_password(password), active=True, failed_logins=0)
    session.add(user)
    session.flush()
    if role == Role.ADMIN:
        claim_orphan_attempts(session)
    session.commit()
    return user


def set_password(session: Session, user: User, password: str) -> None:
    check_password(password)
    user.password_hash = hash_password(password)
    user.failed_logins, user.locked_until = 0, None
    session.commit()


def active_admins(session: Session) -> int:
    return session.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN, User.active.is_(True))) or 0


def claim_orphan_attempts(session: Session) -> int:
    """Lượt luyện có từ trước khi có tài khoản (hoặc từ bản sao lưu cũ) giao cho admin đầu tiên."""
    admin = session.scalar(select(User).where(User.role == Role.ADMIN).order_by(User.id))
    if admin is None:
        return 0
    res = session.execute(update(Attempt).where(Attempt.user_id.is_(None)).values(user_id=admin.id))
    return res.rowcount or 0


def authenticate(session: Session, username: str, password: str, now: datetime | None = None) -> User:
    """Kiểm tra mật khẩu; sai MAX_FAILED lần liên tiếp thì khoá đăng nhập LOCK_MINUTES phút."""
    now = now or datetime.now()
    user = get_user(session, username)
    if user is None:
        verify_password(password, hash_password("x"))  # giữ thời gian trả lời như khi có tài khoản
        raise AuthError("sai tên đăng nhập hoặc mật khẩu")
    if not user.active:
        raise AuthError("tài khoản đã bị khoá, liên hệ admin")
    if user.locked_until and user.locked_until > now:
        mins = int((user.locked_until - now).total_seconds() // 60) + 1
        raise AuthError(f"nhập sai quá nhiều lần, thử lại sau {mins} phút")
    if not verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= MAX_FAILED:
            user.failed_logins, user.locked_until = 0, now + timedelta(minutes=LOCK_MINUTES)
        session.commit()
        raise AuthError("sai tên đăng nhập hoặc mật khẩu")
    user.failed_logins, user.locked_until, user.last_login = 0, None, now
    session.commit()
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    session.add(UserSession(token_hash=_hash_token(token), user_id=user.id, created_at=now,
                            expires_at=now + timedelta(days=SESSION_DAYS)))
    session.execute(delete(UserSession).where(UserSession.expires_at < now))
    session.commit()
    return token


def session_user(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = session.get(UserSession, _hash_token(token))
    if s is None or s.expires_at < datetime.now():
        return None
    user = session.get(User, s.user_id)
    return user if user is not None and user.active else None


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
        session.commit()


def end_user_sessions(session: Session, user_id: int, keep: str | None = None) -> None:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep:
        stmt = stmt.where(UserSession.token_hash != _hash_token(keep))
    session.execute(stmt)
    session.commit()
