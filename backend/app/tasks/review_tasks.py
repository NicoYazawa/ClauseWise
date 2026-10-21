"""Review task (queue review)."""
from loguru import logger
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.tasks.celery_app import celery_app


def run_review_impl(db: Session, task_id: int) -> None:
    from app.services.review_service import run_review

    run_review(db, task_id)


@celery_app.task(name="tasks.run_review", bind=True, max_retries=2, default_retry_delay=10)
def run_review(self, task_id: int):
    db = SessionLocal()
    try:
        run_review_impl(db, task_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"review task retry: {exc}")
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 4)
        except self.MaxRetriesExceededError:
            logger.error(f"review task exhausted retries for task {task_id}")
    finally:
        db.close()
