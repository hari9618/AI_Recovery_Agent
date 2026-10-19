"""Application settings, loaded from environment variables / `.env`.

Every tunable that affects business behaviour (thresholds, model, limits) lives here or in the
per-company `settings` JSON, never as a literal in the code paths that use it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


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
    redis_url: str | None = None

    # --- auth (authentication-ready; demo token for local use) --------------------------
    demo_api_token: SecretStr = SecretStr("dev-demo-token-change-me")
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
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"

    # --- RAG -----------------------------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    reranker_enabled: bool = True
    model_cache_dir: Path = REPO_ROOT / ".cache" / "models"
    rag_candidate_k: int = 20
    rag_top_k: int = 5
    rag_rrf_k: int = 60
    rag_chunk_target_chars: int = 1200
    rag_chunk_overlap_chars: int = 150
    # Minimum reranker relevance (sigmoid of cross-encoder logit) to count as evidence.
    rag_min_relevance: float = 0.2
    # Minimum claim↔evidence cosine similarity for a citation to count as supported.
    rag_min_claim_support: float = 0.55

    # --- uploads -------------------------------------------------------------------------
    upload_max_bytes: int = 10 * 1024 * 1024
    ingest_max_rows: int = 50_000

    # --- demo ----------------------------------------------------------------------------
    demo_seed: int = 20241019
    demo_company_name: str = "Arcline Systems"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.get_secret_value() and self.groq_model)

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
