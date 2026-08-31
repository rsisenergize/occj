"""Async SQLAlchemy engine/session, portable between SQLite (dev) and Postgres (prod)."""
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

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
    return datetime.now(timezone.utc)


async def init_db() -> None:
    """Create tables directly for dev/demo use.

    Production deployments should use the Alembic migrations in
    backend/alembic/ instead of relying on create_all.
    """
    import app.models  # noqa: F401  (ensure all models are registered on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
