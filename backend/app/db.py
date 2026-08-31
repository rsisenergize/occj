"""Async SQLAlchemy engine/session, portable between SQLite (dev) and Postgres (prod)."""
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

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
