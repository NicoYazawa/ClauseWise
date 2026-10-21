"""Prometheus metrics (application side).

- metric prefix is uniformly ``clausewise_``, distinct from the gateway's ``litellm_*``
- only expose aggregate counts and latency distributions; no contract body or counterparty info (compliance)
- output as text via ``GET /metrics`` for Prometheus scraping (endpoint is not under /api,
  nor exposed via the frontend nginx; only reachable inside the compose network)
"""
import os

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Celery worker is prefork multi-process: child counters are invisible to each other. With this env var set,
# prometheus_client writes counters to a shared dir, aggregated by the worker main process via MultiProcessCollector.
# The dir must exist before creating metric objects.
_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _MULTIPROC_DIR:
    os.makedirs(_MULTIPROC_DIR, exist_ok=True)

# Business terminal-state counts: review / parse
REVIEW_TASKS = Counter("clausewise_review_tasks_total", "审查任务终态计数", ["status"])
REVIEW_DURATION = Histogram(
    "clausewise_review_duration_seconds",
    "审查任务端到端耗时（秒）",
    buckets=(5, 15, 30, 60, 120, 300, 600, 1200),
)
PARSE_TASKS = Counter("clausewise_parse_tasks_total", "合同解析终态计数", ["status"])

# Model calls (model is the gateway alias, very low cardinality)
LLM_CALLS = Counter("clausewise_llm_calls_total", "模型调用计数", ["model", "outcome"])
LLM_LATENCY = Histogram(
    "clausewise_llm_call_seconds",
    "单次模型调用耗时（秒）",
    ["model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 80),
)

# Outbound alerts
ALERTS = Counter("clausewise_alerts_total", "外发告警计数", ["level"])


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
