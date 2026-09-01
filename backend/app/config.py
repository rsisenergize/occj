"""Runtime configuration.

Every setting is environment-driven so the same codebase runs unmodified
across dev (SQLite, no external creds) and production (Supabase Postgres,
Groq, Freshdesk/Freshservice). Nothing here hardcodes a deployment target.
Deployment shape: React frontend on Vercel, this FastAPI service on Railway,
Postgres + Realtime on Supabase.
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
    # Comma-separated allowed frontend origins in staging/prod, e.g.
    # "https://occj.vercel.app,https://occj-git-main-yourteam.vercel.app".
    # Dev ignores this and allows everything.
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # --- Persistence ---
    # Default: local SQLite file, zero setup, for local dev/tests. In staging/prod
    # this is Supabase's pooled (PgBouncer, transaction-mode, port 6543) connection
    # string, e.g. postgresql+asyncpg://postgres.<ref>:<pw>@<host>:6543/postgres
    # -- required because Railway can run multiple worker processes, each opening
    # its own pool, and unpooled connections exhaust Supabase's connection limit fast.
    database_url: str = "sqlite+aiosqlite:///./occj.db"
    sql_echo: bool = False

    # --- Supabase (Realtime is consumed directly by the frontend; the backend only
    # needs these if it ever has to call the Supabase management/REST API itself) ---
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    # --- LLM: Groq, OpenAI-compatible endpoint ---
    # Left unset by default: the LLM layer degrades gracefully to deterministic
    # templated narratives when no api_key is configured, so the system is fully
    # demoable before Groq credentials exist.
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 20.0

    # --- Freshdesk (contact-centre evidence source) ---
    freshdesk_domain: str | None = None  # "<subdomain>" of <subdomain>.freshdesk.com
    freshdesk_api_key: str | None = None

    # --- Freshservice (ITSM: incident-correlation evidence + escalation actions) ---
    freshservice_domain: str | None = None  # "<subdomain>" of <subdomain>.freshservice.com
    freshservice_api_key: str | None = None

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

    @property
    def freshdesk_configured(self) -> bool:
        return bool(self.freshdesk_domain and self.freshdesk_api_key)

    @property
    def freshservice_configured(self) -> bool:
        return bool(self.freshservice_domain and self.freshservice_api_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
