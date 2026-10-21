"""ES index management (design doc 3.2.6 / 6.1): mappings and initialization for 4 indices.

- legal_knowledge / template_clause / report_index: dense_vector(1024, cosine) + BM25
- contract_index: full-text BM25 retrieval for contracts (no vectors)
- use ik_max_word / ik_smart when the ik plugin is available, otherwise fall back to standard
"""
from loguru import logger

from app.core.config import settings
from app.es.client import get_es_client, has_ik_plugin

INDEX_LEGAL = "legal_knowledge"
INDEX_TEMPLATE = "template_clause"
INDEX_CONTRACT = "contract_index"
INDEX_REPORT = "report_index"

VECTOR_INDICES = (INDEX_LEGAL, INDEX_TEMPLATE, INDEX_REPORT)


def _analyzer_settings() -> dict:
    if has_ik_plugin():
        return {
            "analysis": {
                "analyzer": {
                    "cn_index": {"type": "custom", "tokenizer": "ik_max_word"},
                    "cn_search": {"type": "custom", "tokenizer": "ik_smart"},
                }
            }
        }
    return {}


def _text_props() -> dict:
    if has_ik_plugin():
        return {"type": "text", "analyzer": "cn_index", "search_analyzer": "cn_search"}
    return {"type": "text", "analyzer": "standard", "search_analyzer": "standard"}


def _vector_mapping() -> dict:
    return {
        "properties": {
            "doc_type": {"type": "keyword"},
            "ref_id": {"type": "keyword"},
            "title": _text_props(),
            "content": _text_props(),
            "content_vector": {
                "type": "dense_vector",
                "dims": settings.embedding_dim,
                "index": True,
                "similarity": "cosine",
            },
            "effective_date": {"type": "date", "format": "yyyy-MM-dd||epoch_millis", "ignore_malformed": True},
            "expiry_date": {"type": "date", "format": "yyyy-MM-dd||epoch_millis", "ignore_malformed": True},
            "status": {"type": "keyword"},
            "contract_type": {"type": "keyword"},
            "clause_level": {"type": "keyword"},
            "source_ref": {"type": "keyword"},
        }
    }


def _contract_mapping() -> dict:
    return {
        "properties": {
            "contract_id": {"type": "long"},
            "version_id": {"type": "long"},
            "clause_id": {"type": "long"},
            "contract_no": {"type": "keyword"},
            "title": _text_props(),
            "clause_no": {"type": "keyword"},
            "clause_type": {"type": "keyword"},
            "content": _text_props(),
        }
    }


def ensure_indices() -> bool:
    """Idempotently create the index; returns False when ES is unavailable (search degrades to empty results, does not block the main flow)."""
    es = get_es_client()
    if es is None:
        logger.warning("Elasticsearch 不可用，跳过索引初始化（检索功能将返回空结果）")
        return False
    settings_body = {"settings": {"number_of_shards": 1, "number_of_replicas": 0}}
    ik_settings = _analyzer_settings()
    if ik_settings:
        settings_body["settings"].update(ik_settings)
    for name in VECTOR_INDICES:
        if not es.indices.exists(index=name):
            es.indices.create(index=name, mappings=_vector_mapping(), **settings_body)
            logger.info(f"ES index created: {name}")
    if not es.indices.exists(index=INDEX_CONTRACT):
        es.indices.create(index=INDEX_CONTRACT, mappings=_contract_mapping(), settings=settings_body["settings"])
        logger.info(f"ES index created: {INDEX_CONTRACT}")
    return True


def delete_indices() -> None:
    es = get_es_client()
    if es is None:
        return
    for name in (*VECTOR_INDICES, INDEX_CONTRACT):
        if es.indices.exists(index=name):
            es.indices.delete(index=name)
