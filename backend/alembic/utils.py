"""Shared utilities for Alembic environment configuration."""


def build_connect_args(db_url: str) -> dict:
    """Return the correct connect_args dict for the given database URL.

    asyncpg uses 'timeout'; psycopg2 and other PostgreSQL drivers use
    'connect_timeout'; SQLite accepts neither.
    """
    if "asyncpg" in db_url:
        return {"timeout": 10}
    elif not db_url.startswith("sqlite"):
        return {"connect_timeout": 10}
    return {}
