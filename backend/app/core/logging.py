"""loguru logging: daily rotation to data/logs/app/, audit logs in a separate dir (design doc 5.5)."""
import sys

from loguru import logger

from app.core.config import settings

_initialized = False


def setup_logging() -> None:
    global _initialized
    if _initialized:
        return
    log_dir = settings.storage_path / "logs" / "app"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", filter=lambda r: r["extra"].get("name") != "audit")
    logger.add(
        log_dir / "app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
        enqueue=False,
        filter=lambda r: r["extra"].get("name") != "audit",  # audit logs go to a separate dir, not mixed into app logs
    )
    _initialized = True
