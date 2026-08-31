"""Runtime configuration.

Every setting is environment-driven so the same codebase runs unmodified
across dev (SQLite, no LLM key) and production (Postgres, LLM proxy behind
litellm). Nothing here hardcodes a deployment target.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Service ---
    app_name: str = "Omnichannel Customer Journey Investigation & Recovery Agent"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # --- Persistence ---
    # Default: local SQLite file, zero setup. Swap to Postgres for real
    # concurrency / LISTEN-NOTIFY-driven realtime by setting DATABASE_URL, e.g.
    # postgresql+asyncpg://occj:occj@localhost:5432/occj
    database_url: str = "sqlite+aiosqlite:///./occj.db"
    sql_echo: bool = False

    # --- LLM (OpenAI-compatible, e.g. a litellm proxy in front of any model) ---
    # Left unset by default: the LLM layer degrades gracefully to deterministic
    # templated narratives when no base_url/api_key is configured, so the
    # system is fully demoable offline. Provide these to enable richer
    # hypothesis rationale / customer-message drafting.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 20.0

    # --- Auth (lightweight demo RBAC; swap for real IdP in production) ---
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480

    # --- Business rules ---
    # Compensation at or above this amount requires supervisor/finance approval.
    high_value_approval_threshold_usd: float = 75.0
    # Evidence older than this relative to the case's last activity is "stale".
    stale_evidence_hours: int = 48
    # New evidence that shifts leading-hypothesis confidence by more than this
    # triggers automatic re-evaluation instead of silently keeping the old plan.
    reevaluation_confidence_delta: float = 0.15


@lru_cache
def get_settings() -> Settings:
    return Settings()
