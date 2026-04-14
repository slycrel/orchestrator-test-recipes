"""Shared pytest fixtures for test isolation.

Sets DATABASE_URL once at module load time (before any test-file imports of src.main),
then provides function-scoped db_engine and db fixtures that reset the schema per test.
"""
import os
import tempfile

import pytest
from sqlalchemy.orm import Session

# Create one shared temp DB file and set DATABASE_URL before test modules import app.
_shared_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
_shared_db_path = _shared_db.name
_shared_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_shared_db_path}"

from src.models import Base, create_db_engine, get_session, init_db  # noqa: E402


@pytest.fixture(scope="function")
def db_path():
    """Return the shared test DB file path."""
    return _shared_db_path


@pytest.fixture(scope="function")
def db_engine(db_path):
    """Fresh schema for each test — drop_all + init_db ensures clean state."""
    engine = create_db_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.drop_all(engine)
    init_db(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db(db_engine):
    """SQLAlchemy session bound to the per-test engine."""
    session = get_session(db_engine)
    yield session
    session.close()
