"""Alertmanager webhook ingest endpoint: receives Alertmanager webhooks and turns them into IM notifications.

Why not let Alertmanager send to WeCom / DingTalk directly:
each IM bot has a different payload structure ({"msgtype":"markdown",...} etc.) while Alertmanager can only send
fixed JSON. Here we do one translation, reusing the multi-IM adaptation and rate-limiting logic already in app/core/alerting.py,
so "event alerts" and "metric alerts" go through one channel and share one formatting code path.

Auth: Alertmanager cannot carry a JWT, so we use a shared token (ALERT_INGEST_TOKEN),
passed via the ?token= query param or the X-Alert-Token header; when unconfigured the endpoint is disabled.
"""
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from app.core.exceptions import AppError

from app.core.alerting import notify
from app.core.config import settings

router = APIRouter(prefix="/alerts", tags=["运维"])

_LEVELS = {"critical": "critical", "error": "error", "warning": "warning", "info": "info"}


@router.post("/prometheus")
def ingest_prometheus_alerts(
    payload: dict,
    token: Annotated[str | None, Query(description="共享令牌")] = None,
    x_alert_token: Annotated[str | None, Header(alias="X-Alert-Token")] = None,
):
    """Alertmanager Webhook v4 payload -> IM notification. Only handles firing; resolved is ignored."""
    expected = settings.alert_ingest_token
    if not expected:
        raise AppError("ALERT_INGEST_DISABLED", 503, "未配置 ALERT_INGEST_TOKEN：告警回调入口已禁用")
    if (token or x_alert_token or "") != expected:
        raise AppError("ALERT_INVALID_TOKEN", 401, "无效的告警入口令牌")

    alerts = payload.get("alerts") or []
    sent = 0
    for alert in alerts:
        if alert.get("status") != "firing":
            continue
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        name = labels.get("alertname") or "指标告警"
        summary = annotations.get("summary") or ""
        description = annotations.get("description") or ""
        level = _LEVELS.get(str(labels.get("severity", "warning")), "warning")
        title = f"[指标告警] {name}" + (f"：{summary}" if summary else "")
        if notify(
            title,
            description or summary or "（无描述）",
            level=level,
            key=alert.get("fingerprint") or name,
        ):
            sent += 1
    return {"received": len(alerts), "sent": sent}
