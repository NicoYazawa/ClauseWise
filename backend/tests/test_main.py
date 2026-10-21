"""Unit tests for the main entrypoint: health check / metrics / app assembly."""
from __future__ import annotations

import pytest

from app.main import app

API = "/api/v1"


@pytest.fixture()
def health_env(monkeypatch):
    """Controlled deps: MySQL engine / dispatch mode / ES / model endpoints."""
    import sqlalchemy

    from app.ai.providers import ModelEndpoint

    sqlite_engine = sqlalchemy.create_engine("sqlite://")
    monkeypatch.setattr("app.db.session.engine", sqlite_engine)
    monkeypatch.setattr("app.tasks.dispatcher.current_mode", lambda: "threadpool")
    monkeypatch.setattr("app.tasks.dispatcher.redis_available", lambda: False)
    monkeypatch.setattr("app.es.client.get_es_client", lambda: None)
    monkeypatch.setattr("app.ai.providers.llm_endpoint", lambda: ModelEndpoint(
        kind="llm", provider="deepseek", base_url="https://api.deepseek.com", api_key="k",
        api_key_env="DEEPSEEK_API_KEY", model="deepseek-chat"))
    monkeypatch.setattr("app.ai.providers.embedding_endpoint", lambda: ModelEndpoint(
        kind="embedding", provider="dashscope", base_url="https://x", api_key="k",
        api_key_env="DASHSCOPE_API_KEY", model="text-embedding-v4", dimensions=1024))


