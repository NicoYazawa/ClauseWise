"""Unit tests for the tasks layer: dispatcher / Celery task bodies / registry / scheduled tasks / worker metrics."""
from __future__ import annotations

import socket
import threading
from types import SimpleNamespace

import pytest

from app.tasks import (
    celery_app as celery_app_module,
)
from app.tasks import (
    dispatcher,
    index_tasks,
    parse_tasks,
    registry,
    review_tasks,
    schedule_tasks,
    worker_metrics,
)
from tests import helpers


class _FakeTaskSelf:
    """Self-reference stand-in for a Celery bind=True task."""

    class MaxRetriesExceededError(Exception):
        pass

    def __init__(self, retries: int = 0):
        self.request = SimpleNamespace(retries=retries)
        self.retry_calls: list[tuple] = []

    def retry(self, exc, countdown):
        self.retry_calls.append((exc, countdown))
        raise RuntimeError(f"retry scheduled (countdown={countdown})")


# ===================== celery_app =====================
class TestCeleryApp:
    def test_app_config(self):
        app = celery_app_module.celery_app
        assert app.main == "contract_compliance"
        assert app.conf.task_serializer == "json"
        assert app.conf.timezone == "Asia/Shanghai"
        assert app.conf.task_default_queue == "review"
        assert app.conf.task_time_limit == 1800
        assert "scan-approval-timeout" in app.conf.beat_schedule
        assert "recover-stale-tasks" in app.conf.beat_schedule
        assert "app.tasks.parse_tasks" in app.conf.include

    def test_worker_metrics_not_started_by_default(self):
        # WORKER_METRICS_PORT=0 (set by conftest) -> the metrics server does not start on import
        assert celery_app_module.settings.worker_metrics_port == 0


