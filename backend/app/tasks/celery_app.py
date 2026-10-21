"""Celery app (design doc 4.7): parse / review / index queues isolated; --pool=solo on Windows."""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "contract_compliance",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.parse_tasks", "app.tasks.review_tasks", "app.tasks.index_tasks", "app.tasks.schedule_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_default_queue="review",
    task_queues=None,  # declared explicitly via -Q
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Task timeout cap: avoid LLM long chains permanently occupying a worker
    task_time_limit=1800,
    task_soft_time_limit=1500,
    beat_schedule={
        "scan-approval-timeout": {
            "task": "tasks.scan_timeout",
            "schedule": 1800.0,  # 30 minutes
        },
        "recover-stale-tasks": {
            "task": "tasks.recover_stale",
            "schedule": 300.0,  # 5 minutes: recover zombie review/parse tasks left by restart / no worker
        },
    },
)

# Worker metrics port: enabled only when WORKER_METRICS_PORT is set (compose sets it only for the worker service),
# so Prometheus can scrape review/parse metrics executed by the worker.
if settings.worker_metrics_port:
    from app.tasks.worker_metrics import start_in_background

    start_in_background()
