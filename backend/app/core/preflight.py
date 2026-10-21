"""Startup preflight: core-component readiness checks; any failure aborts the process.

Checks (all real probes, not config-only):
- MySQL              real connect + SELECT 1
- Elasticsearch      client ping + cluster info
- Redis              real connect + PING (Celery Broker)
- Chat model         current vendor endpoint + key + models.list connectivity
- Embedding model    current vendor endpoint + key + models.list connectivity
                     (falls back to config-only check when the list API is unavailable)

The model vendor is decided by env vars (see app/ai/providers.py); switching vendors auto-follows here.

Entry points: app/main.py lifespan calls enforce_preflight() first;
or run standalone for preflight only (no service start):
    python -m app.core.preflight
"""
import sys

from app.ai.providers import ModelConfigError, embedding_endpoint, llm_endpoint
from app.core.config import settings


def _brief(e: Exception, limit: int = 140) -> str:
    return str(e).replace("\n", " ")[:limit]


# ===================== Component checks =====================


def check_mysql() -> tuple[bool, str]:
    try:
        from sqlalchemy import text

        from app.db.session import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database} 连接正常"
    except Exception as e:  # noqa: BLE001
        return False, f"无法连接 {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}：{_brief(e)}"


def check_elasticsearch() -> tuple[bool, str]:
    try:
        from app.es.client import get_es_client

        es = get_es_client()
        if es is None:
            return False, f"集群不可达或认证失败：{settings.es_url}"
        info = es.info()
        version = (info.get("version") or {}).get("number", "?")
        return True, f"{settings.es_url} 可达（Elasticsearch {version}）"
    except Exception as e:  # noqa: BLE001
        return False, f"集群探测失败 {settings.es_url}：{_brief(e)}"


def check_redis() -> tuple[bool, str]:
    try:
        import redis as redis_lib

        r = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
        r.ping()
        return True, f"{settings.redis_url} 可达（Celery Broker，PING 通过）"
    except Exception as e:  # noqa: BLE001
        return False, f"无法连接 {settings.redis_url}：{_brief(e)}（请启动 Redis/Memurai 服务）"


def _probe(endpoint, label: str, suffix: str = "") -> tuple[bool, str]:
    """Endpoint connectivity probe: API key required but missing -> fail immediately; otherwise probe via models.list()."""
    if endpoint.requires_api_key and not endpoint.api_key:
        return False, f"未配置 {endpoint.api_key_env or 'API_KEY'}（当前厂商 {endpoint.provider}）"
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=endpoint.key_or_placeholder, base_url=endpoint.base_url, timeout=10
        )
        client.models.list()
        return True, f"{label} {endpoint.label} 连通（{endpoint.base_url}）{suffix}"
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # Some compat gateways don't implement /v1/models (auth passed the network layer); fall back to config-only pass
        if "404" in msg or "405" in msg or "not found" in msg.lower():
            return True, f"{label} {endpoint.label} 已配置（列举接口不可用，跳过实测）{suffix}"
        return False, f"{label} {endpoint.label} 调用失败：{_brief(e)}（检查密钥 / BASE_URL / 网络）"


def check_llm() -> tuple[bool, str]:
    try:
        endpoint = llm_endpoint()
    except ModelConfigError as e:
        return False, f"对话模型配置错误：{e}"
    return _probe(endpoint, "对话模型")


def check_embedding() -> tuple[bool, str]:
    try:
        endpoint = embedding_endpoint()
    except ModelConfigError as e:
        return False, f"向量模型配置错误：{e}"
    return _probe(endpoint, "向量模型", f"（{endpoint.dimensions}d）")


# ===================== Report & enforcement =====================

CHECKS = [
    ("MySQL 数据库", check_mysql),
    ("Elasticsearch", check_elasticsearch),
    ("Redis", check_redis),
    ("对话模型", check_llm),
    ("向量模型", check_embedding),
]


def run_preflight_checks() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"检测异常：{_brief(e)}"
        results.append((name, ok, detail))
    return results


def _print_report(results: list[tuple[str, bool, str]]) -> bool:
    all_ok = all(ok for _, ok, _ in results)
    print("=" * 68, flush=True)
    print("启动预检（Preflight）：核心组件就绪检查", flush=True)
    print("-" * 68, flush=True)
    for name, ok, detail in results:
        tag = "[OK]  " if ok else "[FAIL]"
        print(f"{tag} {name}：{detail}", flush=True)
    print("-" * 68, flush=True)
    passed = sum(1 for _, ok, _ in results if ok)
    if all_ok:
        print(f"预检通过（{passed}/{len(results)}），继续启动 API 服务…", flush=True)
    else:
        print(
            f"预检未通过（{passed}/{len(results)}）：请先修复上方 [FAIL] 项"
            "（检查对应服务是否启动、backend/.env 密钥配置），进程即将退出。",
            flush=True,
        )
    print("=" * 68, flush=True)
    return all_ok


def enforce_preflight() -> None:
    """Startup-enforced preflight.

    - ``preflight_strict=True`` (default): any component not ready -> print report and terminate the process.
    - ``preflight_strict=False`` (container/demo env): only MySQL is fatal; other components degrade to warnings,
      so the service can still start without model keys configured (review/QA features will be unavailable).
    """
    results = run_preflight_checks()
    all_ok = _print_report(results)
    if all_ok:
        return

    failed = [name for name, ok, _ in results if not ok]
    fatal = failed if settings.preflight_strict else [n for n in failed if n.startswith("MySQL")]
    if not fatal:
        try:
            from loguru import logger

            logger.warning(f"启动预检部分未通过（非致命，降级运行）：{'、'.join(failed)}")
        except Exception:  # noqa: BLE001  ignore if logging unavailable; report already printed
            pass
        return
    try:
        from loguru import logger

        logger.error(f"启动预检未通过，已终止：{'、'.join(fatal)}")
    except Exception:  # noqa: BLE001  ignore if logging unavailable; report already printed
        pass
    raise SystemExit(1)


if __name__ == "__main__":
    ok = _print_report(run_preflight_checks())
    sys.exit(0 if ok else 1)
