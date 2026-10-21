"""Pytest global scaffolding: deterministic env vars + in-memory SQLite (MySQL substitute) + shared fixtures.

Design notes:
- All env vars are set before importing app.*, overriding backend/.env, so tests are repeatable;
- SQLAlchemy dialect patches (BigInteger->Integer / mysql.TINYINT->Boolean) let the ORM models run
  directly on SQLite; they take effect only in the test process and do not affect production MySQL;
- In-memory SQLite + StaticPool shares a single connection, so the TestClient request session and the
  test seeding session see the same data;
- No product code is changed; all fake dependencies (LLM / ES / Celery / filesystem) are injected via monkeypatch.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

# ===================== 1) Deterministic test environment (must come before importing app) =====================
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="clausewise-tests-"))
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-0123456789abcdef"
os.environ["STORAGE_ROOT"] = str(_TMP_ROOT / "data")
os.environ["ALERT_ENABLED"] = "false"
os.environ["ALERT_WEBHOOK_URL"] = ""
os.environ["ALERT_INGEST_TOKEN"] = ""
os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
os.environ["DASHSCOPE_API_KEY"] = "test-dashscope-key"
os.environ["WORKER_METRICS_PORT"] = "0"
os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

# ===================== 2) SQLite dialect-compat patches (must come before importing app.models) =====================
import sqlalchemy as _sa  # noqa: E402

_sa.BigInteger = _sa.Integer  # SQLite only supports INTEGER auto-increment PKs; a BIGINT PK insert fails with NOT NULL
import sqlalchemy.dialects.mysql as _mysql_dialect  # noqa: E402

_mysql_dialect.TINYINT = _sa.Boolean  # SQLite does not compile mysql.TINYINT

# ===================== 3) In-memory SQLite engine (StaticPool shares a single connection) =====================
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

test_engine = create_engine(
    "sqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
    future=True,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)

import app.db.base as _db_base  # noqa: E402
import app.models as _models  # noqa: E402, F401  (registers all models)

_db_base.Base.metadata.create_all(test_engine)

# Point every module at the test DB (after this, `from app.db.session import SessionLocal` yields the test session factory)
import app.db.session as _db_session  # noqa: E402

_db_session.SessionLocal = TestSessionLocal
_db_session.engine = test_engine


# ===================== 4) Shared fixtures =====================
@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Disable real sleep globally: LLM/embedding retry backoff and polling loops no longer slow tests."""
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear lru_cache to avoid cross-test contamination (endpoint / es client / ik probe)."""
    from app.ai import providers
    from app.es import client as es_client

    def _clear(fn):
        clear = getattr(fn, "cache_clear", None)  # also handle plain functions replaced by monkeypatch
        if callable(clear):
            clear()

    _clear(providers.llm_endpoint)
    _clear(providers.embedding_endpoint)
    _clear(providers.vision_endpoint)
    _clear(es_client.get_es_client)
    _clear(es_client.has_ik_plugin)
    yield
    _clear(providers.llm_endpoint)
    _clear(providers.embedding_endpoint)
    _clear(providers.vision_endpoint)
    _clear(es_client.get_es_client)
    _clear(es_client.has_ik_plugin)


@pytest.fixture()
def storage_root() -> Path:
    return _TMP_ROOT / "data"


@pytest.fixture()
def db():
    """Function-scoped clean session: drop then recreate tables so tests stay isolated."""
    _db_base.Base.metadata.drop_all(test_engine)
    _db_base.Base.metadata.create_all(test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def session_factory() -> sessionmaker:
    return TestSessionLocal


@pytest.fixture()
def admin_user():
    """Detached admin user (roles include admin, so require_perm is fully allowed)."""
    from app.models.user import Role, User

    role = Role(id=1, code="admin", name="系统管理员", data_scope="all")
    return User(
        id=1, username="admin", password_hash="x", real_name="管理员",
        dept_name="信息技术部", title="系统管理员", is_active=True, roles=[role],
    )


@pytest.fixture()
def client(db, admin_user):
    """FastAPI TestClient: overrides get_db / get_current_user deps; skips lifespan (avoids real preflight).

    - get_db: a fresh session per request (shares the same in-memory DB with the seeding session);
    - get_current_user: returns the detached admin by default (roles include admin, require_perm fully allowed);
      tests can set ``client.user_state["user_id"] = <id>`` to load a real user from the request session
      (so Mutations like password changes + commit inside the endpoint are persisted).
    """
    from fastapi.testclient import TestClient

    from app.core.security import get_current_user
    from app.db.session import get_db
    from app.main import app
    from app.models.user import User

    holder: dict = {}
    user_state = {"user_id": None}

    def _override_db():
        s = TestSessionLocal()
        holder["db"] = s
        try:
            yield s
        finally:
            holder.pop("db", None)
            s.close()

    def _override_user():
        session = holder.get("db")
        if session is not None and user_state["user_id"] is not None:
            loaded = session.get(User, user_state["user_id"])
            if loaded is not None:
                return loaded
        return admin_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    test_client = TestClient(app)
    test_client.user_state = user_state
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()
