"""Celery Worker metrics port.

Background: review / parse tasks run in the Celery worker, whose counters live outside the API process;
scraping only the API's /metrics would miss most business metrics. The worker doesn't listen on HTTP like
the API, so here we spin up a minimal HTTP server exposing /metrics.

Under prefork concurrency each child process has isolated counters, so we enable prometheus_client
multi-process mode:
- env var PROMETHEUS_MULTIPROC_DIR points to a shared dir (ensured by app/core/metrics.py)
- child processes write counters into that dir
- this server aggregates them via MultiProcessCollector in the main process

Usage: set WORKER_METRICS_PORT=9100 on the worker container to auto-enable; when unset this module is a no-op
(API / beat containers won't open an extra port).
"""
import os
import threading


def start_metrics_server() -> None:
    port_raw = os.environ.get("WORKER_METRICS_PORT", "")
    if not port_raw:
        return
    try:
        # Shared dir must exist first, otherwise MultiProcessCollector init fails immediately
        multiproc = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if multiproc:
            os.makedirs(multiproc, exist_ok=True)

        from prometheus_client import CollectorRegistry, start_http_server

        registry = CollectorRegistry()
        if multiproc:
            from prometheus_client.multiprocess import MultiProcessCollector

            MultiProcessCollector(registry)
        start_http_server(int(port_raw), registry=registry)
        # Log startup (lazy-import loguru to avoid affecting API-side import cost)
        from loguru import logger

        logger.info(f"worker metrics server started on :{port_raw}")
    except Exception as e:  # noqa: BLE001  metrics port failure must not affect task execution
        from loguru import logger

        logger.warning(f"worker metrics server skipped: {e}")


def start_in_background() -> None:
    threading.Thread(target=start_metrics_server, daemon=True, name="worker-metrics").start()
