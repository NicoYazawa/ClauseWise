"""Elasticsearch client: basic-auth connection + IK analyzer probe."""
from functools import lru_cache

from elasticsearch import Elasticsearch

from app.core.config import settings


@lru_cache
def get_es_client() -> Elasticsearch | None:
    try:
        es = Elasticsearch(
            settings.es_url,
            basic_auth=(settings.es_username, settings.es_password) if settings.es_username else None,
            request_timeout=10,
        )
        if not es.ping():
            return None
        return es
    except Exception:
        return None


@lru_cache
def has_ik_plugin() -> bool:
    """Probe whether the analysis-ik plugin is available (falls back to the standard analyzer if not)."""
    es = get_es_client()
    if es is None:
        return False
    try:
        es.indices.analyze(body={"analyzer": "ik_max_word", "text": "合同违约金"})
        return True
    except Exception:
        return False
