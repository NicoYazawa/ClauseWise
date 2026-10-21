"""Outbound alerting for critical events: task failure / parse failure pushed to a webhook.

Design notes:
- Zero new dependencies: send via the stdlib urllib
- Synchronous send (5s timeout): a daemon thread would be dropped on process exit (alerts lost in practice),
  yet alerts precisely occur on the task-failure path where the process may terminate, so reliability wins;
  only the failure path pays this small latency
- Auto-adapt payload format by URL: WeCom / DingTalk / Feishu bot / generic JSON (self-hosted receiver, Slack proxy, etc.)
- Per-key rate limit (default 5 min): Celery retries and batch failures won't flood
- Any send exception is only logged and never affects the task's state machine or return value
- Disabled by default (ALERT_ENABLED=false); calls return False immediately when no URL is configured

Config keys in app/core/config.py: ALERT_ENABLED / ALERT_WEBHOOK_URL /
ALERT_MIN_INTERVAL_SECONDS / ALERT_SERVICE_NAME.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from datetime import datetime

from loguru import logger

from app.core.config import settings

_lock = threading.Lock()
_last_sent: dict[str, float] = {}
_TIMEOUT = 5


def _build_payload(url: str, title: str, content: str, level: str) -> dict:
    """Assemble payload by bot type; fall back to generic JSON when unrecognized."""
    text = f"【{settings.alert_service_name}】{title}\n{content}"
    if "qyapi.weixin.qq.com" in url:  # WeCom bot
        return {"msgtype": "markdown", "markdown": {"content": text}}
    if "oapi.dingtalk.com" in url:  # DingTalk bot
        return {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    if "open.feishu.cn" in url or "open.larksuite.com" in url:  # Feishu bot
        return {"msg_type": "text", "content": {"text": text}}
    return {  # generic format: self-hosted receiver / Slack-compatible proxy
        "title": title,
        "content": content,
        "level": level,
        "service": settings.alert_service_name,
        "host": socket.gethostname(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def _post(url: str, payload: dict) -> None:
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.status >= 300:
                logger.warning(f"alert webhook returned HTTP {resp.status}")
    except Exception as e:  # noqa: BLE001  alert failure must not affect the business
        logger.warning(f"alert webhook failed: {e}")


def notify(title: str, content: str, *, level: str = "error", key: str | None = None) -> bool:
    """Send an alert (background thread, non-blocking). Returns whether it was actually submitted (False when rate-limited or disabled)."""
    if not settings.alert_enabled or not settings.alert_webhook_url:
        return False
    dedup = key or title
    now = time.monotonic()
    with _lock:
        last_sent = _last_sent.get(dedup)
        if last_sent is not None and now - last_sent < settings.alert_min_interval_seconds:
            logger.info(f"alert suppressed by rate limit: {dedup}")
            return False
        _last_sent[dedup] = now
    payload = _build_payload(settings.alert_webhook_url, title, content, level)
    _post(settings.alert_webhook_url, payload)
    logger.info(f"alert sent: [{level}] {title}")
    try:
        from app.core.metrics import ALERTS

        ALERTS.labels(level=level).inc()
    except Exception:  # noqa: BLE001
        pass
    return True


def notify_task_failure(kind: str, ref_id: int, subject: str, error: object) -> bool:
    """Unified task-failure alert: review / parse."""
    label = {"review": "AI 审查", "parse": "合同解析"}.get(kind, kind)
    return notify(
        title=f"{label}任务失败 #{ref_id}",
        content=f"对象：{subject}\n错误：{str(error)[:300]}",
        level="error",
        key=f"{kind}:{ref_id}",
    )
