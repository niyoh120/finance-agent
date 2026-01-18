import asyncio
from logging.config import fileConfig

from shared.database import get_database_url

# Import shared models
from shared.models import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate metadata
target_metadata = Base.metadata

# Set sqlalchemy.url from environment variable
config.set_main_option("sqlalchemy.url", get_database_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations given a (sync) connection provided by run_sync()."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 可选：更严格的自动检测（按需开启）
        # compare_type=True,
        # compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations() -> None:
    """Entry point used by Alembic CLI."""
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        asyncio.run(run_migrations_online())


# IMPORTANT: Alembic CLI imports env.py; it must run on import.
run_migrations()
