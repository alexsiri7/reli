"""Alembic environment configuration.

Reads the database URL from backend.config.settings so credentials
are never hardcoded in alembic.ini.
"""

from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool, text

from backend.alembic.safety import check_pending_migrations

# -- Alembic Config object ---------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -- Import SQLModel metadata ------------------------------------------------
# Import all models so SQLModel.metadata knows about every table.
from sqlmodel import SQLModel  # noqa: E402

from backend import db_models as _db_models  # noqa: F401, E402

target_metadata = SQLModel.metadata

# -- Set sqlalchemy.url from application settings ----------------------------
from backend.config import settings  # noqa: E402

config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")

    # Safety check: scan pending migrations for destructive DDL
    script_dir = ScriptDirectory.from_config(config)
    check_pending_migrations(script_dir, current_heads=set())

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with a live database connection)."""
    _db_url = config.get_main_option("sqlalchemy.url") or ""
    _connect_args: dict = {}
    if "asyncpg" in _db_url:
        _connect_args = {"timeout": 10}  # asyncpg uses 'timeout', not 'connect_timeout'
    elif not _db_url.startswith("sqlite"):
        _connect_args = {"connect_timeout": 10}  # psycopg2 / other PostgreSQL drivers

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_connect_args,
    )

    with connectable.connect() as connection:
        # Safety check: scan pending migrations for destructive DDL
        script_dir = ScriptDirectory.from_config(config)
        try:
            result = connection.execute(text("SELECT version_num FROM alembic_version"))
            current_heads = {row[0] for row in result}
        except Exception:
            # Table doesn't exist yet (fresh database) — all migrations pending
            current_heads = set()
            connection.rollback()

        check_pending_migrations(script_dir, current_heads=current_heads)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
