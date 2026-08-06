"""Alembic env — engine async (asyncpg), URL de app.config/DATABASE_URL."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrações são SQL puro (DDL do SDD §4.1) — sem autogenerate no v1.
target_metadata = None


def get_url() -> str:
    # Testes de integração (A7) injetam a URL via config ("sqlalchemy.url");
    # execução normal segue app.config/DATABASE_URL.
    url = config.get_main_option("sqlalchemy.url")
    return url if url else get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
