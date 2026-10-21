"""Chat-model client (design doc 4.2): OpenAI-compatible protocol, real calls, no Mock fallback.

Vendor resolution lives in ``app/ai/providers.py``; this module only does the calling:

- Text review: temperature=0.1, carries response_format json_object when supported
- Vision OCR: base64 image input (scanned-doc parse channel; LLM_VISION_MODEL can override the model)
- 3 attempts of exponential backoff; auto-degrade to pure prompt constraints when a non-standard vendor lacks json mode
"""
import json
import re
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from app.core.exceptions import AppError
from loguru import logger
from openai import APIStatusError, OpenAI

from app.ai.providers import ModelConfigError, llm_endpoint, vision_endpoint
from app.core.config import settings

_client: OpenAI | None = None
_client_sig: str | None = None
_client_lock = threading.Lock()
# Track vendor endpoints that don't support response_format (disabled after first 400, avoid retrying every call)
_json_unsupported: set[str] = set()
# Global concurrency semaphore (<= N parallel; overflow queues to avoid model API rate limits)
_sem = threading.Semaphore(settings.llm_concurrency)
_pool = ThreadPoolExecutor(max_workers=settings.llm_concurrency, thread_name_prefix="llm")


class LLMError(Exception):
    pass


def _is_fatal(e: Exception) -> bool:
    """Auth/permission errors are not worth retrying (keys won't recover on retry); fail immediately."""
    if isinstance(e, APIStatusError):
        return e.status_code in (401, 403)
    return False


def get_llm_client() -> OpenAI:
    """Create client from the current vendor endpoint; auto-rebuild on endpoint change (hot config switch)."""
    global _client, _client_sig
    try:
        endpoint = llm_endpoint()
    except ModelConfigError as e:
        raise LLMError(f"对话模型配置错误：{e}") from e
    if endpoint.requires_api_key and not endpoint.api_key:
        raise LLMError(
            f"未配置 {endpoint.api_key_env or 'LLM_API_KEY'}（当前厂商 {endpoint.provider}），"
            "无法调用审查模型（仅真实 API 模式）"
        )
    signature = f"{endpoint.base_url}|{endpoint.model}"
    if _client is None or _client_sig != signature:
        with _client_lock:
            if _client is None or _client_sig != signature:
                _client = OpenAI(
                    api_key=endpoint.key_or_placeholder,
                    base_url=endpoint.base_url,
                )
                _client_sig = signature
                logger.info(f"LLM endpoint ready: {endpoint.label} @ {endpoint.base_url}")
    return _client


def current_model() -> str:
    """Currently active model name (for task persistence / report tracing)."""
    try:
        return llm_endpoint().model
    except ModelConfigError:
        return settings.llm_model


def _record_call(model: str, outcome: str, elapsed: float) -> None:
    """Record model call metrics; metric failures never affect the call chain."""
    try:
        from app.core.metrics import LLM_CALLS, LLM_LATENCY

        LLM_CALLS.labels(model=model, outcome=outcome).inc()
        LLM_LATENCY.labels(model=model).observe(elapsed)
    except Exception:  # noqa: BLE001
        pass


def _is_json_mode_rejection(e: Exception) -> bool:
    """Detect whether a 400/422 is caused by unsupported response_format (some vendors/proxies don't implement it)."""
    if not isinstance(e, APIStatusError) or e.status_code not in (400, 422):
        return False
    text = str(e).lower()
    return "response_format" in text or "json_object" in text or "not support" in text or "unsupported" in text


