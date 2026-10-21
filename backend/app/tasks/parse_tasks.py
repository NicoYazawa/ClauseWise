"""Parse task (queue parse): Celery task + thread-pool shared task body. max_retries=3 exponential backoff is guaranteed by both the LLM layer and the dispatch layer."""
from loguru import logger
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.tasks.celery_app import celery_app


def parse_contract_impl(db: Session, version_id: int) -> None:
    from app.services.parse_service import parse_version

    parse_version(db, version_id)


@celery_app.task(name="tasks.parse_contract", bind=True, max_retries=3, default_retry_delay=8)
def parse_contract(self, version_id: int):
    db = SessionLocal()
    try:
        parse_contract_impl(db, version_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"parse task retry: {exc}")
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 2)
        except self.MaxRetriesExceededError:
            logger.error(f"parse task exhausted retries for version {version_id}")
    finally:
        db.close()
