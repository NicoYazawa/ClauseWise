# LiteLLM gateway "alias -> real model" resolution.
#
# Context: the application only knows gateway aliases (.env LLM_MODEL=contract-review);
# the real vendor and model are centralized in docker/litellm/config.yaml, so switching
# vendors / changing params / adding backup models never touches application code.
# But if the frontend (bottom of the sidebar) only shows the alias, you cannot tell
# whether the model behind it is DeepSeek or BaiLian (DashScope).
#
# This module queries the gateway's /v1/model/info for the mapping and translates the
# alias into the real model name, for display only:
#     contract-review -> deepseek-v4-flash-vision-exp (vendor=deepseek)
# When the gateway is unavailable (direct vendor connection, gateway down, auth failure),
# it silently degrades to an empty mapping without affecting any business flow - the
# display layer falls back to the alias when the real name cannot be retrieved.
#
# Depends only on the standard-library urllib to avoid pulling in an HTTP client for a
# low-frequency display query.
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# The mapping changes with gateway config, so a 60s cache is enough; failures are also cached as empty to avoid hitting the gateway on every page load
_CACHE_TTL = 60.0
_TIMEOUT = 3.0

_lock = threading.Lock()
_cache: dict[str, dict[str, str]] = {}
_cached_at = 0.0


def _vendor_from_api_base(api_base: str) -> str:
    # Infer the real vendor from the gateway-configured api_base domain (for display)
    host = api_base.split('//')[-1].split('/')[0].lower()
    if 'deepseek' in host:
        return 'deepseek'
    if 'dashscope' in host or 'aliyuncs' in host:
        return 'dashscope'
    if 'moonshot' in host:
        return 'moonshot'
    if 'zhipu' in host:
        return 'zhipu'
    if 'siliconflow' in host:
        return 'siliconflow'
    if 'volces' in host or 'ark' in host:
        return 'volcengine'
    if 'openai' in host:
        return 'openai'
    return ''


def _fetch(base_url: str, api_key: str) -> dict[str, dict[str, str]]:
    # Query the gateway /v1/model/info, returning {alias: {model, vendor}}
    root = base_url.rstrip('/')
    if root.endswith('/v1'):
        root = root[: -len('/v1')]
    req = urllib.request.Request(
        root + '/v1/model/info',
        headers={'Authorization': 'Bearer ' + api_key},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode('utf-8'))

    out: dict[str, dict[str, str]] = {}
    for item in payload.get('data') or []:
        alias = item.get('model_name')
        params = item.get('litellm_params') or {}
        real = params.get('model') or ''
        if not alias or not real:
            continue
        if '/' in real:
            real = real.split('/', 1)[1]  # Strip vendor prefixes like "openai/"
        out[alias] = {
            'model': real,
            'vendor': _vendor_from_api_base(params.get('api_base') or ''),
        }
    return out


def resolve_alias_map(base_url: str, api_key: str) -> dict[str, dict[str, str]]:
    # Return {alias: {model, vendor}}; returns an empty dict when the gateway is unavailable (caller falls back to showing the alias)
    global _cache, _cached_at
    if not base_url or not api_key:
        return {}

    now = time.monotonic()
    with _lock:
        if _cached_at and now - _cached_at < _CACHE_TTL:
            return _cache

    try:
        data = _fetch(base_url, api_key)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        log.warning('LiteLLM /v1/model/info 查询失败，模型展示降级为别名：%s', e)
        data = {}

    with _lock:
        _cache = data
        _cached_at = now
    return data