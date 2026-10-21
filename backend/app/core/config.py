"""Global config: pydantic-settings reads .env uniformly; secrets are never committed nor stored in DB."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "contract_compliance"

    # Elasticsearch
    es_url: str = "http://localhost:9200"
    es_username: str = ""
    es_password: str = ""

    # ===== Chat model (vendor-switchable; resolution logic in app/ai/providers.py) =====
    # Switch vendor: change LLM_PROVIDER + LLM_MODEL (and LLM_BASE_URL / LLM_API_KEY if needed), restart api/worker/beat
    llm_provider: str = "deepseek"  # deepseek/dashscope/openai/moonshot/zhipu/siliconflow/volcengine/ollama/custom
    llm_base_url: str = ""  # only needed for custom or to override a preset
    llm_api_key: str = ""  # only needed for custom or to override a preset key
    llm_model: str = ""  # leave empty to use the vendor preset default model
    llm_vision_model: str = ""  # model dedicated to the scanned-doc OCR channel; empty reuses the main model
    llm_stream_usage: str = ""  # tri-state: empty=follow vendor preset, true/false=force (some vendors don't support stream_options)

    # Per-vendor keys (auto-selected by LLM_PROVIDER, independent of each other)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_api_key: str = ""
    moonshot_api_key: str = ""
    zhipu_api_key: str = ""
    siliconflow_api_key: str = ""
    ark_api_key: str = ""  # Volcengine Ark

    # ===== Embedding model (vendor-switchable, same as LLM) =====
    embedding_provider: str = "dashscope"  # dashscope/openai/zhipu/siliconflow/ollama/custom
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""  # leave empty to use the vendor preset default model
    embedding_dim: int = 1024  # must match ES index dense_vector.dims; rebuild the index after switching models
    embedding_send_dimensions: str = ""  # tri-state: empty=follow preset, false=omit dimensions (e.g. bge-m3)

    # BaiLian (compat with old config; behavior unchanged)
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""

    # Security & storage
    secret_key: str = ""
    bootstrap_admin_password: str = ""
    # ===== Preset (demo) accounts: disabled by default; enable only for demo / trial =====
    # When enabled, the accounts in app/core/preset_accounts.py share PRESET_ACCOUNT_PASSWORD
    # (empty falls back to the built-in demo password) and skip the forced password change.
    # When disabled, those accounts are revoked at startup (deactivated + tokens invalidated).
    preset_accounts_enabled: bool = False
    preset_account_password: str = ""
    storage_root: str = "./data"
    access_token_expire_days: int = 7
    llm_concurrency: int = 8
    # Clause-review ReAct sub-agent recursion budget: each tool call consumes 2 super-steps (model + tools),
    # 8 only fits ~2 retrieval rounds and empirically hurts normal reviews; default 30 covers 6~7 rounds
    agent_recursion_limit: int = 30
    # Preflight strictness: true=abort if any component unready; false=only MySQL fatal, others degrade to warnings
    preflight_strict: bool = True

    # ===== Alert outbound (task failure / parse failure and other critical events) =====
    # Supports WeCom / DingTalk / Feishu bots, or any self-hosted endpoint accepting JSON; disabled by default
    alert_enabled: bool = False
    alert_webhook_url: str = ""
    alert_min_interval_seconds: int = 300  # per-key rate limit to avoid Celery retry flooding
    alert_service_name: str = "clausewise"
    # Alertmanager callback shared token: empty disables this endpoint (Alertmanager can't carry JWT)
    alert_ingest_token: str = ""
    # Celery worker metrics port (0=disabled; worker container sets 9100 for Prometheus scraping)
    worker_metrics_port: int = 0

    @model_validator(mode="after")
    def authenticated_redis(self):
        if self.redis_password:
            parts = urlsplit(self.redis_url)
            host = parts.netloc.rsplit("@", 1)[-1]
            self.redis_url = urlunsplit(parts._replace(netloc=f":{quote(self.redis_password, safe='')}@{host}"))
        return self

    def validate_security(self) -> None:
        if len(self.secret_key) < 32 or self.secret_key.lower().startswith(("change_me", "insecure-default")):
            raise ValueError("SECRET_KEY 必须配置为至少 32 字符的随机密钥，禁止默认值")

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_root)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p

    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
