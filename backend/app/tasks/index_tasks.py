"""Knowledge vectorization task (queue: index)."""
from loguru import logger

from app.db.session import SessionLocal
from app.tasks.celery_app import celery_app


def index_law_impl(db, law_id: int) -> None:
    from app.models.knowledge import LawRegulation
    from app.services import knowledge_service

    law = db.get(LawRegulation, law_id)
    if not law:
        return
    knowledge_service.index_law(db, law)


@celery_app.task(bind=True, name="tasks.index_law", max_retries=3, default_retry_delay=8)
def index_law(self, law_id: int):
    db = SessionLocal()
    try:
        index_law_impl(db, law_id)
    except Exception as exc:  # noqa: BLE001
        # Actually trigger Celery retry (the original impl only re-raised the exception, making max_retries moot)
        logger.warning(f"index_law failed ({exc}); retrying")
        raise self.retry(exc=exc, countdown=2 ** (self.request.retries + 1) * 4) from exc
    finally:
        db.close()