# ===================== dispatcher =====================
class TestDispatcher:
    def test_detect_redis_ok(self, monkeypatch):
        monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: SimpleNamespace(close=lambda: None))
        assert dispatcher._detect_redis() is True

    def test_detect_redis_down(self, monkeypatch):
        def _boom(addr, timeout):
            raise OSError("refused")

        monkeypatch.setattr(socket, "create_connection", _boom)
        assert dispatcher._detect_redis() is False

    def test_detect_worker_ok(self, monkeypatch):
        class _Inspect:
            def __init__(self, **kw):
                pass

            def ping(self, timeout=None):
                return {"worker@host": {"ok": "pong"}}

        monkeypatch.setattr("app.tasks.celery_app.celery_app.control.inspect", lambda **kw: _Inspect(**kw))
        assert dispatcher._detect_worker() is True

    def test_detect_worker_typeerror_fallback(self, monkeypatch):
        calls = []

        class _Inspect:
            def __init__(self, **kw):
                calls.append(kw)
                if "timeout" in kw:  # Celery>=5.6 签名
                    raise TypeError("unexpected timeout")

            def ping(self, timeout=None):
                return {"w": {}}

        # first call with timeout -> TypeError; second call without timeout
        monkeypatch.setattr("app.tasks.celery_app.celery_app.control.inspect", _Inspect)
        assert dispatcher._detect_worker() is True
        assert len(calls) == 2

    def test_detect_worker_exception(self, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("no worker")

        monkeypatch.setattr("app.tasks.celery_app.celery_app.control.inspect", _boom)
        assert dispatcher._detect_worker() is False

    def test_redis_available_parses_url(self, monkeypatch):
        seen = {}

        def _fake(host, port, timeout=1.5):
            seen.update(host=host, port=port)
            return True

        monkeypatch.setattr(dispatcher, "_detect_redis", _fake)
        monkeypatch.setattr(dispatcher.settings, "redis_url", "redis://redis-host:16379/0")
        assert dispatcher.redis_available() is True
        assert seen["host"] == "redis-host"
        assert seen["port"] == 16379

    def test_current_mode_celery(self, monkeypatch):
        monkeypatch.setattr(dispatcher, "_mode", None)
        monkeypatch.setattr(dispatcher, "redis_available", lambda: True)
        monkeypatch.setattr(dispatcher, "_detect_worker", lambda timeout=2.0: True)
        assert dispatcher.current_mode() == "celery"

    def test_current_mode_threadpool_when_no_worker(self, monkeypatch):
        monkeypatch.setattr(dispatcher, "_mode", None)
        monkeypatch.setattr(dispatcher, "redis_available", lambda: True)
        monkeypatch.setattr(dispatcher, "_detect_worker", lambda timeout=2.0: False)
        assert dispatcher.current_mode() == "threadpool"

    def test_current_mode_threadpool_when_no_redis(self, monkeypatch):
        monkeypatch.setattr(dispatcher, "_mode", None)
        monkeypatch.setattr(dispatcher, "redis_available", lambda: False)
        assert dispatcher.current_mode() == "threadpool"

    def test_current_mode_cached(self, monkeypatch):
        monkeypatch.setattr(dispatcher, "_mode", "celery")
        monkeypatch.setattr(dispatcher, "_mode_decided_at", __import__("time").monotonic())
        monkeypatch.setattr(dispatcher, "redis_available", lambda: False)  # 不应被调用
        assert dispatcher.current_mode() == "celery"

    def test_get_executor_singleton(self):
        e1 = dispatcher._get_executor()
        assert e1 is dispatcher._get_executor()

    def test_run_in_thread_executes(self, monkeypatch):
        done = threading.Event()
        received = {}

        def fake_fn(db, version_id):
            received["db"] = db
            received["version_id"] = version_id
            done.set()

        monkeypatch.setattr(registry, "TASK_FUNCS", {"parse_contract": fake_fn})
        dispatcher._run_in_thread("parse_contract", (42,))
        assert done.wait(timeout=5)
        assert received["version_id"] == 42
        assert received["db"] is not None

    def test_run_in_thread_failure_logged(self, monkeypatch):
        done = threading.Event()

        def fake_fn(db, version_id):
            done.set()
            raise RuntimeError("boom")

        monkeypatch.setattr(registry, "TASK_FUNCS", {"parse_contract": fake_fn})
        dispatcher._run_in_thread("parse_contract", (1,))
        assert done.wait(timeout=5)  # exception swallowed, only logged

    @pytest.mark.parametrize("submit, task_name, queue", [
        (dispatcher.submit_parse_task, "tasks.parse_contract", "parse"),
        (dispatcher.submit_review_task, "tasks.run_review", "review"),
        (dispatcher.submit_index_law_task, "tasks.index_law", "index"),
    ])
    def test_submit_celery_mode(self, monkeypatch, submit, task_name, queue):
        sent = []
        monkeypatch.setattr(dispatcher, "current_mode", lambda: "celery")
        monkeypatch.setattr("app.tasks.celery_app.celery_app.send_task",
                            lambda name, args, queue: sent.append((name, args, queue)))
        submit(7)
        assert sent == [(task_name, [7], queue)]

    @pytest.mark.parametrize("submit, func_name", [
        (dispatcher.submit_parse_task, "parse_contract"),
        (dispatcher.submit_review_task, "run_review"),
        (dispatcher.submit_index_law_task, "index_law"),
    ])
    def test_submit_threadpool_mode(self, monkeypatch, submit, func_name):
        calls = []
        monkeypatch.setattr(dispatcher, "current_mode", lambda: "threadpool")
        monkeypatch.setattr(dispatcher, "_run_in_thread", lambda fn, args: calls.append((fn, args)))
        submit(9)
        assert calls == [(func_name, (9,))]

    def test_start_builtin_scheduler_celery_mode(self, monkeypatch):
        monkeypatch.setattr(dispatcher, "current_mode", lambda: "celery")
        dispatcher.start_builtin_scheduler()  # returns directly, does not start a thread

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_start_builtin_scheduler_threadpool(self, monkeypatch):
        import sys
        import time as _time

        monkeypatch.setattr(dispatcher, "current_mode", lambda: "threadpool")
        gate = threading.Event()

        def _gated_sleep(seconds):
            gate.wait(timeout=5)  # block on the gate, waiting for the main thread to release
            sys.exit(0)  # exit after release (pytest records a thread-exception warning, already ignored)

        monkeypatch.setattr(_time, "sleep", _gated_sleep)
        monkeypatch.setattr(schedule_tasks, "recover_stale_task", lambda: 0)
        monkeypatch.setattr(schedule_tasks, "scan_timeout_task", lambda: 0)
        dispatcher.start_builtin_scheduler(interval_seconds=0.01)
        # the thread has started and blocks on the first sleep (daemon thread, no leak on process exit)
        assert any(t.name == "builtin-scheduler" and t.is_alive() and t.daemon
                   for t in threading.enumerate())
        gate.set()  # 放行 → 线程退出

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_builtin_scheduler_loop_body(self, monkeypatch):
        """Loop body: each round recovers zombies; the 6th round (30 min) additionally scans for approval timeouts."""
        import sys
        import time as _time

        monkeypatch.setattr(dispatcher, "current_mode", lambda: "threadpool")
        calls = {"sleeps": 0}
        scanned = threading.Event()

        def _fake_sleep(seconds):
            calls["sleeps"] += 1
            if calls["sleeps"] >= 7:  # 6 轮回收 + 1 次超时扫描后退出
                sys.exit(0)

        monkeypatch.setattr(_time, "sleep", _fake_sleep)
        monkeypatch.setattr(schedule_tasks, "recover_stale_task", lambda: 0)

        def _scan():
            scanned.set()
            return 0

        monkeypatch.setattr(schedule_tasks, "scan_timeout_task", _scan)
        dispatcher.start_builtin_scheduler(interval_seconds=0.001)
        assert scanned.wait(timeout=5)  # the 6th round triggers one timeout scan
        assert calls["sleeps"] >= 7


# ===================== parse_tasks / review_tasks / index_tasks =====================
def _run_task(task_obj, self_ref, *args):
    """Invoke a Celery task body (bypassing PromiseProxy instance binding by passing the stand-in self explicitly)."""
    return task_obj.run.__func__(self_ref, *args)


class TestTaskBodies:
    def test_parse_contract_impl(self, db, monkeypatch):
        called = []
        monkeypatch.setattr("app.services.parse_service.parse_version",
                            lambda db, vid: called.append(vid))
        parse_tasks.parse_contract_impl(db, 5)
        assert called == [5]

    def test_run_review_impl(self, db, monkeypatch):
        called = []
        monkeypatch.setattr("app.services.review_service.run_review",
                            lambda db, tid: called.append(tid))
        review_tasks.run_review_impl(db, 6)
        assert called == [6]

    def test_index_law_impl(self, db, monkeypatch):
        law = helpers.make_law(db)
        db.commit()
        indexed = []
        monkeypatch.setattr("app.services.knowledge_service.index_law",
                            lambda db, law: indexed.append(law.id))
        index_tasks.index_law_impl(db, law.id)
        assert indexed == [law.id]

    def test_index_law_impl_missing(self, db):
        index_tasks.index_law_impl(db, 99999)  # silently returns

    def test_parse_task_retry(self, monkeypatch):
        self_ref = _FakeTaskSelf(retries=0)

        def _boom(db, vid):
            raise RuntimeError("parse down")

        monkeypatch.setattr(parse_tasks, "parse_contract_impl", _boom)
        with pytest.raises(RuntimeError, match="retry scheduled"):
            _run_task(parse_tasks.parse_contract, self_ref, 1)
        assert self_ref.retry_calls[0][1] == 2  # countdown = 2**0*2

    def test_parse_task_max_retries_exceeded(self, monkeypatch):
        class _Exhausted(_FakeTaskSelf):
            def retry(self, exc, countdown):
                raise self.MaxRetriesExceededError()

        self_ref = _Exhausted(retries=3)

        def _boom(db, vid):
            raise RuntimeError("parse down")

        monkeypatch.setattr(parse_tasks, "parse_contract_impl", _boom)
        _run_task(parse_tasks.parse_contract, self_ref, 1)  # does not raise, only logged

    def test_review_task_retry(self, monkeypatch):
        self_ref = _FakeTaskSelf(retries=1)

        def _boom(db, tid):
            raise RuntimeError("review down")

        monkeypatch.setattr(review_tasks, "run_review_impl", _boom)
        with pytest.raises(RuntimeError, match="retry scheduled"):
            _run_task(review_tasks.run_review, self_ref, 1)
        assert self_ref.retry_calls[0][1] == 8  # countdown = 2**1*4

    def test_review_task_max_retries_exceeded(self, monkeypatch):
        class _Exhausted(_FakeTaskSelf):
            def retry(self, exc, countdown):
                raise self.MaxRetriesExceededError()

        self_ref = _Exhausted(retries=2)

        def _boom(db, tid):
            raise RuntimeError("review down")

        monkeypatch.setattr(review_tasks, "run_review_impl", _boom)
        _run_task(review_tasks.run_review, self_ref, 1)

    def test_index_task_retry(self, monkeypatch):
        self_ref = _FakeTaskSelf(retries=0)

        def _boom(db, lid):
            raise RuntimeError("index down")

        monkeypatch.setattr(index_tasks, "index_law_impl", _boom)
        with pytest.raises(RuntimeError, match="retry scheduled"):
            _run_task(index_tasks.index_law, self_ref, 1)
        assert self_ref.retry_calls[0][1] == 8  # countdown = 2**(0+1)*4

    def test_index_task_success(self, monkeypatch):
        called = []
        monkeypatch.setattr(index_tasks, "index_law_impl", lambda db, lid: called.append(lid))
        _run_task(index_tasks.index_law, _FakeTaskSelf(), 3)
        assert called == [3]


# ===================== registry =====================
class TestRegistry:
    def test_task_funcs(self):
        assert set(registry.TASK_FUNCS) == {"parse_contract", "run_review", "index_law"}
        assert all(callable(f) for f in registry.TASK_FUNCS.values())


# ===================== schedule_tasks =====================
class TestScheduleTasks:
    def test_scan_timeout_task(self, monkeypatch):
        monkeypatch.setattr("app.services.workflow_engine.scan_timeout", lambda db: 2)
        assert schedule_tasks.scan_timeout_task() == 2

    def test_recover_stale_task(self, monkeypatch):
        monkeypatch.setattr("app.services.review_service.recover_stale_tasks", lambda db: 1)
        assert schedule_tasks.recover_stale_task() == 1

    def test_scan_timeout_celery(self, monkeypatch):
        monkeypatch.setattr(schedule_tasks, "scan_timeout_task", lambda: 3)
        assert schedule_tasks.scan_timeout_celery() == 3

    def test_recover_stale_celery(self, monkeypatch):
        monkeypatch.setattr(schedule_tasks, "recover_stale_task", lambda: 4)
        assert schedule_tasks.recover_stale_celery() == 4

    def test_scan_timeout_task_closes_session(self, monkeypatch):
        # real SessionLocal (conftest already points at the test DB): the exception path must still close the session
        def _boom(db):
            raise RuntimeError("db down")

        monkeypatch.setattr("app.services.workflow_engine.scan_timeout", _boom)
        with pytest.raises(RuntimeError):
            schedule_tasks.scan_timeout_task()


# ===================== worker_metrics =====================
class TestWorkerMetrics:
    def test_no_port_noop(self, monkeypatch):
        monkeypatch.delenv("WORKER_METRICS_PORT", raising=False)
        worker_metrics.start_metrics_server()  # does not raise

    def test_starts_server_with_port(self, monkeypatch, tmp_path):
        started = []
        monkeypatch.setenv("WORKER_METRICS_PORT", "19191")
        monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
        monkeypatch.setattr("prometheus_client.start_http_server",
                            lambda port, registry=None: started.append(port))
        worker_metrics.start_metrics_server()
        assert started == [19191]

    def test_multiprocess_mode(self, monkeypatch, tmp_path):
        started = []
        collectors = []
        monkeypatch.setenv("WORKER_METRICS_PORT", "19192")
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path / "prom"))
        monkeypatch.setattr("prometheus_client.start_http_server",
                            lambda port, registry=None: started.append(port))
        monkeypatch.setattr("prometheus_client.multiprocess.MultiProcessCollector",
                            lambda registry: collectors.append(registry))
        worker_metrics.start_metrics_server()
        assert started == [19192] and collectors

    def test_failure_swallowed(self, monkeypatch):
        monkeypatch.setenv("WORKER_METRICS_PORT", "not-a-number")
        worker_metrics.start_metrics_server()  # bad port -> only warns

    def test_start_in_background(self, monkeypatch):
        started = []
        monkeypatch.setattr(worker_metrics, "start_metrics_server", lambda: started.append(1))
        worker_metrics.start_in_background()
        import time as _time

        deadline = _time.monotonic() + 2
        while not started and _time.monotonic() < deadline:
            _time.sleep(0.01)
        assert started
