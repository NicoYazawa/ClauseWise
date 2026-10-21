"""Unit tests for the core layer: config / security / exceptions / logging / metrics / audit / alerting / preflight."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import alerting, audit, config, metrics, preflight, security
from app.core import logging as app_logging
from app.core.exceptions import AppError
from tests import helpers


# ===================== config =====================
class TestSettings:
    def test_defaults(self):
        s = config.Settings(_env_file=None)
        assert s.llm_provider == "deepseek"
        assert s.embedding_dim == 1024
        assert s.access_token_expire_days == 7

    def test_storage_path_relative(self):
        s = config.Settings(_env_file=None, storage_root="./data")
        assert s.storage_path.is_absolute()
        assert s.storage_path.name == "data"

    def test_storage_path_absolute(self, storage_root):
        s = config.Settings(_env_file=None, storage_root=str(storage_root))
        assert s.storage_path == storage_root

    def test_sqlalchemy_database_uri(self):
        s = config.Settings(_env_file=None, mysql_user="root", mysql_password="pw",
                            mysql_host="db", mysql_port=3307, mysql_database="cw")
        assert s.sqlalchemy_database_uri == "mysql+pymysql://root:pw@db:3307/cw?charset=utf8mb4"

    def test_get_settings_cached(self):
        assert config.get_settings() is config.get_settings()


# ===================== exceptions =====================
class TestAppError:
    def test_detail_shape(self):
        e = AppError("X_CODE", 404, "msg")
        assert isinstance(e, HTTPException)
        assert e.status_code == 404
        assert e.detail == {"code": "X_CODE", "message": "msg"}


# ===================== security =====================
class TestSecurity:
    def test_password_hash_roundtrip(self):
        h = security.hash_password("Passw0rd!")
        assert h != "Passw0rd!"
        assert security.verify_password("Passw0rd!", h)
        assert not security.verify_password("wrong", h)

    def test_verify_password_none_and_garbage(self):
        assert security.verify_password("x", None) is False
        assert security.verify_password("x", "not-a-hash") is False

    def test_jwt_roundtrip(self):
        token = security.create_access_token(42, "alice")
        payload = security.decode_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "alice"
        assert "exp" in payload

    def test_decode_token_invalid(self):
        with pytest.raises(AppError) as ei:
            security.decode_token("garbage")
        assert ei.value.detail["code"] == "AUTH_INVALID_TOKEN"

    def test_decode_token_expired(self):
        from datetime import UTC, datetime, timedelta

        import jwt

        payload = {"sub": "1", "username": "a", "exp": datetime.now(UTC) - timedelta(hours=1)}
        token = jwt.encode(payload, security.settings.secret_key, algorithm="HS256")
        with pytest.raises(AppError) as ei:
            security.decode_token(token)
        assert ei.value.detail["code"] == "AUTH_TOKEN_EXPIRED"

    def test_get_current_user_missing_credentials(self):
        with pytest.raises(AppError) as ei:
            security.get_current_user(credentials=None, db=None)
        assert ei.value.detail["code"] == "AUTH_MISSING_TOKEN"

    def test_get_current_user_disabled(self, db):
        u = helpers.make_user(db, username="u1", is_active=False)
        db.commit()
        creds = SimpleNamespace(credentials=security.create_access_token(u.id, u.username))
        with pytest.raises(AppError) as ei:
            security.get_current_user(credentials=creds, db=db)
        assert ei.value.detail["code"] == "AUTH_ACCOUNT_DISABLED"

    def test_get_current_user_ok(self, db):
        u = helpers.make_user(db, username="u2")
        db.commit()
        creds = SimpleNamespace(credentials=security.create_access_token(u.id, u.username))
        assert security.get_current_user(credentials=creds, db=db).id == u.id

    def test_get_user_permissions(self, db):
        p1 = helpers.make_permission(db, code="contract:upload")
        p2 = helpers.make_permission(db, code="system:user")
        role = helpers.make_role(db, permissions=[p1, p2])
        u = helpers.make_user(db, roles=[role])
        assert security.get_user_permissions(u) == {"contract:upload", "system:user"}

    def test_require_perm_admin_bypass(self, admin_user):
        checker = security.require_perm("anything")
        assert checker(admin_user) is admin_user

    def test_require_perm_denied(self):
        from app.models.user import Role, User

        role = Role(code="legal", name="法务")
        u = User(id=9, username="u", real_name="u", roles=[role])
        with pytest.raises(AppError) as ei:
            security.require_perm("contract:upload")(u)
        assert ei.value.status_code == 403

    def test_require_perm_allowed(self):
        from app.models.user import Permission, Role, User

        role = Role(code="legal", name="法务", permissions=[Permission(code="contract:upload", name="上传")])
        u = User(id=9, username="u", real_name="u", roles=[role])
        assert security.require_perm("contract:upload")(u).id == 9


# ===================== logging =====================
class TestLogging:
    def test_setup_logging_idempotent(self, storage_root):
        app_logging.setup_logging()
        app_logging.setup_logging()  # second call returns directly
        assert (storage_root / "logs" / "app").exists()


# ===================== metrics =====================
class TestMetrics:
    def test_counters_and_response(self):
        metrics.REVIEW_TASKS.labels(status="completed").inc()
        metrics.PARSE_TASKS.labels(status="failed").inc()
        metrics.LLM_CALLS.labels(model="m", outcome="ok").inc()
        metrics.LLM_LATENCY.labels(model="m").observe(0.1)
        metrics.ALERTS.labels(level="error").inc()
        resp = metrics.metrics_response()
        assert resp.media_type.startswith("text/plain")
        assert b"clausewise_review_tasks_total" in resp.body

    def test_record_call_never_raises(self, monkeypatch):
        from app.ai import llm_client

        llm_client._record_call("m", "ok", 0.01)  # happy path
        monkeypatch.setattr("app.core.metrics.LLM_CALLS", None)
        llm_client._record_call("m", "ok", 0.01)  # failure swallowed


# ===================== audit =====================
class TestAudit:
    def test_write_audit(self, db, storage_root):
        audit.write_audit(db, user_id=1, username="alice", action="login", resource_type="会话",
                          resource_id="-", ip="1.2.3.4", ua="UA", extra="登录成功")
        from app.models.knowledge import AuditLog

        db.expire_all()
        log = db.query(AuditLog).one()
        assert log.action == "login"
        assert log.detail == {"ip": "1.2.3.4", "ua": "UA", "result": "成功", "extra": "登录成功"}
        assert (storage_root / "logs" / "audit").exists()

    def test_write_audit_without_extra(self, db):
        audit.write_audit(db, user_id=None, username="anon", action="logout",
                          resource_type="会话", resource_id="u1")
        from app.models.knowledge import AuditLog

        db.expire_all()
        log = db.query(AuditLog).one()
        assert "extra" not in log.detail

    def test_write_audit_file_failure_swallowed(self, db, monkeypatch):
        def _boom():
            raise RuntimeError("disk full")

        monkeypatch.setattr(audit, "_get_audit_logger", _boom)
        audit.write_audit(db, user_id=1, username="u", action="login",
                          resource_type="会话", resource_id="-")  # do not raise, only warn


# ===================== alerting =====================
class TestAlerting:
    @pytest.fixture(autouse=True)
    def _reset_rate_limit(self):
        alerting._last_sent.clear()
        yield
        alerting._last_sent.clear()

    @pytest.fixture()
    def enabled_settings(self, monkeypatch):
        fake = SimpleNamespace(
            alert_enabled=True, alert_webhook_url="https://example.com/hook",
            alert_min_interval_seconds=300, alert_service_name="clausewise-test",
        )
        monkeypatch.setattr(alerting, "settings", fake)
        return fake

    @pytest.mark.parametrize("url,expected_key", [
        ("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x", "msgtype"),
        ("https://oapi.dingtalk.com/robot/send?access_token=x", "msgtype"),
        ("https://open.feishu.cn/open-apis/bot/v2/hook/x", "msg_type"),
        ("https://open.larksuite.com/open-apis/bot/v2/hook/x", "msg_type"),
        ("https://self-hosted.local/alert", "title"),
    ])
    def test_build_payload(self, enabled_settings, url, expected_key):
        payload = alerting._build_payload(url, "标题", "内容", "error")
        assert expected_key in payload

    def test_notify_disabled(self, monkeypatch):
        fake = SimpleNamespace(alert_enabled=False, alert_webhook_url="", alert_min_interval_seconds=0,
                               alert_service_name="cw")
        monkeypatch.setattr(alerting, "settings", fake)
        assert alerting.notify("t", "c") is False

    def test_notify_success(self, enabled_settings, monkeypatch):
        posted = []
        monkeypatch.setattr(alerting, "_post", lambda url, payload: posted.append((url, payload)))
        assert alerting.notify("任务失败", "详情", level="error", key="review:1") is True
        assert posted and posted[0][1]["title"] == "任务失败"

    def test_notify_rate_limited(self, enabled_settings, monkeypatch):
        monkeypatch.setattr(alerting, "_post", lambda url, payload: None)
        assert alerting.notify("t", "c", key="k") is True
        assert alerting.notify("t", "c", key="k") is False  # same key rate-limited within 5 minutes

    @pytest.mark.parametrize("uptime", [0.0, 1.0, 299.0])
    def test_notify_first_alert_after_boot_and_interval_boundary(self, enabled_settings, monkeypatch, uptime):
        clock = [uptime]
        posted = []
        monkeypatch.setattr(alerting.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(alerting, "_post", lambda url, payload: posted.append(payload))
        assert alerting.notify("t", "c", key="boot") is True
        clock[0] = uptime + 299.0
        assert alerting.notify("t", "c", key="boot") is False
        clock[0] = uptime + 300.0
        assert alerting.notify("t", "c", key="boot") is True
        assert len(posted) == 2

    def test_notify_different_key_not_limited(self, enabled_settings, monkeypatch):
        monkeypatch.setattr(alerting, "_post", lambda url, payload: None)
        assert alerting.notify("t", "c", key="k1") is True
        assert alerting.notify("t", "c", key="k2") is True

    def test_post_network_failure_swallowed(self, monkeypatch):
        import urllib.request

        def _boom(req, timeout):
            raise OSError("network down")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        alerting._post("https://example.com", {"a": 1})  # does not raise

    def test_post_http_error_status_logged(self, monkeypatch):
        import urllib.request

        class _Resp:
            status = 500

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _Resp())
        alerting._post("https://example.com", {"a": 1})

    def test_notify_task_failure(self, enabled_settings, monkeypatch):
        monkeypatch.setattr(alerting, "_post", lambda url, payload: None)
        assert alerting.notify_task_failure("review", 7, "某合同", ValueError("boom")) is True
        alerting._last_sent.clear()
        assert alerting.notify_task_failure("parse", 8, "某合同", ValueError("boom")) is True
        alerting._last_sent.clear()
        assert alerting.notify_task_failure("unknown-kind", 9, "s", "e") is True

    def test_notify_task_failure_disabled(self, monkeypatch):
        fake = SimpleNamespace(alert_enabled=False, alert_webhook_url="", alert_min_interval_seconds=0,
                               alert_service_name="cw")
        monkeypatch.setattr(alerting, "settings", fake)
        assert alerting.notify_task_failure("review", 7, "s", "e") is False


# ===================== preflight =====================
class TestPreflight:
    def test_check_mysql_ok(self, monkeypatch):
        import sqlalchemy

        monkeypatch.setattr("app.db.session.engine", sqlalchemy.create_engine("sqlite://"))
        ok, detail = preflight.check_mysql()
        assert ok is True
        assert "连接正常" in detail

    def test_check_mysql_fail(self, monkeypatch):
        import sqlalchemy

        monkeypatch.setattr("app.db.session.engine", sqlalchemy.create_engine("sqlite://"))
        monkeypatch.setattr(sqlalchemy.engine.Engine, "connect",
                            lambda self: (_ for _ in ()).throw(OSError("x")))
        ok, detail = preflight.check_mysql()
        assert ok is False
        assert "无法连接" in detail

    def test_check_elasticsearch_none(self, monkeypatch):
        monkeypatch.setattr("app.es.client.get_es_client", lambda: None)
        ok, detail = preflight.check_elasticsearch()
        assert ok is False and "不可达" in detail

    def test_check_elasticsearch_ok(self, monkeypatch):
        monkeypatch.setattr("app.es.client.get_es_client", lambda: helpers.FakeES())
        ok, detail = preflight.check_elasticsearch()
        assert ok is True and "9.1.2" in detail

    def test_check_elasticsearch_fail(self, monkeypatch):
        class _Boom:
            def info(self):
                raise RuntimeError("cluster down")

        monkeypatch.setattr("app.es.client.get_es_client", lambda: _Boom())
        ok, _ = preflight.check_elasticsearch()
        assert ok is False

    def test_check_redis_ok(self, monkeypatch):
        import redis as redis_lib

        class _R:
            def ping(self):
                return True

        monkeypatch.setattr(redis_lib.Redis, "from_url", lambda url, **kw: _R())
        ok, detail = preflight.check_redis()
        assert ok is True and "PING 通过" in detail

    def test_check_redis_fail(self, monkeypatch):
        import redis as redis_lib

        monkeypatch.setattr(redis_lib.Redis, "from_url",
                            lambda url, **kw: (_ for _ in ()).throw(OSError("refused")))
        ok, _ = preflight.check_redis()
        assert ok is False

    def test_probe_missing_key(self):
        from app.ai.providers import ModelEndpoint

        ep = ModelEndpoint(kind="llm", provider="deepseek", base_url="https://x", api_key="",
                           api_key_env="DEEPSEEK_API_KEY", model="m")
        ok, detail = preflight._probe(ep, "对话模型")
        assert ok is False and "未配置" in detail

    def test_probe_ok(self, monkeypatch):
        from app.ai.providers import ModelEndpoint

        ep = ModelEndpoint(kind="llm", provider="deepseek", base_url="https://x", api_key="k",
                           api_key_env="DEEPSEEK_API_KEY", model="m")
        calls = []

        class _Models:
            def list(self):
                calls.append("list")
                return None

        class _Client:
            def __init__(self, **kw):
                calls.append(kw)

            @property
            def models(self):
                return _Models()

        import openai
        monkeypatch.setattr(openai, "OpenAI", _Client)
        ok, detail = preflight._probe(ep, "对话模型")
        assert ok is True and "连通" in detail

    def test_probe_models_list_404_fallback(self, monkeypatch):
        from app.ai.providers import ModelEndpoint

        ep = ModelEndpoint(kind="llm", provider="custom", base_url="https://x", api_key="k",
                           api_key_env="K", model="m")
        import openai
        from openai import APIStatusError

        class _Models:
            def list(self):
                raise APIStatusError("404 page not found",
                                     response=helpers.http_response(404), body=None)

        class _Client:
            def __init__(self, **kw):
                pass

            @property
            def models(self):
                return _Models()

        monkeypatch.setattr(openai, "OpenAI", _Client)
        ok, detail = preflight._probe(ep, "对话模型")
        assert ok is True and "跳过实测" in detail

    def test_probe_error(self, monkeypatch):
        from app.ai.providers import ModelEndpoint

        ep = ModelEndpoint(kind="llm", provider="custom", base_url="https://x", api_key="k",
                           api_key_env="K", model="m")
        import openai

        class _Models:
            def list(self):
                raise RuntimeError("500 boom")

        class _Client:
            def __init__(self, **kw):
                pass

            @property
            def models(self):
                return _Models()

        monkeypatch.setattr(openai, "OpenAI", _Client)
        ok, detail = preflight._probe(ep, "对话模型")
        assert ok is False and "调用失败" in detail

    def test_check_llm_config_error(self, monkeypatch):
        from app.ai.providers import ModelConfigError

        def _boom():
            raise ModelConfigError("未知厂商")

        monkeypatch.setattr("app.core.preflight.llm_endpoint", _boom)
        ok, detail = preflight.check_llm()
        assert ok is False and "配置错误" in detail

    def test_check_embedding_config_error(self, monkeypatch):
        from app.ai.providers import ModelConfigError

        monkeypatch.setattr("app.core.preflight.embedding_endpoint",
                            lambda: (_ for _ in ()).throw(ModelConfigError("坏")))
        ok, _ = preflight.check_embedding()
        assert ok is False

    def test_run_preflight_checks_collects(self, monkeypatch):
        monkeypatch.setattr(preflight, "CHECKS", [
            ("A", lambda: (True, "ok")),
            ("B", lambda: (_ for _ in ()).throw(RuntimeError("x"))),
            ("C", lambda: (False, "down")),
        ])
        results = preflight.run_preflight_checks()
        assert [r[1] for r in results] == [True, False, False]
        assert "检测异常" in results[1][2]

    def test_enforce_preflight_all_ok(self, monkeypatch):
        monkeypatch.setattr(preflight, "run_preflight_checks", lambda: [("MySQL", True, "ok")])
        preflight.enforce_preflight()  # 不抛

    def test_enforce_preflight_strict_exits(self, monkeypatch):
        monkeypatch.setattr(preflight, "run_preflight_checks",
                            lambda: [("MySQL 数据库", False, "down"), ("Redis", False, "down")])
        with pytest.raises(SystemExit):
            preflight.enforce_preflight()

    def test_enforce_preflight_non_strict_degrades(self, monkeypatch):
        monkeypatch.setattr(preflight, "run_preflight_checks",
                            lambda: [("MySQL 数据库", True, "ok"), ("Redis", False, "down")])
        monkeypatch.setattr(preflight.settings, "preflight_strict", False)
        preflight.enforce_preflight()  # 仅 MySQL 致命 → 不退出

    def test_enforce_preflight_non_strict_mysql_fatal(self, monkeypatch):
        monkeypatch.setattr(preflight, "run_preflight_checks", lambda: [("MySQL 数据库", False, "down")])
        monkeypatch.setattr(preflight.settings, "preflight_strict", False)
        with pytest.raises(SystemExit):
            preflight.enforce_preflight()

    def test_print_report_output(self, capsys):
        ok = preflight._print_report([("MySQL", True, "ok"), ("Redis", False, "down")])
        assert ok is False
        out = capsys.readouterr().out
        assert "[OK]" in out and "[FAIL]" in out and "预检未通过" in out

    def test_module_main(self, monkeypatch):
        """Cover the `if __name__ == "__main__"` guard block (extracted via AST and executed as a patched function)."""
        import ast
        from pathlib import Path

        printed = []
        monkeypatch.setattr(preflight, "run_preflight_checks", lambda: [("MySQL", True, "ok")])
        monkeypatch.setattr(preflight, "_print_report", lambda results: printed.append(results) or True)

        src = Path(preflight.__file__).read_text(encoding="utf-8")
        guard = next(n for n in ast.parse(src).body if isinstance(n, ast.If))
        ns = {
            "__name__": "__main__",
            "sys": SimpleNamespace(exit=lambda code=0: (_ for _ in ()).throw(SystemExit(code))),
            "run_preflight_checks": preflight.run_preflight_checks,
            "_print_report": preflight._print_report,
        }
        with pytest.raises(SystemExit) as ei:
            exec(compile(ast.Module(body=guard.body, type_ignores=[]), "<preflight-main>", "exec"), ns)
        assert ei.value.code == 0
        assert len(printed) == 1
