"""Kết nối cơ sở dữ liệu. Mặc định SQLite tại ./nganhang.db, đổi bằng biến NHD_DB."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_URL = "sqlite:///nganhang.db"


def get_url() -> str:
    return os.environ.get("NHD_DB", DEFAULT_URL)


def make_session(url: str | None = None) -> Session:
    engine = create_engine(url or get_url())
    Base.metadata.create_all(engine)
    return sessionmaker(engine)()
