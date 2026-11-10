import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import every module's models so they register on Base.metadata before autogenerate.
from app.audit import models as audit_models  # noqa: E402, F401

# Make `app` importable when alembic is invoked from apps/api/ (also set via
# alembic.ini's prepend_sys_path = .).
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.modules.ai import models as ai_models  # noqa: E402, F401
from app.modules.autopilot import models as autopilot_models  # noqa: E402, F401
from app.modules.finance import models as finance_models  # noqa: E402, F401
from app.modules.identity import models as identity_models  # noqa: E402, F401
from app.modules.spendpilot import models as spendpilot_models  # noqa: E402, F401
from app.modules.trustflow import models as trustflow_models  # noqa: E402, F401
from app.modules.workflows import models as workflows_models  # noqa: E402, F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The single source of truth for the DB URL and the ORM metadata: the same
# settings/.env and the same Base the FastAPI app itself uses. This avoids a
# second, drifting copy of the connection string in alembic.ini.
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
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
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
