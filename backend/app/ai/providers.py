"""Model provider resolution: abstract a "vendor" into a single OpenAI-compatible endpoint; switching vendors only changes env vars.

Why a thin layer is enough: DeepSeek / DashScope / OpenAI / Moonshot / Zhipu / Volcengine Ark /
SiliconFlow / Ollama / vLLM / OneAPI gateways all expose OpenAI-compatible /chat/completions and
/embeddings, so we uniformly reuse the openai SDK without per-vendor dependencies.

Switch vendor (restart the api / worker / beat containers after editing .env)::

    LLM_PROVIDER=moonshot
    LLM_MODEL=moonshot-v1-32k
    MOONSHOT_API_KEY=sk-xxx

Self-hosted service not covered by presets (vLLM / OneAPI gateway / corporate proxy)::

    LLM_PROVIDER=custom
    LLM_BASE_URL=https://your-gateway/v1
    LLM_MODEL=qwen-max
    LLM_API_KEY=sk-xxx

Embedding models work the same way, overridden via EMBEDDING_PROVIDER / EMBEDDING_BASE_URL /
EMBEDDING_MODEL / EMBEDDING_API_KEY. Note: switching embeddings REQUIRES rebuilding the ES index
(different dims or vector space silently breaks retrieval); see README.

Backward compatibility: when LLM_PROVIDER / EMBEDDING_PROVIDER are unset, default to deepseek /
dashscope respectively and keep reading legacy vars (DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, ...),
so behavior matches the pre-refactor state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from app.core.config import Settings, get_settings


class ModelConfigError(Exception):
    """Model config error (unknown vendor, missing BASE_URL or model name)."""


@dataclass(frozen=True)
class ModelEndpoint:
    """Everything needed for one model call, free of business semantics."""

    kind: str  # llm / embedding
    provider: str
    base_url: str
    api_key: str
    api_key_env: str  # only for error messages: which env var this vendor reads the key from
    model: str
    requires_api_key: bool = True
    json_mode: bool = True  # whether response_format={"type":"json_object"} is supported
    stream_usage: bool = True  # whether the streaming call reports usage
    dimensions: int | None = None  # embedding only
    send_dimensions: bool = True  # whether to send the dimensions param in the request

    @property
    def key_or_placeholder(self) -> str:
        """Auth-free endpoints (Ollama / internal vLLM) use a placeholder to satisfy the SDK's non-empty check."""
        return self.api_key or "EMPTY"

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class _Preset:
    """Vendor presets: only vendor-specific defaults not suitable to expose to users."""

    base_url: str = ""
    base_url_attr: str = ""  # compat with old vendor-specific BASE_URL fields (e.g. deepseek_base_url)
    api_key_attr: str = ""  # key field name; empty means the endpoint needs no auth
    default_model: str = ""
    json_mode: bool = True
    stream_usage: bool = True
    send_dimensions: bool = True

    @property
    def requires_api_key(self) -> bool:
        return bool(self.api_key_attr)


LLM_PRESETS: dict[str, _Preset] = {
    "deepseek": _Preset(
        "https://api.deepseek.com", "deepseek_base_url", "deepseek_api_key", "deepseek-chat"
    ),
    "dashscope": _Preset(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dashscope_base_url",
        "dashscope_api_key",
        "qwen-plus",
    ),
    "openai": _Preset("https://api.openai.com/v1", "", "openai_api_key", "gpt-4o-mini"),
    "moonshot": _Preset("https://api.moonshot.cn/v1", "", "moonshot_api_key", "moonshot-v1-32k"),
    "zhipu": _Preset(
        "https://open.bigmodel.cn/api/paas/v4", "", "zhipu_api_key", "glm-4-plus"
    ),
    "siliconflow": _Preset(
        "https://api.siliconflow.cn/v1", "", "siliconflow_api_key", "Qwen/Qwen2.5-72B-Instruct"
    ),
    # Volcengine Ark's model is an inference endpoint ID (ep-xxxx) and must be set explicitly, so no default model
    "volcengine": _Preset("https://ark.cn-beijing.volces.com/api/v3", "", "ark_api_key", ""),
    # Local Ollama: usually no auth, and not guaranteed to support response_format / stream_options
    "ollama": _Preset(
        "http://localhost:11434/v1", "", "", "qwen2.5:14b", json_mode=False, stream_usage=False
    ),
    "custom": _Preset("", "", "", ""),
}

EMBEDDING_PRESETS: dict[str, _Preset] = {
    "dashscope": _Preset(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dashscope_base_url",
        "dashscope_api_key",
        "text-embedding-v4",
    ),
    "openai": _Preset("https://api.openai.com/v1", "", "openai_api_key", "text-embedding-3-small"),
    "zhipu": _Preset("https://open.bigmodel.cn/api/paas/v4", "", "zhipu_api_key", "embedding-3"),
    # self-hosted embedding models like bge-m3 usually don't accept the dimensions param
    "siliconflow": _Preset(
        "https://api.siliconflow.cn/v1", "", "siliconflow_api_key", "BAAI/bge-m3", send_dimensions=False
    ),
    "ollama": _Preset(
        "http://localhost:11434/v1", "", "", "bge-m3", send_dimensions=False, json_mode=False
    ),
    "custom": _Preset("", "", "", ""),
}


