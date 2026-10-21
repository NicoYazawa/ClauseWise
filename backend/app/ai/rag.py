"""RAG retrieval augmentation (design doc 3.2.6): BM25 + kNN hybrid retrieval, RRF fusion.

- Prefer the ES-native rrf retriever (>= 8.14)
- Fall back to _msearch running BM25 and kNN separately, with application-level RRF fusion (score = Σ 1/(20+rank))
- Degrade to pure BM25 when embedding fails (design doc 5.3 fallback)
"""
from datetime import date

from loguru import logger

from app.ai.embedding_client import embed_query
from app.es.client import get_es_client
from app.es.indices import INDEX_CONTRACT, INDEX_LEGAL, INDEX_REPORT, INDEX_TEMPLATE

RANK_CONSTANT = 20
TOP_K = 6


class RagHit:
    def __init__(self, kind: str, ref_id: int, title: str, snippet: str, score: float, source: str = ""):
        self.kind = kind  # law / case / template
        self.ref_id = ref_id
        self.title = title
        self.snippet = snippet
        self.score = score
        self.source = source

    def __repr__(self):
        return f"<RagHit {self.kind}:{self.ref_id} {self.title[:20]} score={self.score:.3f}>"


def _today() -> str:
    return date.today().isoformat()


def _doc_to_hit(doc: dict, fallback_kind: str = "law") -> RagHit | None:
    try:
        kind = doc.get("doc_type", fallback_kind)
        if kind not in ("law", "case"):
            kind = fallback_kind
        return RagHit(
            kind=kind,
            ref_id=int(doc.get("ref_id", 0)),
            title=doc.get("title", ""),
            snippet=doc.get("content", "")[:400],
            score=0.0,
        )
    except Exception:
        return None


def _search_native_rrf(es, index: str, query_text: str, query_vector: list[float] | None, top_k: int) -> list[dict] | None:
    """ES >= 8.14 native RRF retriever."""
    retrievers: list[dict] = [
        {
            "standard": {
                "query": {"multi_match": {"query": query_text, "fields": ["title^2", "content"]}}
            }
        }
    ]
    if query_vector:
        retrievers.append(
            {
                "knn": {
                    "field": "content_vector",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": 100,
                }
            }
        )
    body = {
        "retriever": {"rrf": {"retrievers": retrievers, "rank_constant": RANK_CONSTANT, "size": top_k}}
    }
    try:
        resp = es.search(index=index, **body)
        return [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as e:
        logger.info(f"native RRF unavailable on {index}: {e}")
        return None


def _search_app_rrf(es, index: str, query_text: str, query_vector: list[float] | None, top_k: int) -> list[dict]:
    """Application-level RRF fusion fallback."""
    from elasticsearch.helpers import scan  # noqa: F401  (kept for reference)

    bm25_hits: list[str] = []
    knn_hits: list[str] = []

    body: dict = {
        "query": {"multi_match": {"query": query_text, "fields": ["title^2", "content"]}},
        "size": top_k * 3,
        "_source": False,
    }
    try:
        resp = es.search(index=index, **body)
        bm25_hits = [hit["_id"] for hit in resp["hits"]["hits"]]
    except Exception as e:
        logger.warning(f"BM25 search failed on {index}: {e}")

    if query_vector:
        try:
            knn_body = {
                "knn": {
                    "field": "content_vector",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": 100,
                },
                "size": top_k * 3,
                "_source": False,
            }
            resp = es.search(index=index, **knn_body)
            knn_hits = [hit["_id"] for hit in resp["hits"]["hits"]]
        except Exception as e:
            logger.warning(f"kNN search failed on {index}: {e}")

    scores: dict[str, float] = {}
    for hits in (bm25_hits, knn_hits):
        for rank, doc_id in enumerate(hits, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RANK_CONSTANT + rank)
    if not scores:
        return []
    # sort by fusion score, then fetch _source
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    docs: list[dict] = []
    for doc_id, score in ranked:
        try:
            resp = es.get(index=index, id=doc_id)
            doc = dict(resp["_source"])
            doc["_rrf_score"] = score
            docs.append(doc)
        except Exception:
            continue
    return docs


def hybrid_search_knowledge(query_text: str, top_k: int = TOP_K, *, include_templates: bool = True) -> list[RagHit]:
    """Retrieve laws/cases (+ template clauses), filtering expired knowledge (expiry_date / status)."""
    es = get_es_client()
    if es is None:
        return []
    query_vector: list[float] | None = None
    try:
        query_vector = embed_query(query_text)
    except Exception as e:
        logger.warning(f"query embedding failed, fallback to pure BM25: {e}")

    hits: list[RagHit] = []
    for index, fallback_kind in ((INDEX_LEGAL, "law"), (INDEX_TEMPLATE, "template")):
        if index == INDEX_TEMPLATE and not include_templates:
            continue
        docs = _search_native_rrf(es, index, query_text, query_vector, top_k)
        if docs is None:
            docs = _search_app_rrf(es, index, query_text, query_vector, top_k)
        today = _today()
        for rank, doc in enumerate(docs, start=1):
            # expired-knowledge filter (3.4.2: effective_date / expiry_date policy)
            if doc.get("status") == "expired":
                continue
            exp = doc.get("effective_date")
            if exp and str(exp) > today:
                continue
            expiry = doc.get("expiry_date")
            if expiry and str(expiry) < today:
                continue
            if index == INDEX_TEMPLATE:
                hit = RagHit(
                    kind="template",
                    ref_id=int(doc.get("ref_id", 0)),
                    title=f"企业模板 · {doc.get('title', '')}",
                    snippet=doc.get("content", "")[:400],
                    score=round(1.0 / (RANK_CONSTANT + rank) * 6, 4),
                )
            else:
                hit = _doc_to_hit(doc, fallback_kind)
                if hit is None:
                    continue
                hit.score = round(1.0 / (RANK_CONSTANT + rank) * 6, 4)
            hits.append(hit)
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


def search_contracts(query_text: str, top_k: int = 20) -> list[dict]:
    """Contract full-text BM25 search (contract_index)."""
    es = get_es_client()
    if es is None:
        return []
    body = {
        "query": {"multi_match": {"query": query_text, "fields": ["title^2", "content"]}},
        "size": top_k,
    }
    try:
        resp = es.search(index=INDEX_CONTRACT, **body)
        return [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as e:
        logger.warning(f"contract search failed: {e}")
        return []


def index_report_summary(report_id: int, title: str, summary_text: str) -> str | None:
    """Vectorize a report summary into report_index (design doc 3.2.9); returns es_doc_id."""
    es = get_es_client()
    if es is None:
        return None
    try:
        vector = embed_query(summary_text)
        doc_id = f"report_{report_id}"
        es.index(
            index=INDEX_REPORT,
            id=doc_id,
            document={
                "doc_type": "report",
                "ref_id": report_id,
                "title": title,
                "content": summary_text,
                "content_vector": vector,
                "status": "active",
            },
        )
        return doc_id
    except Exception as e:
        logger.warning(f"report index failed: {e}")
        return None
