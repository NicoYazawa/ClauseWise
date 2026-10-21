"""Embedding-model client (design doc 4.3): OpenAI-compatible protocol, real calls.

Vendor resolution lives in ``app/ai/providers.py``; defaults to DashScope text-embedding-v4 (1024 dims):

- batches <= 10 per call (conservative cap of compatible APIs)
- token-bucket rate limit (default 900 RPM, half of DashScope's official 1800)
- exponential backoff on 429/timeout
- dimensions sent only when the vendor supports it (self-hosted models like bge-m3 reject the param)

Note: after switching the embedding model you MUST rebuild the ES index (dense_vector.dims in
app/es/indices.py and the vector space are both bound to the model), otherwise retrieval silently breaks.
"""
import threading
import time

from loguru import logger
from openai import APIStatusError, OpenAI

from app.ai.providers import ModelConfigError, embedding_endpoint

_client: OpenAI | None = None
_client_sig: str | None = None
_lock = threading.Lock()

# token bucket: 900 RPM = 15 req/s
_RATE = 15.0
_bucket = _RATE
_last_refill = time.monotonic()
_bucket_lock = threading.Lock()


class EmbeddingError(Exception):
    pass


def _is_fatal(e: Exception) -> bool:
    """Auth/permission errors are not worth retrying (keys won't recover on retry); fail immediately."""
    if isinstance(e, APIStatusError):
        return e.status_code in (401, 403)
    return False


def get_embedding_client() -> OpenAI:
    """Create client from the current vendor endpoint; auto-rebuild on endpoint change."""
    global _client, _client_sig
    try:
        endpoint = embedding_endpoint()
    except ModelConfigError as e:
        raise EmbeddingError(f"向量模型配置错误：{e}") from e
    if endpoint.requires_api_key and not endpoint.api_key:
        raise EmbeddingError(
            f"未配置 {endpoint.api_key_env or 'EMBEDDING_API_KEY'}（当前厂商 {endpoint.provider}），"
            "无法调用向量化模型（仅真实 API 模式）"
        )
    signature = f"{endpoint.base_url}|{endpoint.model}"
    if _client is None or _client_sig != signature:
        with _lock:
            if _client is None or _client_sig != signature:
                _client = OpenAI(
                    api_key=endpoint.key_or_placeholder,
                    base_url=endpoint.base_url,
                )
                _client_sig = signature
                logger.info(f"Embedding endpoint ready: {endpoint.label} @ {endpoint.base_url}")
    return _client


def _acquire_token() -> None:
    global _bucket, _last_refill
    with _bucket_lock:
        now = time.monotonic()
        _bucket = min(_RATE, _bucket + (now - _last_refill) * _RATE)
        _last_refill = now
        if _bucket >= 1:
            _bucket -= 1
            return
    time.sleep(1.0 / _RATE)
    _acquire_token()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embedding (<= 10 per batch); returns a vector list equal in length to the input."""
    if not texts:
        return []
    client = get_embedding_client()
    endpoint = embedding_endpoint()
    results: list[list[float]] = []
    batch_size = 10
    for i in range(0, len(texts), batch_size):
        batch = [t[:6000] for t in texts[i : i + batch_size]]
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                _acquire_token()
                kwargs: dict = {"model": endpoint.model, "input": batch, "timeout": 60}
                if endpoint.send_dimensions and endpoint.dimensions:
                    kwargs["dimensions"] = endpoint.dimensions
                resp = client.embeddings.create(**kwargs)
                data = sorted(resp.data, key=lambda d: d.index)
                results.extend(d.embedding for d in data)
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if _is_fatal(e):
                    logger.error(f"embedding call failed (不可重试的认证/权限错误): {e}")
                    raise EmbeddingError(f"向量化调用失败（密钥或权限无效）：{e}") from e
                wait = 2**attempt
                logger.warning(f"embedding call failed (attempt {attempt}/3): {e}; retry in {wait}s")
                time.sleep(wait)
        if last_err is not None:
            raise EmbeddingError(f"向量化调用连续失败：{last_err}")
    return results


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
