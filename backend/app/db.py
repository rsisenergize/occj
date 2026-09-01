"""Async SQLAlchemy engine/session, portable between SQLite (dev) and Postgres (prod)."""
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


def connect_args_for(database_url: str) -> dict:
    """Driver-level connect_args for a given DATABASE_URL. Shared with
    alembic/env.py so migrations connect the same way the app does.

    Supabase's pooled connection (port 6543) runs PgBouncer/Supavisor in
    transaction mode, which does not preserve prepared statements across the
    pooled connections asyncpg reuses them on -- asyncpg's default statement
    cache then hits "DuplicatePreparedStatementError". Disabling it is the
    standard fix for asyncpg behind a transaction-mode pooler.
    """
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    if "+asyncpg" in database_url:
        return {"statement_cache_size": 0}
    return {}


_connect_args = connect_args_for(settings.database_url)

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip (no native tz-aware type), so a
    datetime read back from the dev DB comes back naive while Postgres/
    Supabase preserves it. Every comparison in engine code should go through
    this so the same logic is correct on both backends -- naive values are
    assumed UTC, which is the only convention this codebase ever writes."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def init_db() -> None:
    """Create tables directly for dev/demo use.

    Production deployments should use the Alembic migrations in
    backend/alembic/ instead of relying on create_all.
    """
    import app.models  # noqa: F401  (ensure all models are registered on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