class TestHealth:
    def test_health_ok(self, client, health_env):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["mysql"] == "up"
        assert body["task_mode"] == "threadpool"
        assert body["redis"] == "down"
        assert body["elasticsearch"] == "down"
        assert body["llm"] == "deepseek:deepseek-chat"

    def test_health_celery_mode(self, client, health_env, monkeypatch):
        monkeypatch.setattr("app.tasks.dispatcher.current_mode", lambda: "celery")
        body = client.get("/health").json()
        assert body["redis"] == "up"
        assert body["worker"] == "up"

    def test_health_redis_up_no_worker(self, client, health_env, monkeypatch):
        monkeypatch.setattr("app.tasks.dispatcher.redis_available", lambda: True)
        body = client.get("/health").json()
        assert body["redis"] == "up"
        assert "降级" in body["worker"]

    def test_health_mysql_down_degraded(self, client, health_env, monkeypatch):
        monkeypatch.setattr("app.db.session.engine",
                            __import__("sqlalchemy").create_engine("sqlite://"))
        import sqlalchemy

        monkeypatch.setattr(sqlalchemy.engine.Engine, "connect",
                            lambda self: (_ for _ in ()).throw(OSError("db down")))
        body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["mysql"].startswith("down")

    def test_health_dispatcher_exception(self, client, health_env, monkeypatch):
        def _boom():
            raise RuntimeError("dispatch broken")

        monkeypatch.setattr("app.tasks.dispatcher.current_mode", _boom)
        body = client.get("/health").json()
        assert body["redis"].startswith("down")
        assert body["task_mode"] == "unknown"

    def test_health_es_exception(self, client, health_env, monkeypatch):
        def _boom():
            raise RuntimeError("es broken")

        monkeypatch.setattr("app.es.client.get_es_client", _boom)
        body = client.get("/health").json()
        assert body["elasticsearch"].startswith("down")

    def test_health_model_unconfigured_key(self, client, health_env, monkeypatch):
        from app.ai.providers import ModelEndpoint

        monkeypatch.setattr("app.ai.providers.llm_endpoint", lambda: ModelEndpoint(
            kind="llm", provider="deepseek", base_url="https://x", api_key="",
            api_key_env="DEEPSEEK_API_KEY", model="m"))
        body = client.get("/health").json()
        assert body["llm"] == "deepseek:m（未配置密钥）"

    def test_health_model_config_error(self, client, health_env, monkeypatch):
        from app.ai.providers import ModelConfigError

        def _boom():
            raise ModelConfigError("厂商未知")

        monkeypatch.setattr("app.ai.providers.llm_endpoint", _boom)
        body = client.get("/health").json()
        assert body["llm"].startswith("config error")

    def test_metrics(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert b"clausewise_" in resp.content

    def test_metrics_not_in_schema(self):
        assert "/metrics" not in app.openapi().get("paths", {})


class TestAppAssembly:
    def test_routes_mounted(self):
        paths = set(app.openapi()["paths"])
        assert f"{API}/auth/login" in paths
        assert f"{API}/contracts" in paths
        assert f"{API}/review-tasks" in paths
        assert f"{API}/workflow/instances" in paths
        assert f"{API}/laws" in paths
        assert f"{API}/qa/ask" in paths
        assert f"{API}/agents" in paths
        assert f"{API}/findings" in paths
        assert "/health" in paths

    def test_middlewares(self):
        # user_middleware elements are Middleware wrappers; the actual class is on .cls
        classes = {getattr(m, "cls", m).__name__ for m in app.user_middleware}
        assert "CORSMiddleware" in classes
        assert "GZipMiddleware" in classes

    def test_app_metadata(self):
        assert app.title == "AI智能合同合规审查平台 API"
        assert app.version == "1.0.0"


class TestLifespan:
    def test_startup_sequence(self, monkeypatch):
        """lifespan: preflight -> ES indices -> zombie recovery -> built-in scheduler; any failure degrades without blocking."""
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        order = []
        monkeypatch.setattr("app.core.preflight.enforce_preflight", lambda: order.append("preflight"))
        monkeypatch.setattr("app.es.indices.ensure_indices", lambda: order.append("indices") or True)
        monkeypatch.setattr("app.db.session.SessionLocal", lambda: _FakeSession(order))
        _stub_security_upgrade(monkeypatch)
        monkeypatch.setattr("app.services.review_service.recover_stale_tasks",
                            lambda db: order.append("recover") or 0)
        monkeypatch.setattr("app.tasks.dispatcher.start_builtin_scheduler",
                            lambda *a, **k: order.append("scheduler"))
        with TestClient(fastapi_app):
            pass  # enter/exit the lifespan
        assert order == ["preflight", "indices", "recover", "scheduler"]

    def test_startup_es_failure_tolerated(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        monkeypatch.setattr("app.core.preflight.enforce_preflight", lambda: None)

        def _boom():
            raise RuntimeError("es init down")

        monkeypatch.setattr("app.es.indices.ensure_indices", _boom)
        monkeypatch.setattr("app.db.session.SessionLocal", lambda: _FakeSession([]))
        _stub_security_upgrade(monkeypatch)
        monkeypatch.setattr("app.services.review_service.recover_stale_tasks", lambda db: 0)
        monkeypatch.setattr("app.tasks.dispatcher.start_builtin_scheduler", lambda *a, **k: None)
        with TestClient(fastapi_app):
            pass  # ES failure only warns

    def test_startup_recover_failure_tolerated(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        monkeypatch.setattr("app.core.preflight.enforce_preflight", lambda: None)
        monkeypatch.setattr("app.es.indices.ensure_indices", lambda: True)
        monkeypatch.setattr("app.db.session.SessionLocal", lambda: _FakeSession([]))
        _stub_security_upgrade(monkeypatch)

        def _boom(db):
            raise RuntimeError("recover down")

        monkeypatch.setattr("app.services.review_service.recover_stale_tasks", _boom)
        monkeypatch.setattr("app.tasks.dispatcher.start_builtin_scheduler", lambda *a, **k: None)
        with TestClient(fastapi_app):
            pass  # recovery failure only warns

    def test_startup_scheduler_failure_tolerated(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        monkeypatch.setattr("app.core.preflight.enforce_preflight", lambda: None)
        monkeypatch.setattr("app.es.indices.ensure_indices", lambda: True)
        monkeypatch.setattr("app.db.session.SessionLocal", lambda: _FakeSession([]))
        _stub_security_upgrade(monkeypatch)
        monkeypatch.setattr("app.services.review_service.recover_stale_tasks", lambda db: 0)

        def _boom(*a, **k):
            raise RuntimeError("scheduler down")

        monkeypatch.setattr("app.tasks.dispatcher.start_builtin_scheduler", _boom)
        with TestClient(fastapi_app):
            pass  # scheduler failure only warns


class _FakeSession:
    def __init__(self, order):
        self._order = order

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_security_upgrade(monkeypatch):
    """Startup security upgrade hits the real DB; isolate it from lifespan flow tests."""
    monkeypatch.setattr("app.db.security_upgrade.upgrade_schema", lambda engine: None)
    monkeypatch.setattr("app.db.security_upgrade.harden_legacy_accounts", lambda db, **kwargs: None)
    monkeypatch.setattr("app.db.security_upgrade.sync_permissions", lambda db: None)
    monkeypatch.setattr("app.db.security_upgrade.seed_preset_accounts", lambda db, **kwargs: 0)
    monkeypatch.setattr("app.db.security_upgrade.migrate_legacy_reports", lambda db: None)
