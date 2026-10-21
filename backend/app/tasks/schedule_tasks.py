"""Scheduled tasks (Celery Beat / built-in thread in fallback mode): approval-timeout scan & reminder (design doc 3.3.1) + zombie review/parse task recovery."""
from loguru import logger

from app.db.session import SessionLocal
from app.tasks.celery_app import celery_app


def scan_timeout_task() -> int:
    from app.services.workflow_engine import scan_timeout

    db = SessionLocal()
    try:
        n = scan_timeout(db)
        if n:
            logger.info(f"scan_timeout: {n} instances urged")
        return n
    finally:
        db.close()


@celery_app.task(name="tasks.scan_timeout")
def scan_timeout_celery():
    return scan_timeout_task()


def recover_stale_task() -> int:
    """Zombie task recovery: long-pending/running review tasks and parsing versions -> marked failed and the contract status rolled back."""
    from app.services.review_service import recover_stale_tasks

    db = SessionLocal()
    try:
        n = recover_stale_tasks(db)
        if n:
            logger.info(f"recover_stale: {n} stale tasks recovered")
        return n
    finally:
        db.close()


@celery_app.task(name="tasks.recover_stale")
def recover_stale_celery():
    return recover_stale_task()