def _optional_bool(raw: str) -> bool | None:
    """Parse a tri-state switch: empty string means "follow vendor preset"."""
    value = (raw or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _pick_base_url(settings: Settings, generic: str, preset: _Preset) -> str:
    """Priority: generic override > vendor-specific legacy field > preset default."""
    override = (generic or "").strip()
    if override:
        return override.rstrip("/")
    legacy = (getattr(settings, preset.base_url_attr, "") or "").strip() if preset.base_url_attr else ""
    if legacy:
        return legacy.rstrip("/")
    return preset.base_url.rstrip("/")


def _pick_api_key(settings: Settings, generic: str, preset: _Preset) -> tuple[str, str]:
    """Return (key, env var name for hints); generic override wins."""
    override = (generic or "").strip()
    if override:
        return override, "LLM_API_KEY / EMBEDDING_API_KEY"
    if not preset.api_key_attr:
        return "", ""
    return (getattr(settings, preset.api_key_attr, "") or "").strip(), preset.api_key_attr.upper()


def _resolve(
    kind: str,
    presets: dict[str, _Preset],
    provider_raw: str,
    default_provider: str,
    base_url_raw: str,
    api_key_raw: str,
    model_raw: str,
) -> ModelEndpoint:
    settings = get_settings()
    kind_label = "对话模型" if kind == "llm" else "向量模型"
    provider = (provider_raw or default_provider).strip().lower()
    preset = presets.get(provider)
    if preset is None:
        allowed = ", ".join(sorted(presets))
        raise ModelConfigError(f"未知的{kind_label}厂商 '{provider}'，可选：{allowed}")

    base_url = _pick_base_url(settings, base_url_raw, preset)
    if not base_url:
        env_name = "LLM_BASE_URL" if kind == "llm" else "EMBEDDING_BASE_URL"
        raise ModelConfigError(f"厂商 '{provider}' 需要显式配置 {env_name}（OpenAI 兼容地址，含 /v1）")

    model = (model_raw or "").strip() or preset.default_model
    if not model:
        env_name = "LLM_MODEL" if kind == "llm" else "EMBEDDING_MODEL"
        raise ModelConfigError(f"厂商 '{provider}' 没有默认模型，请配置 {env_name}")

    api_key, api_key_env = _pick_api_key(settings, api_key_raw, preset)
    endpoint = ModelEndpoint(
        kind=kind,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        model=model,
        requires_api_key=preset.requires_api_key,
        json_mode=preset.json_mode,
        stream_usage=preset.stream_usage,
    )
    if kind == "embedding":
        endpoint = replace(
            endpoint,
            dimensions=settings.embedding_dim,
            send_dimensions=preset.send_dimensions,
        )
    return endpoint


@lru_cache(maxsize=1)
def llm_endpoint() -> ModelEndpoint:
    """Chat-model endpoint used for review / Q&A."""
    s = get_settings()
    endpoint = _resolve(
        "llm",
        LLM_PRESETS,
        s.llm_provider,
        "deepseek",
        s.llm_base_url,
        s.llm_api_key,
        s.llm_model,
    )
    stream_usage = _optional_bool(s.llm_stream_usage)
    if stream_usage is not None and stream_usage != endpoint.stream_usage:
        endpoint = replace(endpoint, stream_usage=stream_usage)
    return endpoint


@lru_cache(maxsize=1)
def embedding_endpoint() -> ModelEndpoint:
    """Embedding endpoint used for knowledge-base vectorization."""
    s = get_settings()
    endpoint = _resolve(
        "embedding",
        EMBEDDING_PRESETS,
        s.embedding_provider,
        "dashscope",
        s.embedding_base_url,
        s.embedding_api_key,
        s.embedding_model,
    )
    send_dimensions = _optional_bool(s.embedding_send_dimensions)
    if send_dimensions is not None and send_dimensions != endpoint.send_dimensions:
        endpoint = replace(endpoint, send_dimensions=send_dimensions)
    return endpoint


@lru_cache(maxsize=1)
def vision_endpoint() -> ModelEndpoint:
    """Vision OCR endpoint: reuses the main model by default; can be overridden by LLM_VISION_MODEL (e.g. qwen-vl-max)."""
    s = get_settings()
    endpoint = llm_endpoint()
    override = (s.llm_vision_model or "").strip()
    return replace(endpoint, model=override) if override else endpoint


def reset_cache() -> None:
    """Clear endpoint cache (config hot-reload / tests)."""
    llm_endpoint.cache_clear()
    embedding_endpoint.cache_clear()
    vision_endpoint.cache_clear()


def describe() -> dict[str, str]:
    """For startup logs / preflight display: currently active vendor and model."""
    out: dict[str, str] = {}
    for key, fn in (("llm", llm_endpoint), ("embedding", embedding_endpoint)):
        try:
            ep = fn()
            out[key] = f"{ep.provider} · {ep.model} · {ep.base_url}"
        except ModelConfigError as e:
            out[key] = f"配置错误：{e}"
    return out
