"""FastAPI entrypoint (design docs 2.2 / 4.7): router mounting / GZip / CORS / static hosting / health check."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1.router import api_router
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.config import settings
    settings.validate_security()
    setup_logging()
    # Startup-enforced preflight: if MySQL / ES / Redis / DeepSeek / BaiLian is unready, print report then exit (no degraded start)
    from app.core.preflight import enforce_preflight

    enforce_preflight()
    from app.db.security_upgrade import (
        harden_legacy_accounts,
        migrate_legacy_reports,
        seed_preset_accounts,
        sync_permissions,
        upgrade_schema,
    )
    from app.db.session import SessionLocal, engine

    upgrade_schema(engine)
    with SessionLocal() as session:
        harden_legacy_accounts(session, bootstrap_password=settings.bootstrap_admin_password)
        sync_permissions(session)
        seed_preset_accounts(session)  # Seed or revoke preset accounts based on the configured switches
        migrate_legacy_reports(session)
    # ES index init (unavailability does not block startup)
    try:
        from app.es.indices import ensure_indices

        ensure_indices()
    except Exception as e:
        logger.warning(f"ES index init skipped: {e}")
    # Startup recovery: reclaim zombie review/parse tasks left from the last run (self-heal after a service restart interruption)
    try:
        from app.db.session import SessionLocal
        from app.services.review_service import recover_stale_tasks

        db = SessionLocal()
        try:
            recovered = recover_stale_tasks(db)
            if recovered:
                logger.info(f"startup recovered {recovered} stale task(s)")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"startup recover skipped: {e}")
    # Built-in timer in fallback mode (zombie task recovery + timeout reminder scan)
    try:
        from app.tasks.dispatcher import start_builtin_scheduler

        start_builtin_scheduler()
    except Exception as e:
        logger.warning(f"builtin scheduler skipped: {e}")
    yield


app = FastAPI(
    title="AI智能合同合规审查平台 API",
    version="1.0.0",
    description="FastAPI 模块化单体 · LangGraph 多 Agent 协作 · DeepSeek 审查 · 百炼向量化 · ES 混合检索 · 审批工作流",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["运维"])
def health():
    """Health check: MySQL / Redis / ES / model API connectivity and task dispatch mode (design doc 5.5)."""
    result: dict = {"status": "ok"}

    # MySQL
    try:
        from sqlalchemy import text

        from app.db.session import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        result["mysql"] = "up"
    except Exception as e:
        result["mysql"] = f"down: {str(e)[:80]}"

    # Redis / task dispatch mode (celery needs Redis + Worker both available, otherwise auto-degrade to in-process thread pool)
    try:
        from app.tasks.dispatcher import current_mode, redis_available

        result["task_mode"] = current_mode()
        if result["task_mode"] == "celery":
            result["redis"] = "up"
            result["worker"] = "up"
        else:
            redis_up = redis_available()
            result["redis"] = "up" if redis_up else "down"
            result["worker"] = (
                "down（已降级进程内线程池，任务异步执行不受影响）" if redis_up else "-"
            )
    except Exception as e:
        result["redis"] = f"down: {str(e)[:80]}"
        result["task_mode"] = "unknown"

    # Elasticsearch
    try:
        from app.es.client import get_es_client

        es = get_es_client()
        result["elasticsearch"] = "up" if es is not None else "down"
    except Exception as e:
        result["elasticsearch"] = f"down: {str(e)[:80]}"

    # Model vendor (follows .env; auto-updates after switching vendors, convenient to confirm the actually active model)
    from app.ai.providers import ModelConfigError, embedding_endpoint, llm_endpoint

    for key, resolver in (("llm", llm_endpoint), ("embedding", embedding_endpoint)):
        try:
            ep = resolver()
            configured = bool(ep.api_key) or not ep.requires_api_key
            result[key] = f"{ep.provider}:{ep.model}" + ("" if configured else "（未配置密钥）")
        except ModelConfigError as e:
            result[key] = f"config error: {e}"

    if any(str(v).startswith("down") for k, v in result.items() if k in ("mysql",)):
        result["status"] = "degraded"
    return result


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Prometheus metrics (text format): business terminal counts, model call latency, alert counts.

    Only reachable inside the compose network (nginx only proxies /api and /health); not exposed externally.
    """
    from app.core.metrics import metrics_response

    return metrics_response()


# Serve frontend build artifacts from same origin (when frontend/dist exists)
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="spa")
