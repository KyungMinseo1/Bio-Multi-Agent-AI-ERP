import os
import tempfile
from pathlib import Path
import pytest

# Never reuse a developer DATABASE_URL, even when tests are started inside the API container.
_test_dir = tempfile.TemporaryDirectory(prefix="bioerp-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_dir.name) / "test.db").as_posix()
os.environ["SESSION_SECRET"] = "isolated-test-session-signing-key"
os.environ["INITIAL_APPROVER_EMAIL"] = "approver@example.test"
os.environ["INITIAL_APPROVER_PASSWORD"] = "test-only-approver-password"
os.environ["INITIAL_OPERATOR_EMAIL"] = "operator@example.test"
os.environ["INITIAL_OPERATOR_PASSWORD"] = "test-only-operator-password"
os.environ["PLANNING_AS_OF"] = "2026-10-24"

from sqlalchemy import text
from fastapi.testclient import TestClient
from app.db import engine, SessionLocal
from app.models import Base
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def isolated_database_cleanup():
    yield
    # Windows cannot unlink SQLite files while a pooled DBAPI connection remains open.
    from sqlalchemy.orm import close_all_sessions
    close_all_sessions()
    engine.dispose()
    _test_dir.cleanup()


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0002_outbound_emails')"))
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_ROLE_MAPPING", "{}")
    with TestClient(app) as value:
        login = value.post("/api/v1/auth/login", json={"email": "approver@example.test", "password": "test-only-approver-password"})
        assert login.status_code == 200
        yield value
