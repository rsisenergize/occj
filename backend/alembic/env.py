import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure every model module is imported so Base.metadata is complete before
# autogenerate compares it against the live schema.
import app.models  # noqa: F401
from app.config import get_settings
from app.db import Base, connect_args_for

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Driven by app settings (DATABASE_URL env var), not a hardcoded url in
# alembic.ini -- same migrations run unmodified against local SQLite and
# Supabase Postgres. configparser treats "%" as interpolation syntax (e.g.
# in a percent-encoded password like "%40"), so it must be escaped to "%%"
# going in -- config.get_main_option/get_section un-escape it on the way out.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args_for(get_settings().database_url),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
