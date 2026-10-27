"""Kết nối cơ sở dữ liệu. Mặc định SQLite tại ./nganhang.db, đổi bằng biến NHD_DB."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_URL = "sqlite:///nganhang.db"


def get_url() -> str:
    return os.environ.get("NHD_DB", DEFAULT_URL)


def make_session(url: str | None = None) -> Session:
    engine = create_engine(url or get_url())
    Base.metadata.create_all(engine)
    upgrade_schema(engine)
    return sessionmaker(engine)()


def upgrade_schema(engine: Engine) -> list[str]:
    """Thêm các cột mới có trong mô hình nhưng chưa có trong cơ sở dữ liệu đang dùng (chưa dùng Alembic).
    Chỉ thêm cột cho phép trống hoặc có giá trị mặc định nên không đụng dữ liệu cũ. Trả về các cột đã thêm."""
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'
                if col.server_default is not None:
                    sql += f" DEFAULT {col.server_default.arg.compile(dialect=engine.dialect)}"
                conn.execute(text(sql))
                added.append(f"{table.name}.{col.name}")
    return added
