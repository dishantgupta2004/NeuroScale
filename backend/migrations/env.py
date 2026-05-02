"""
Alembic environment configuration.

Key choices
-----------
- We use the async engine in the *app*, but Alembic itself uses the sync
  driver (psycopg2) because Alembic's offline + online migration runners
  are sync. We translate `postgresql+asyncpg://...` -> `postgresql://...`
  here so the user only configures one DATABASE_URL.

- target_metadata = Base.metadata, which gets populated when we import
  app.db (which imports every table module). Don't remove that import.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure `app` is importable when running `alembic` from backend/.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# IMPORTANT: importing app.db registers every table on Base.metadata.
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Translate async URL to sync for migrations.
def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)

config.set_main_option("sqlalchemy.url", _sync_url(settings.database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without connecting to a DB. Useful for review."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # don't keep connections after migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()