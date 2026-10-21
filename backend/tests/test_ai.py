"""Unit tests for the ai layer: vendor resolution / LLM client / embedding client / RAG / prompts / gateway aliases."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.ai import embedding_client, gateway_models, llm_client, prompt_manager, providers, rag
from app.core.exceptions import AppError
from tests import helpers


# ===================== providers =====================
def _settings(**kw):
    from app.core.config import Settings

    base = dict(_env_file=None, deepseek_api_key="ds-key", dashscope_api_key="dsq-key")
    base.update(kw)
    return Settings(**base)


class TestProviders:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def _use(self, **kw):
        providers.reset_cache()
        self._monkeypatch.setattr(providers, "get_settings", lambda: _settings(**kw))

    def test_optional_bool(self):
        assert providers._optional_bool("1") is True
        assert providers._optional_bool("true") is True
        assert providers._optional_bool("ON") is True
        assert providers._optional_bool("0") is False
        assert providers._optional_bool("off") is False
        assert providers._optional_bool("") is None
        assert providers._optional_bool("garbage") is None

    def test_llm_endpoint_deepseek_default(self):
        self._use()
        ep = providers.llm_endpoint()
        assert ep.provider == "deepseek"
        assert ep.base_url == "https://api.deepseek.com"
        assert ep.model == "deepseek-chat"
        assert ep.api_key == "ds-key"
        assert ep.api_key_env == "DEEPSEEK_API_KEY"
        assert ep.label == "deepseek:deepseek-chat"
        assert ep.key_or_placeholder == "ds-key"

    def test_llm_endpoint_unknown_provider(self):
        self._use(llm_provider="nope")
        with pytest.raises(providers.ModelConfigError) as ei:
            providers.llm_endpoint()
        assert "未知的对话模型厂商" in str(ei.value)

    def test_custom_requires_base_url(self):
        self._use(llm_provider="custom")
        with pytest.raises(providers.ModelConfigError) as ei:
            providers.llm_endpoint()
        assert "LLM_BASE_URL" in str(ei.value)

    def test_custom_with_overrides(self):
        self._use(llm_provider="custom", llm_base_url="https://gw.local/v1/", llm_model="qwen-max",
                  llm_api_key="sk-x")
        ep = providers.llm_endpoint()
        assert ep.base_url == "https://gw.local/v1"  # 去掉尾部斜杠
        assert ep.model == "qwen-max"
        assert ep.api_key == "sk-x"
        assert ep.api_key_env == "LLM_API_KEY / EMBEDDING_API_KEY"

    def test_volcengine_requires_model(self):
        self._use(llm_provider="volcengine", ark_api_key="k")
        with pytest.raises(providers.ModelConfigError) as ei:
            providers.llm_endpoint()
        assert "LLM_MODEL" in str(ei.value)

    def test_legacy_base_url_attr(self):
        self._use(deepseek_base_url="https://legacy.deepseek.local/v1")
        assert providers.llm_endpoint().base_url == "https://legacy.deepseek.local/v1"

    def test_ollama_no_key_needed(self):
        self._use(llm_provider="ollama")
        ep = providers.llm_endpoint()
        assert ep.requires_api_key is False
        assert ep.api_key == ""
        assert ep.key_or_placeholder == "EMPTY"
        assert ep.json_mode is False
        assert ep.stream_usage is False

    def test_stream_usage_tristate_override(self):
        self._use(llm_stream_usage="false")
        assert providers.llm_endpoint().stream_usage is False
        self._use(llm_stream_usage="true")
        assert providers.llm_endpoint().stream_usage is True
        self._use(llm_stream_usage="")
        assert providers.llm_endpoint().stream_usage is True

    def test_embedding_endpoint_defaults_and_dim(self):
        self._use(embedding_dim=768)
        ep = providers.embedding_endpoint()
        assert ep.kind == "embedding"
        assert ep.provider == "dashscope"
        assert ep.model == "text-embedding-v4"
        assert ep.dimensions == 768
        assert ep.send_dimensions is True

    def test_embedding_siliconflow_no_dimensions(self):
        self._use(embedding_provider="siliconflow")
        assert providers.embedding_endpoint().send_dimensions is False

    def test_embedding_send_dimensions_override(self):
        self._use(embedding_provider="siliconflow", embedding_send_dimensions="true")
        assert providers.embedding_endpoint().send_dimensions is True

    def test_embedding_unknown_provider(self):
        self._use(embedding_provider="bad")
        with pytest.raises(providers.ModelConfigError):
            providers.embedding_endpoint()

    def test_vision_endpoint_override_and_reuse(self):
        self._use()
        assert providers.vision_endpoint().model == "deepseek-chat"
        self._use(llm_vision_model="qwen-vl-max")
        assert providers.vision_endpoint().model == "qwen-vl-max"

    def test_describe_and_reset_cache(self):
        self._use(llm_provider="bad")
        out = providers.describe()
        assert "配置错误" in out["llm"]  # embedding 默认 dashscope 仍可用
        assert out["embedding"].startswith("dashscope")
        providers.reset_cache()
        self._use()
        out = providers.describe()
        assert out["llm"].startswith("deepseek · deepseek-chat")
        assert out["embedding"].startswith("dashscope")


# ===================== llm_client =====================
@pytest.fixture()
def llm_env(monkeypatch):
    """Fixed endpoint + scriptable fake client."""
    ep = providers.ModelEndpoint(
        kind="llm", provider="deepseek", base_url="https://api.deepseek.com", api_key="k",
        api_key_env="DEEPSEEK_API_KEY", model="deepseek-chat",
    )
    monkeypatch.setattr(llm_client, "llm_endpoint", lambda: ep)
    return ep


class TestLlmClient:
    def test_get_llm_client_config_error(self, monkeypatch):
        from app.ai.providers import ModelConfigError

        def _boom():
            raise ModelConfigError("坏配置")

        monkeypatch.setattr(llm_client, "llm_endpoint", _boom)
        with pytest.raises(llm_client.LLMError):
            llm_client.get_llm_client()

    def test_get_llm_client_missing_key(self, monkeypatch):
        ep = providers.ModelEndpoint(kind="llm", provider="deepseek", base_url="https://x",
                                     api_key="", api_key_env="DEEPSEEK_API_KEY", model="m")
        monkeypatch.setattr(llm_client, "llm_endpoint", lambda: ep)
        with pytest.raises(llm_client.LLMError) as ei:
            llm_client.get_llm_client()
        assert "DEEPSEEK_API_KEY" in str(ei.value)

    def test_get_llm_client_ok_and_rebuild(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient()
        monkeypatch.setattr(llm_client, "OpenAI", lambda **kw: fake)
        c1 = llm_client.get_llm_client()
        assert c1 is fake
        # endpoint changed -> rebuild the client
        llm_env2 = providers.ModelEndpoint(kind="llm", provider="openai", base_url="https://api.openai.com/v1",
                                           api_key="k", api_key_env="OPENAI_API_KEY", model="gpt-4o-mini")
        monkeypatch.setattr(llm_client, "llm_endpoint", lambda: llm_env2)
        fake2 = helpers.FakeOpenAIClient()
        monkeypatch.setattr(llm_client, "OpenAI", lambda **kw: fake2)
        assert llm_client.get_llm_client() is fake2

    def test_current_model(self, llm_env):
        assert llm_client.current_model() == "deepseek-chat"

    def test_current_model_fallback(self, monkeypatch):
        from app.ai.providers import ModelConfigError

        monkeypatch.setattr(llm_client, "llm_endpoint",
                            lambda: (_ for _ in ()).throw(ModelConfigError("x")))
        assert llm_client.current_model() == llm_client.settings.llm_model

    def test_is_fatal(self):
        assert llm_client._is_fatal(helpers.api_status_error(401)) is True
        assert llm_client._is_fatal(helpers.api_status_error(403)) is True
        assert llm_client._is_fatal(helpers.api_status_error(500)) is False
        assert llm_client._is_fatal(ValueError("x")) is False

    def test_is_json_mode_rejection(self):
        assert llm_client._is_json_mode_rejection(helpers.api_status_error(400, "response_format not support")) is True
        assert llm_client._is_json_mode_rejection(helpers.api_status_error(422, "json_object unsupported")) is True
        assert llm_client._is_json_mode_rejection(helpers.api_status_error(500)) is False
        assert llm_client._is_json_mode_rejection(ValueError("x")) is False

    def test_loads_json_fences_and_prose(self):
        assert llm_client._loads_json('前言 ```json\n{"a": 1}\n``` 后记') == {"a": 1}

    def test_loads_json_no_object(self):
        with pytest.raises(ValueError):
            llm_client._loads_json("没有 JSON")

    def test_chat_json_success(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.make_chat_response('{"risk_level": "high"}',
                                                                          prompt_tokens=100, completion_tokens=20)])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        out, tokens = llm_client.chat_json("sys", "user")
        assert out == {"risk_level": "high"}
        assert tokens == 120
        kwargs = fake.chat.completions.calls[0]
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["temperature"] == 0.1

    def test_chat_json_parse_failure(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.make_chat_response("不是JSON")])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        with pytest.raises(llm_client.LLMError) as ei:
            llm_client.chat_json("s", "u")
        assert "JSON 解析失败" in str(ei.value)

    def test_chat_text_success(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.make_chat_response("回答")])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        text, tokens = llm_client.chat_text("s", "u")
        assert text == "回答"
        assert "response_format" not in fake.chat.completions.calls[0]

    def test_chat_retry_then_success(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[
            helpers.api_status_error(500), helpers.make_chat_response("ok"),
        ])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        text, _ = llm_client.chat_text("s", "u")
        assert text == "ok"
        assert len(fake.chat.completions.calls) == 2

    def test_chat_fatal_no_retry(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.api_status_error(401, "bad key")])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        with pytest.raises(llm_client.LLMError) as ei:
            llm_client.chat_text("s", "u")
        assert "密钥或权限无效" in str(ei.value)
        assert len(fake.chat.completions.calls) == 1

    def test_chat_all_retries_fail(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.api_status_error(500)] * 3)
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        with pytest.raises(llm_client.LLMError) as ei:
            llm_client._chat_with_retry([{"role": "user", "content": "u"}], retries=2)
        assert "连续 2 次失败" in str(ei.value)
        assert len(fake.chat.completions.calls) == 2

    def test_json_mode_rejection_degrades(self, llm_env, monkeypatch):
        # first 400 says response_format unsupported -> turn off json mode and retry succeeds (no retries consumed)
        fake = helpers.FakeOpenAIClient(script=[
            helpers.api_status_error(400, "response_format not support"),
            helpers.make_chat_response('{"a": 1}'),
        ])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        out, _ = llm_client.chat_json("s", "u")
        assert out == {"a": 1}
        assert "response_format" not in fake.chat.completions.calls[1]
        assert "deepseek-chat" in llm_client._json_unsupported
        llm_client._json_unsupported.discard("deepseek-chat")

    def test_unsupported_model_skips_json_mode(self, llm_env, monkeypatch):
        llm_client._json_unsupported.add("deepseek-chat")
        fake = helpers.FakeOpenAIClient(script=[helpers.make_chat_response('{"a": 1}')])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        llm_client.chat_json("s", "u")
        assert "response_format" not in fake.chat.completions.calls[0]
        llm_client._json_unsupported.discard("deepseek-chat")

    def test_chat_text_stream_success(self, llm_env, monkeypatch):
        def _chunk(text):
            return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

        class _Stream:
            def __init__(self, items):
                self.items = list(items)

            def __iter__(self):
                return iter(self.items)

        fake = helpers.FakeOpenAIClient(script=[_Stream([_chunk("你"), _chunk("好")])])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        out = list(llm_client.chat_text_stream("s", "u"))
        assert out == ["你", "好"]
        assert fake.chat.completions.calls[0]["stream"] is True

    def test_stream_skips_empty_choices(self, llm_env, monkeypatch):
        empty = SimpleNamespace(choices=[])
        piece = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="x"))])

        class _Stream:
            def __iter__(self):
                return iter([empty, piece])

        fake = helpers.FakeOpenAIClient(script=[_Stream()])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        assert list(llm_client.chat_text_stream("s", "u")) == ["x"]

    def test_stream_interrupt_after_produced(self, llm_env, monkeypatch):
        class _Stream:
            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="片段"))])
                raise OSError("断流")

        fake = helpers.FakeOpenAIClient(script=[_Stream()])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        gen = llm_client.chat_text_stream("s", "u")
        assert next(gen) == "片段"
        with pytest.raises(llm_client.LLMError) as ei:
            next(gen)
        assert "流式输出中断" in str(ei.value)

    def test_stream_retry_before_produced(self, llm_env, monkeypatch):
        piece = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))])

        class _OkStream:
            def __iter__(self):
                return iter([piece])

        class _FailStream:
            def __iter__(self):
                raise OSError("打开失败")

        fake = helpers.FakeOpenAIClient(script=[_FailStream(), _OkStream()])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        assert list(llm_client.chat_text_stream("s", "u")) == ["ok"]
        assert len(fake.chat.completions.calls) == 2

    def test_stream_fatal(self, llm_env, monkeypatch):
        class _FailStream:
            def __iter__(self):
                raise helpers.api_status_error(401)

        fake = helpers.FakeOpenAIClient(script=[_FailStream()])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        with pytest.raises(llm_client.LLMError) as ei:
            list(llm_client.chat_text_stream("s", "u"))
        assert "密钥或权限无效" in str(ei.value)

    def test_stream_exhausted(self, llm_env, monkeypatch):
        class _FailStream:
            def __iter__(self):
                raise OSError("boom")

        fake = helpers.FakeOpenAIClient(script=[_FailStream()] * 3)
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        with pytest.raises(llm_client.LLMError) as ei:
            list(llm_client.chat_text_stream("s", "u", retries=2))
        assert "连续 2 次失败" in str(ei.value)

    def test_vision_extract_clauses(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[
            helpers.make_chat_response('{"clauses": [{"clause_no": "第一条", "content": "x"}]}')
        ])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        monkeypatch.setattr(llm_client, "vision_endpoint",
                            lambda: providers.ModelEndpoint(kind="llm", provider="deepseek",
                                                            base_url="https://x", api_key="k",
                                                            api_key_env="K", model="vision-model"))
        out, tokens = llm_client.vision_extract_clauses("b64data")
        assert out["clauses"][0]["clause_no"] == "第一条"
        kwargs = fake.chat.completions.calls[0]
        assert kwargs["model"] == "vision-model"
        content = kwargs["messages"][0]["content"]
        assert content[1]["image_url"]["url"] == "data:image/png;base64,b64data"

    def test_vision_extract_custom_prompt(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.make_chat_response('{"clauses": []}')])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        llm_client.vision_extract_clauses("b64data", mime="image/jpeg", prompt="自定义提示")
        content = fake.chat.completions.calls[0]["messages"][0]["content"]
        assert content[0]["text"] == "自定义提示"
        assert "data:image/jpeg;base64,b64data" in content[1]["image_url"]["url"]

    def test_vision_extract_bad_json(self, llm_env, monkeypatch):
        fake = helpers.FakeOpenAIClient(script=[helpers.make_chat_response("not json")])
        monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)
        with pytest.raises(llm_client.LLMError) as ei:
            llm_client.vision_extract_clauses("b64")
        assert "视觉模型输出 JSON 解析失败" in str(ei.value)

    def test_run_parallel(self, llm_env):
        assert llm_client.run_parallel(lambda x: x * 2, []) == []
        assert llm_client.run_parallel(lambda x: x * 2, [1, 2, 3]) == [2, 4, 6]

    def test_ensure_llm_configured_ok(self, llm_env):
        llm_client.ensure_llm_configured()  # 不抛

    def test_ensure_llm_configured_missing_key(self, monkeypatch):
        ep = providers.ModelEndpoint(kind="llm", provider="deepseek", base_url="https://x",
                                     api_key="", api_key_env="DEEPSEEK_API_KEY", model="m")
        monkeypatch.setattr(llm_client, "llm_endpoint", lambda: ep)
        with pytest.raises(AppError) as ei:
            llm_client.ensure_llm_configured()
        assert ei.value.detail["code"] == "LLM_SERVICE_UNAVAILABLE"

    def test_ensure_llm_configured_config_error(self, monkeypatch):
        from app.ai.providers import ModelConfigError

        monkeypatch.setattr(llm_client, "llm_endpoint",
                            lambda: (_ for _ in ()).throw(ModelConfigError("坏")))
        with pytest.raises(AppError) as ei:
            llm_client.ensure_llm_configured()
        assert ei.value.detail["code"] == "LLM_CONFIG_ERROR"


# ===================== embedding_client =====================
@pytest.fixture()
def emb_env(monkeypatch):
    ep = providers.ModelEndpoint(
        kind="embedding", provider="dashscope", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="k", api_key_env="DASHSCOPE_API_KEY", model="text-embedding-v4",
        dimensions=1024, send_dimensions=True,
    )
    monkeypatch.setattr(embedding_client, "embedding_endpoint", lambda: ep)
    embedding_client._bucket = embedding_client._RATE  # reset the token bucket
    return ep


class TestEmbeddingClient:
    def test_get_client_missing_key(self, monkeypatch):
        ep = providers.ModelEndpoint(kind="embedding", provider="dashscope", base_url="https://x",
                                     api_key="", api_key_env="DASHSCOPE_API_KEY", model="m")
        monkeypatch.setattr(embedding_client, "embedding_endpoint", lambda: ep)
        with pytest.raises(embedding_client.EmbeddingError) as ei:
            embedding_client.get_embedding_client()
        assert "DASHSCOPE_API_KEY" in str(ei.value)

    def test_get_client_config_error(self, monkeypatch):
        from app.ai.providers import ModelConfigError

        monkeypatch.setattr(embedding_client, "embedding_endpoint",
                            lambda: (_ for _ in ()).throw(ModelConfigError("x")))
        with pytest.raises(embedding_client.EmbeddingError):
            embedding_client.get_embedding_client()

    def test_embed_texts_empty(self, emb_env):
        assert embedding_client.embed_texts([]) == []

    def test_embed_texts_batching_and_dimensions(self, emb_env, monkeypatch):
        fake = helpers.FakeOpenAIClient()
        monkeypatch.setattr(embedding_client, "get_embedding_client", lambda: fake)
        monkeypatch.setattr(embedding_client, "OpenAI", lambda **kw: fake)
        out = embedding_client.embed_texts([f"t{i}" for i in range(25)])
        assert len(out) == 25
        assert all(len(v) == 4 for v in out)
        assert len(fake.embedding_calls) == 3  # 每批 ≤ 10
        assert fake.embedding_calls[0]["dimensions"] == 1024
        assert fake.embedding_calls[0]["model"] == "text-embedding-v4"

    def test_embed_query(self, emb_env, monkeypatch):
        fake = helpers.FakeOpenAIClient()
        monkeypatch.setattr(embedding_client, "get_embedding_client", lambda: fake)
        monkeypatch.setattr(embedding_client, "OpenAI", lambda **kw: fake)
        vec = embedding_client.embed_query("查询")
        assert len(vec) == 4

    def test_embed_retry_then_success(self, emb_env, monkeypatch):
        script = [helpers.api_status_error(429), None]
        fake = helpers.FakeOpenAIClient(script=script)

        class _Emb:
            def __init__(self):
                self.n = 0

            def create(self, **kw):
                self.n += 1
                if self.n == 1:
                    raise helpers.api_status_error(429)
                return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.2] * 4)])

        fake.embeddings = SimpleNamespace(create=_Emb().create)
        monkeypatch.setattr(embedding_client, "get_embedding_client", lambda: fake)
        out = embedding_client.embed_texts(["a"])
        assert out == [[0.2] * 4]

    def test_embed_fatal(self, emb_env, monkeypatch):
        def _boom(**kw):
            raise helpers.api_status_error(401)

        fake = SimpleNamespace(embeddings=SimpleNamespace(create=_boom))
        monkeypatch.setattr(embedding_client, "get_embedding_client", lambda: fake)
        with pytest.raises(embedding_client.EmbeddingError) as ei:
            embedding_client.embed_texts(["a"])
        assert "密钥或权限无效" in str(ei.value)

    def test_embed_exhausted(self, emb_env, monkeypatch):
        def _boom(**kw):
            raise helpers.api_status_error(500)

        fake = SimpleNamespace(embeddings=SimpleNamespace(create=_boom))
        monkeypatch.setattr(embedding_client, "get_embedding_client", lambda: fake)
        with pytest.raises(embedding_client.EmbeddingError) as ei:
            embedding_client.embed_texts(["a"])
        assert "连续失败" in str(ei.value)

    def test_dimensions_omitted_when_unsupported(self, monkeypatch):
        ep = providers.ModelEndpoint(
            kind="embedding", provider="ollama", base_url="http://localhost:11434/v1",
            api_key="", api_key_env="", model="bge-m3", dimensions=1024, send_dimensions=False,
        )
        monkeypatch.setattr(embedding_client, "embedding_endpoint", lambda: ep)
        embedding_client._bucket = embedding_client._RATE
        seen = {}

        def _create(**kw):
            seen.update(kw)
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1] * 4)])

        fake = SimpleNamespace(embeddings=SimpleNamespace(create=_create))
        monkeypatch.setattr(embedding_client, "get_embedding_client", lambda: fake)
        embedding_client.embed_texts(["a"])
        assert "dimensions" not in seen

    def test_token_bucket_refill(self, monkeypatch):
        # controllable clock: bucket drained -> sleep branch advances the clock -> recursive re-fetch succeeds
        import time as _time

        clock = {"t": 1000.0}
        slept = []
        monkeypatch.setattr(_time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(_time, "sleep", lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
        embedding_client._last_refill = 1000.0
        embedding_client._bucket = 0.0
        embedding_client._acquire_token()
        assert slept == [pytest.approx(1.0 / 15.0)]
        assert embedding_client._bucket < 1e-6  # 睡 1/15s 后令牌桶恰好补满并取走 1 个


# ===================== rag =====================
class TestRag:
    def test_doc_to_hit_variants(self):
        hit = rag._doc_to_hit({"doc_type": "case", "ref_id": "5", "title": "案例", "content": "内容"})
        assert hit.kind == "case" and hit.ref_id == 5
        # illegal doc_type -> fall back
        hit2 = rag._doc_to_hit({"doc_type": "weird", "ref_id": 1, "title": "t", "content": "c"}, fallback_kind="template")
        assert hit2.kind == "template"
        # error -> None
        assert rag._doc_to_hit({"ref_id": "not-int"}) is None

    def test_raghit_repr(self):
        h = rag.RagHit("law", 1, "标题" * 10, "s", 0.5)
        assert repr(h).startswith("<RagHit law:1")

    def test_native_rrf_with_vector(self):
        es = helpers.FakeES(search_script=[{"hits": {"hits": [helpers.es_hit("1", {"title": "t"})]}}])
        docs = rag._search_native_rrf(es, "idx", "查询", [0.1, 0.2], 5)
        assert docs == [{"title": "t"}]
        body = es.search_calls[0]
        assert len(body["retriever"]["rrf"]["retrievers"]) == 2

    def test_native_rrf_failure_returns_none(self):
        es = helpers.FakeES(search_script=[OSError("no rrf")])
        assert rag._search_native_rrf(es, "idx", "q", None, 5) is None

    def test_app_rrf_fusion(self):
        es = helpers.FakeES(
            search_script=[
                {"hits": {"hits": [helpers.es_hit("a", {}), helpers.es_hit("b", {})]}},
                {"hits": {"hits": [helpers.es_hit("b", {}), helpers.es_hit("c", {})]}},
            ],
            get_map={"a": {"ref_id": 1}, "b": {"ref_id": 2}, "c": {"ref_id": 3}},
        )
        docs = rag._search_app_rrf(es, "idx", "q", [0.1], 3)
        ids = [d["ref_id"] for d in docs]
        assert set(ids) == {1, 2, 3}
        assert ids[0] == 2  # b 两路都命中，融合分最高

    def test_app_rrf_bm25_fail_returns_empty(self):
        es = helpers.FakeES(search_script=[OSError("boom")])
        assert rag._search_app_rrf(es, "idx", "q", None, 5) == []

    def test_app_rrf_knn_failure_skips_vector_leg(self):
        es = helpers.FakeES(
            search_script=[
                {"hits": {"hits": [helpers.es_hit("a", {})]}},
                OSError("knn down"),  # kNN leg fails -> BM25 fusion only
            ],
            get_map={"a": {"ref_id": 1}},
        )
        docs = rag._search_app_rrf(es, "idx", "q", [0.1], 5)
        assert [d["ref_id"] for d in docs] == [1]

    def test_hybrid_search_no_es(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: None)
        assert rag.hybrid_search_knowledge("q") == []

    def test_hybrid_search_full(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: helpers.FakeES())
        monkeypatch.setattr(rag, "embed_query", lambda t: [0.1])
        monkeypatch.setattr(rag, "_search_native_rrf",
                            lambda es, index, q, vec, k: [
                                {"doc_type": "law", "ref_id": 1, "title": "法条一", "content": "内容一", "status": "active"},
                                {"doc_type": "case", "ref_id": 2, "title": "案例二", "content": "内容二", "status": "active"},
                            ] if index == rag.INDEX_LEGAL else [
                                {"doc_type": "template", "ref_id": 3, "title": "模板条款", "content": "模板内容", "status": "active"},
                            ])
        hits = rag.hybrid_search_knowledge("违约金", top_k=5)
        kinds = {h.kind for h in hits}
        assert kinds == {"law", "case", "template"}
        assert hits[0].title.startswith("企业模板") is False  # sorted by score; templates have equal weight
        assert all(h.score > 0 for h in hits)

    def test_hybrid_search_filters(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: helpers.FakeES())
        monkeypatch.setattr(rag, "embed_query", lambda t: (_ for _ in ()).throw(RuntimeError("no emb")))
        future = "2999-01-01"
        past = "2000-01-01"
        monkeypatch.setattr(rag, "_search_native_rrf", lambda es, index, q, vec, k: [
            {"doc_type": "law", "ref_id": 1, "title": "已失效", "content": "c", "status": "expired"},
            {"doc_type": "law", "ref_id": 2, "title": "未生效", "content": "c", "effective_date": future},
            {"doc_type": "law", "ref_id": 3, "title": "已过期", "content": "c", "expiry_date": past},
            {"doc_type": "law", "ref_id": 4, "title": "有效", "content": "c"},
        ] if index == rag.INDEX_LEGAL else [])
        hits = rag.hybrid_search_knowledge("q", include_templates=False)
        assert [h.title for h in hits] == ["有效"]

    def test_hybrid_search_app_rrf_fallback(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: helpers.FakeES())
        monkeypatch.setattr(rag, "embed_query", lambda t: [0.1])
        monkeypatch.setattr(rag, "_search_native_rrf", lambda *a: None)  # 原生不可用
        monkeypatch.setattr(rag, "_search_app_rrf",
                            lambda es, index, q, vec, k: [{"doc_type": "law", "ref_id": 9, "title": "兜底", "content": "c"}])
        hits = rag.hybrid_search_knowledge("q")
        assert hits[0].title == "兜底"

    def test_hybrid_search_doc_to_hit_none_skipped(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: helpers.FakeES())
        monkeypatch.setattr(rag, "embed_query", lambda t: [0.1])
        monkeypatch.setattr(rag, "_search_native_rrf",
                            lambda es, index, q, vec, k: [{"ref_id": "bad"}] if index == rag.INDEX_LEGAL else [])
        assert rag.hybrid_search_knowledge("q") == []

    def test_search_contracts(self, monkeypatch):
        es = helpers.FakeES(search_script=[{"hits": {"hits": [helpers.es_hit("1", {"title": "合同"})]}}])
        monkeypatch.setattr(rag, "get_es_client", lambda: es)
        out = rag.search_contracts("采购", top_k=3)
        assert out == [{"title": "合同"}]

    def test_search_contracts_no_es(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: None)
        assert rag.search_contracts("q") == []

    def test_search_contracts_failure(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: helpers.FakeES(search_script=[OSError("x")]))
        assert rag.search_contracts("q") == []

    def test_index_report_summary(self, monkeypatch):
        es = helpers.FakeES()
        monkeypatch.setattr(rag, "get_es_client", lambda: es)
        monkeypatch.setattr(rag, "embed_query", lambda t: [0.1, 0.2])
        doc_id = rag.index_report_summary(7, "标题", "摘要")
        assert doc_id == "report_7"
        assert es.indexed[0]["document"]["ref_id"] == 7

    def test_index_report_summary_no_es(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: None)
        assert rag.index_report_summary(7, "t", "s") is None

    def test_index_report_summary_failure(self, monkeypatch):
        monkeypatch.setattr(rag, "get_es_client", lambda: helpers.FakeES())
        monkeypatch.setattr(rag, "embed_query", lambda t: (_ for _ in ()).throw(RuntimeError("x")))
        assert rag.index_report_summary(7, "t", "s") is None


# ===================== prompt_manager =====================
class TestPromptManager:
    def test_render_prompt(self):
        out = prompt_manager.render_prompt("类型={contract_type} 条款={clause_text} 缺={missing}",
                                           {"contract_type": "采购", "clause_text": "第一条"})
        assert out == "类型=采购 条款=第一条 缺={missing}"  # 未提供的占位符原样保留

    def test_get_active_prompt_fallback(self, db):
        tpl = prompt_manager.get_active_prompt(db, prompt_manager.SCENE_REVIEW)
        assert tpl.version == "default-v1"
        assert tpl.is_active is True
        assert "{clause_text}" in tpl.content

    def test_get_active_prompt_from_db(self, db):
        helpers.make_prompt(db, version="v2.0", scene=prompt_manager.SCENE_REVIEW, content="自定义", is_active=True)
        helpers.make_prompt(db, version="v9.0", scene=prompt_manager.SCENE_REVIEW, content="更新的", is_active=True)
        db.commit()
        tpl = prompt_manager.get_active_prompt(db, prompt_manager.SCENE_REVIEW)
        assert tpl.content == "更新的"  # id 倒序取最新

    def test_get_active_prompt_inactive_ignored(self, db):
        helpers.make_prompt(db, scene=prompt_manager.SCENE_REVIEW, content="旧", is_active=False)
        db.commit()
        assert prompt_manager.get_active_prompt(db, prompt_manager.SCENE_REVIEW).version == "default-v1"


# ===================== gateway_models =====================
class TestGatewayModels:
    @pytest.fixture(autouse=True)
    def _reset(self):
        gateway_models._cache = {}
        gateway_models._cached_at = 0.0
        yield
        gateway_models._cache = {}
        gateway_models._cached_at = 0.0

    @pytest.mark.parametrize("host,expected", [
        ("https://api.deepseek.com", "deepseek"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "dashscope"),
        ("https://api.moonshot.cn/v1", "moonshot"),
        ("https://open.bigmodel.cn/api/paas/v4", ""),  # domain has no zhipu, vendor cannot be inferred (display layer falls back to alias)
        ("https://api.siliconflow.cn/v1", "siliconflow"),
        ("https://ark.cn-beijing.volces.com/api/v3", "volcengine"),
        ("https://api.openai.com/v1", "openai"),
        ("https://unknown.example.com", ""),
    ])
    def test_vendor_from_api_base(self, host, expected):
        assert gateway_models._vendor_from_api_base(host) == expected

    def test_resolve_empty_inputs(self):
        assert gateway_models.resolve_alias_map("", "key") == {}
        assert gateway_models.resolve_alias_map("http://gw", "") == {}

    def test_fetch_success(self, monkeypatch):
        payload = {"data": [
            {"model_name": "contract-review", "litellm_params": {
                "model": "openai/deepseek-v4-flash", "api_base": "https://api.deepseek.com"}},
            {"model_name": "no-real", "litellm_params": {"model": ""}},  # no real model -> skip
            {"litellm_params": {"model": "x"}},  # no alias -> skip
        ]}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        monkeypatch.setattr(gateway_models.urllib.request, "urlopen", lambda req, timeout: _Resp())
        out = gateway_models._fetch("http://gw:4000/v1", "sk")
        assert out == {"contract-review": {"model": "deepseek-v4-flash", "vendor": "deepseek"}}

    def test_resolve_cache_hit(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gateway_models, "_fetch", lambda b, k: calls.append((b, k)) or {"a": {"model": "m", "vendor": "v"}})
        first = gateway_models.resolve_alias_map("http://gw", "k")
        second = gateway_models.resolve_alias_map("http://gw", "k")
        assert first == second
        assert len(calls) == 1  # 60s TTL 内命中缓存

    def test_resolve_failure_degrades(self, monkeypatch):
        import urllib.error

        def _boom(req, timeout):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(gateway_models.urllib.request, "urlopen", _boom)
        assert gateway_models.resolve_alias_map("http://gw", "k") == {}

    def test_resolve_value_error_degrades(self, monkeypatch):
        def _bad_json(req, timeout):
            raise ValueError("bad json")

        monkeypatch.setattr(gateway_models.urllib.request, "urlopen", _bad_json)
        assert gateway_models.resolve_alias_map("http://gw", "k") == {}
