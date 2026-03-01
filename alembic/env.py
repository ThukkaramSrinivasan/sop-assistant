"""
Alembic migration environment.

Uses asyncio mode so migrations run through the same asyncpg driver
as the application — no separate psycopg2 connection needed.
"""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

# Import every model so SQLModel.metadata knows about all tables.
# This is required for --autogenerate to detect schema changes.
from app.models.ai_response import AIResponse  # noqa: F401
from app.models.chunk import DocumentChunk  # noqa: F401
from app.models.customer import Customer  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.ingestion_job import IngestionJob  # noqa: F401
from app.models.user import User  # noqa: F401

logger = logging.getLogger(__name__)

alembic_cfg = context.config

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

target_metadata = SQLModel.metadata


def _get_database_url() -> str:
    from app.core.config import settings  # deferred so env vars are loaded first

    return settings.database_url


# ---------------------------------------------------------------------------
# Offline mode — emit SQL to stdout without a live DB connection
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Ensure enum types are compared correctly
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — connect to the live DB and run migrations
# ---------------------------------------------------------------------------


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_get_database_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
