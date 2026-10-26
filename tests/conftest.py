import os

import pytest
from sqlalchemy import create_engine

from nganhangde.models import Base


@pytest.fixture
def db_url(tmp_path):
    """SQLite tạm theo mặc định; đặt NHD_TEST_DB (ví dụ postgresql+psycopg://...) để chạy trên PostgreSQL."""
    url = os.environ.get("NHD_TEST_DB")
    if not url:
        return f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    engine.dispose()
    return url
