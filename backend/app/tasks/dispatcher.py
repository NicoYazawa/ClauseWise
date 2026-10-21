"""Task dispatch abstraction (design docs 2.2 / 4.7):

- Redis available -> Celery (parse / review / index queues isolated; Windows worker uses --pool=solo)
- Redis unavailable -> in-process ThreadPoolExecutor runs the same task functions (single-node equivalent)
- /health reports the current mode
"""
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from app.core.config import settings
from app.db.session import SessionLocal

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_mode: str | None = None
_mode_decided_at: float = 0.0
_MODE_TTL_SECONDS = 60.0  # dispatch-mode decision cache: Worker start/stop is reflected within at most 60s


def _detect_redis(host: str = "127.0.0.1", port: int = 6379, timeout: float = 1.5) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _detect_worker(timeout: float = 2.0) -> bool:
    """Celery Worker liveness probe (inspect ping): when Redis is up but the Worker isn't started, fall back to thread pool.

    Note: since Celery 5.6 ``Inspect.ping()`` no longer accepts the ``timeout`` keyword (timeout is passed via
    ``control.inspect(timeout=...)``); the old写法 (passing timeout on ping()) would throw TypeError and always be
    judged as "Worker not started". Here we support both old and new signatures.
    """
    try:
        from app.tasks.celery_app import celery_app

        try:
            pong = celery_app.control.inspect(timeout=timeout).ping()
        except TypeError:  # Celery < 5.6: timeout param is on ping()
            pong = celery_app.control.inspect().ping(timeout=timeout)
        return bool(pong)
    except Exception:  # noqa: BLE001
        return False


def redis_available() -> bool:
    from urllib.parse import urlparse

    u = urlparse(settings.redis_url)
    host = u.hostname or "127.0.0.1"
    port = u.port or 6379
    return _detect_redis(host, port)


def current_mode() -> str:
    """celery (Redis + Worker both available) / threadpool (fallback: Redis unavailable or Worker not started)."""
    global _mode, _mode_decided_at
    now = time.monotonic()
    if _mode is None or now - _mode_decided_at > _MODE_TTL_SECONDS:
        decided = "celery" if (redis_available() and _detect_worker()) else "threadpool"
        if decided != _mode:
            logger.info(f"task dispatcher mode: {decided}")
        _mode = decided
        _mode_decided_at = now
    return _mode


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="task")
    return _executor


def _run_in_thread(func_name: str, args: tuple) -> None:
    def _wrapper():
        db = SessionLocal()
        try:
            from app.tasks import registry

            fn = registry.TASK_FUNCS[func_name]
            fn(db, *args)
        except Exception as e:  # noqa: BLE001
            logger.error(f"task {func_name}{args} failed: {e}")
        finally:
            db.close()

    _get_executor().submit(_wrapper)


def submit_parse_task(version_id: int) -> None:
    """Submit a parse task."""
    if current_mode() == "celery":
        from app.tasks.celery_app import celery_app

        celery_app.send_task("tasks.parse_contract", args=[version_id], queue="parse")
    else:
        _run_in_thread("parse_contract", (version_id,))


def submit_review_task(task_id: int) -> None:
    """Submit a review task."""
    if current_mode() == "celery":
        from app.tasks.celery_app import celery_app

        celery_app.send_task("tasks.run_review", args=[task_id], queue="review")
    else:
        _run_in_thread("run_review", (task_id,))


def submit_index_law_task(law_id: int) -> None:
    """Submit a knowledge-vectorization task."""
    if current_mode() == "celery":
        from app.tasks.celery_app import celery_app

        celery_app.send_task("tasks.index_law", args=[law_id], queue="index")
    else:
        _run_in_thread("index_law", (law_id,))


def start_builtin_scheduler(interval_seconds: int = 300) -> None:
    """Built-in scheduler thread in fallback mode (not needed when Celery Beat is available):

    - every 5 minutes: recover zombie tasks (long-pending/running reviews, parsing -> failed, retryable)
    - every 30 minutes: scan approval timeouts and send reminders (keep original cadence to avoid duplicate reminders)
    """
    if current_mode() == "celery":
        return

    def _loop():
        import time

        from app.tasks.schedule_tasks import recover_stale_task, scan_timeout_task

        rounds = 0
        while True:
            time.sleep(interval_seconds)
            try:
                recover_stale_task()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"builtin recover_stale failed: {e}")
            rounds += 1
            if rounds % 6 == 0:  # 300s x 6 = 30 minutes
                try:
                    scan_timeout_task()
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"builtin scan_timeout failed: {e}")

    threading.Thread(target=_loop, daemon=True, name="builtin-scheduler").start()
    logger.info(f"builtin scheduler started (interval {interval_seconds}s)")
