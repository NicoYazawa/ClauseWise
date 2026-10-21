"""Operation audit (design doc 3.5.4): INSERT-ONLY; writes to MySQL audit_log and a separate file under data/logs/audit/."""
import json
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import AuditLog

_audit_logger = None


def _get_audit_logger():
    global _audit_logger
    if _audit_logger is None:
        from loguru import logger as _lg

        audit_dir = settings.storage_path / "logs" / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        # Dedicated sink: only accepts logs bound with name="audit".
        # Note: must NOT call remove(): loguru sinks are shared globally; remove() would also drop the app sink configured in setup_logging.
        _lg.add(
            audit_dir / "audit_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="3 years",
            level="INFO",
            encoding="utf-8",
            filter=lambda record: record["extra"].get("name") == "audit",
        )
        _audit_logger = _lg.bind(name="audit")
    return _audit_logger


def write_audit(
    db: Session,
    *,
    user_id: int | None,
    username: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ip: str = "-",
    ua: str = "-",
    result: str = "成功",
    extra: str | None = None,
) -> None:
    detail = {"ip": ip, "ua": ua, "result": result}
    if extra:
        detail["extra"] = extra
    log = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        detail=detail,
        created_at=datetime.now(),
    )
    db.add(log)
    db.commit()
    try:
        _get_audit_logger().info(
            json.dumps(
                {
                    "username": username,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id),
                    "detail": detail,
                },
                ensure_ascii=False,
            )
        )
    except Exception as e:  # audit file failure must not affect the main flow
        logger.warning(f"audit file write failed: {e}")