def _chat_with_retry(
    messages: list[dict],
    *,
    json_mode: bool = False,
    retries: int = 3,
    model: str | None = None,
) -> tuple[str, int]:
    client = get_llm_client()
    endpoint = llm_endpoint()
    target_model = model or endpoint.model
    use_json_mode = bool(json_mode and endpoint.json_mode and target_model not in _json_unsupported)
    attempt = 0
    last_err: Exception | None = None
    while attempt < retries:
        attempt += 1
        kwargs: dict = {
            "model": target_model,
            "temperature": 0.1,
            "messages": messages,
            "timeout": 120,
        }
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        t_start = time.monotonic()
        try:
            with _sem:
                resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or ""
            tokens = 0
            if resp.usage:
                tokens = (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
            _record_call(target_model, "ok", time.monotonic() - t_start)
            return content, tokens
        except Exception as e:  # noqa: BLE001
            last_err = e
            _record_call(target_model, "error", time.monotonic() - t_start)
            # Vendor rejects response_format: disable the param and retry immediately (not counted as a retry)
            if use_json_mode and _is_json_mode_rejection(e):
                logger.warning(
                    f"{target_model} 不支持 response_format，已降级为提示词约束（{str(e)[:120]}）"
                )
                _json_unsupported.add(target_model)
                use_json_mode = False
                attempt -= 1
                continue
            if _is_fatal(e):
                logger.error(f"LLM call failed (不可重试的认证/权限错误): {e}")
                raise LLMError(f"模型调用失败（密钥或权限无效）：{e}") from e
            wait = 2**attempt  # 2s / 4s / 8s
            logger.warning(f"LLM call failed (attempt {attempt}/{retries}): {e}; retry in {wait}s")
            time.sleep(wait)
    raise LLMError(f"模型调用连续 {retries} 次失败：{last_err}")


def _loads_json(content: str) -> dict:
    """Leniently parse model output: tolerate ```json fences and leading/trailing prose."""
    cleaned = re.sub(r"```(?:json)?", "", str(content)).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def chat_json(system_prompt: str, user_prompt: str) -> tuple[dict, int]:
    """Structured JSON-output call; returns (parsed_json, tokens)."""
    content, tokens = _chat_with_retry(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        json_mode=True,
    )
    try:
        return _loads_json(content), tokens
    except (json.JSONDecodeError, ValueError) as e:
        raise LLMError(f"模型输出 JSON 解析失败：{e}；原始输出前 200 字：{content[:200]}") from e


def chat_text(system_prompt: str, user_prompt: str) -> tuple[str, int]:
    """Plain-text output call (Q&A / diff summarization)."""
    return _chat_with_retry(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    )


def chat_text_stream(system_prompt: str, user_prompt: str, *, retries: int = 3) -> Iterator[str]:
    """Streaming text generation (per-char Q&A output): yields incremental chunks in order.

    Retry policy: only retry when nothing has been produced yet (stream-open failure / pre-first-chunk error);
    once content has been produced, an interruption is raised directly to avoid pushing duplicate text to the caller.
    """
    client = get_llm_client()
    endpoint = llm_endpoint()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        produced = False
        try:
            with _sem:
                stream = client.chat.completions.create(
                    model=endpoint.model,
                    temperature=0.1,
                    messages=messages,
                    timeout=120,
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    piece = chunk.choices[0].delta.content
                    if piece:
                        produced = True
                        yield piece
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            if produced:
                raise LLMError(f"模型流式输出中断：{e}") from e
            if _is_fatal(e):
                logger.error(f"LLM stream call failed (不可重试的认证/权限错误): {e}")
                raise LLMError(f"模型调用失败（密钥或权限无效）：{e}") from e
            wait = 2 ** attempt  # 2s / 4s / 8s
            logger.warning(f"LLM stream call failed (attempt {attempt}/{retries}): {e}; retry in {wait}s")
            time.sleep(wait)
    raise LLMError(f"模型流式调用连续 {retries} 次失败：{last_err}")


def vision_extract_clauses(image_b64: str, mime: str = "image/png", prompt: str | None = None) -> tuple[dict, int]:
    """Vision channel: single-page image OCR + layout understanding (design doc 3.1.2).

    Returns {clauses: [{clause_no, clause_type, content, page_no}]}.
    """
    if prompt is None:
        prompt = (
            "识别本页合同图片中的全部条款文本，按条款号结构化输出 JSON："
            '{"clauses": [{"clause_no": "条款号", "clause_type": "条款类型（如 违约责任/付款/保密）", '
            '"content": "条款完整原文", "page_no": 1}]}，不要输出任何其他文字。'
        )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }
    ]
    content, tokens = _chat_with_retry(messages, json_mode=True, model=vision_endpoint().model)
    try:
        return _loads_json(content), tokens
    except (json.JSONDecodeError, ValueError) as e:
        raise LLMError(f"视觉模型输出 JSON 解析失败：{e}") from e


def run_parallel(func, items):
    """Run in parallel (rate limiting via semaphore is handled inside _chat_with_retry)."""
    if not items:
        return []
    futures = [_pool.submit(func, item) for item in items]
    return [f.result() for f in futures]


def ensure_llm_configured() -> None:
    try:
        endpoint = llm_endpoint()
    except ModelConfigError as e:
        raise AppError("LLM_CONFIG_ERROR", 503, f"对话模型配置错误：{e}") from e
    if endpoint.requires_api_key and not endpoint.api_key:
        raise AppError(
            "LLM_SERVICE_UNAVAILABLE",
            503,
            f"未配置 {endpoint.api_key_env or 'LLM_API_KEY'}（当前厂商 {endpoint.provider}）："
            "本系统为仅真实 API 模式，请先在 backend/.env 配置模型密钥",
        )
