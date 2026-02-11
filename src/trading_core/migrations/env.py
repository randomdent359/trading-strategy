"""Alembic environment — multi-schema aware."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from trading_core.db.base import Base

# Import all table modules so Base.metadata sees them
import trading_core.db.tables  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

MANAGED_SCHEMAS = {"trading_market_data", "trading_signals", "trading_paper"}


def get_url() -> str:
    """Resolve DB URL: env var takes precedence over alembic.ini."""
    return os.environ.get("TRADING_DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def include_object(obj, name, type_, reflected, compare_to):
    """Only manage objects in our 3 schemas."""
    if type_ == "table":
        return obj.schema in MANAGED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without connecting."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect and execute."""
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Ensure our schemas exist before migrating
        for schema in MANAGED_SCHEMAS:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table_schema="trading_market_data",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
