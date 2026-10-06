from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


SQLALCHEMY_ONLY = (
    "prepared_statement_cache_size",
    "prepared_statement_name_func",
    "async_fallback",
)


@asynccontextmanager
async def notify_connection(database_url: str) -> AsyncGenerator[asyncpg.Connection]:
    """A plain asyncpg connection for Postgres LISTEN and NOTIFY, which SQLAlchemy does not
    offer. Its arguments come from SQLAlchemy's asyncpg dialect, without the options that only
    SQLAlchemy reads, so URL options such as ssl work as they do for the engine."""
    _, arguments = PGDialect_asyncpg().create_connect_args(make_url(database_url))
    for option in SQLALCHEMY_ONLY:
        arguments.pop(option, None)
    connection = await asyncpg.connect(**arguments)
    try:
        yield connection
    finally:
        await connection.close()
