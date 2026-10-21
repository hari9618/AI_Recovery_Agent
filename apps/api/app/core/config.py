"""Application settings, loaded from environment variables / `.env`.

Every tunable that affects business behaviour (thresholds, model, limits) lives here or in the
per-company `settings` JSON, never as a literal in the code paths that use it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
# Public placeholder from the repo; fine locally, never accepted in production.
DEFAULT_DEMO_API_TOKEN = "dev-demo-token-change-me"


def normalise_database_url(url: str) -> str:
    """Accept the connection strings hosting providers hand out (Neon, Supabase, Render, Heroku).

    `postgres://` / `postgresql://` become the asyncpg driver URL, libpq's `sslmode=` becomes asyncpg's `ssl=`,
    and libpq-only options asyncpg would reject (`channel_binding`) are dropped.
    """
    parts = urlsplit(url.strip())
    scheme = "postgresql+asyncpg" if parts.scheme in ("postgres", "postgresql") else parts.scheme
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            query.append(("ssl", value))
        elif key != "channel_binding":
            query.append((key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # --- runtime -------------------------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- data stores ---------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres@127.0.0.1:5433/revenue_recovery"
    database_echo: bool = False
    database_pool_size: int = 10
    redis_url: str | None = None

    # --- auth (authentication-ready; demo token for local use) --------------------------
    demo_api_token: SecretStr = SecretStr(DEFAULT_DEMO_API_TOKEN)
    auth_disabled: bool = False

    # --- LLM -----------------------------------------------------------------------------
    llm_provider: Literal["groq"] = "groq"
    groq_api_key: SecretStr | None = None
    groq_model: str | None = None
    groq_base_url: str | None = None
    # json_schema = constrained decoding (only some Groq models); json_object = any model.
    groq_structured_mode: Literal["json_schema", "json_object"] = "json_schema"
    groq_reasoning_effort: Literal["low", "medium", "high"] | None = "low"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    llm_structured_repair_attempts: int = 2
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 2048
    llm_max_concurrency: int = 4
    # USD per 1M tokens; used for *estimated* cost. Override when Groq pricing changes.
    llm_price_input_per_m: float | None = None
    llm_price_output_per_m: float | None = None

    # --- observability -------------------------------------------------------------------
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    # LANGFUSE_HOST, or LANGFUSE_BASE_URL (the name newer Langfuse docs use). Must match the key's region.
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("langfuse_host", "langfuse_base_url"),
    )
    langfuse_environment: str = "development"

    # --- notifications ---------------------------------------------------------------------
    # Slack incoming-webhook URL (https://hooks.slack.com/services/...). Optional: without it nothing is posted.
    slack_webhook_url: SecretStr | None = None
    slack_timeout_seconds: float = 5.0
    # Where links in notifications point (the web app, not the API).
    app_public_url: str = "http://localhost:3100"

    # --- RAG -----------------------------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    reranker_enabled: bool = True
    model_cache_dir: Path = REPO_ROOT / ".cache" / "models"
    rag_candidate_k: int = 12
    rag_top_k: int = 5
    rag_rrf_k: int = 60
    rag_chunk_target_chars: int = 1200
    rag_chunk_overlap_chars: int = 150
    # Minimum reranker relevance (sigmoid of cross-encoder logit) to count as evidence.
    rag_min_relevance: float = 0.2
    # Claim↔evidence support thresholds: cross-encoder relevance (preferred) or bi-encoder cosine (fallback).
    # Measured on the demo corpus: supporting passages score ~1.0 with the cross-encoder, unrelated ones ~0.0,
    # while cosine gives 0.55–0.65 for unrelated passages of the same domain — hence the stricter cosine bar.
    rag_min_claim_support_xenc: float = 0.5
    rag_min_claim_support: float = 0.7
    # Withhold chunks flagged by the injection scanner from LLM context (they stay visible in search).
    rag_exclude_flagged_from_llm: bool = True

    # --- uploads -------------------------------------------------------------------------
    upload_max_bytes: int = 10 * 1024 * 1024
    ingest_max_rows: int = 50_000

    # --- demo ----------------------------------------------------------------------------
    demo_seed: int = 20241019
    demo_company_name: str = "Arcline Systems"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        return normalise_database_url(value) if isinstance(value, str) else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _require_real_token_in_production(self) -> Settings:
        token = self.demo_api_token.get_secret_value().strip()
        if self.environment == "production" and (not token or token == DEFAULT_DEMO_API_TOKEN):
            raise ValueError("DEMO_API_TOKEN must be set to a private random value in production")
        return self

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.get_secret_value() and self.groq_model)

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_webhook_url and self.slack_webhook_url.get_secret_value().strip())

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
