"""Tests for backend/alembic: the build_connect_args helper and the env.py migration runner."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from backend.alembic.utils import build_connect_args


class TestBuildConnectArgs:
    def test_asyncpg_url_uses_timeout(self):
        url = "postgresql+asyncpg://user:pass@localhost/db"
        assert build_connect_args(url) == {"timeout": 10}

    def test_psycopg2_url_uses_connect_timeout(self):
        url = "postgresql+psycopg2://user:pass@localhost/db"
        assert build_connect_args(url) == {"connect_timeout": 10}

    def test_bare_postgresql_url_uses_connect_timeout(self):
        url = "postgresql://user:pass@localhost/db"
        assert build_connect_args(url) == {"connect_timeout": 10}

    def test_sqlite_url_returns_empty(self):
        url = "sqlite:///./data/reli.db"
        assert build_connect_args(url) == {}

    def test_empty_url_treated_as_non_sqlite(self):
        # Empty URL is neither asyncpg nor sqlite, so falls through to psycopg2 branch
        assert build_connect_args("") == {"connect_timeout": 10}


@pytest.fixture()
def fresh_database(postgres_url: str) -> Iterator[str]:
    """An empty database on the test server, with the app's settings pointed at it for the test.

    ``migrated_db`` starts from nothing and reaches head in one go, which is exactly the path that
    never exercised the bug below — so this fixture hands out a database the test can walk through
    revision by revision, and restores the settings singleton afterwards.
    """
    from backend import config as config_module
    from backend import db_engine

    name = "reli_env_regression"
    server = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {name}"))

    url = postgres_url.rsplit("/", 1)[0] + f"/{name}"
    previous_env = os.environ.get("DATABASE_URL")
    previous_setting = config_module.settings.DATABASE_URL
    os.environ["DATABASE_URL"] = url
    config_module.settings.DATABASE_URL = url
    db_engine.reset_engine()

    yield url

    config_module.settings.DATABASE_URL = previous_setting
    if previous_env is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_env
    db_engine.reset_engine()
    with server.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    server.dispose()


def _alembic_config():
    from alembic.config import Config as AlembicConfig

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return AlembicConfig(os.path.join(repo_root, "alembic.ini"))


def _upgrade(revision: str) -> None:
    from alembic import command as alembic_command

    alembic_command.upgrade(_alembic_config(), revision)


def _script_head() -> str:
    """The single head revision of the versions directory, so the test follows new migrations."""
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert head is not None, "the versions directory must have exactly one head"
    return head


def _state(url: str) -> tuple[set[str], set[str]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        versions = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
        tables = set(
            conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            ).scalars()
        )
    engine.dispose()
    return versions, tables


def test_upgrading_from_an_existing_revision_persists(fresh_database: str):
    """Regression: migrations after the baseline were rolled back on every boot (#1450).

    env.py probes ``alembic_version`` on the connection it then hands to Alembic. Under SQLAlchemy
    2.x that probe autobegins a transaction; Alembic saw it, ran the DDL inside it and never
    committed, so ``upgrade head`` on a database already at ``v4_baseline`` logged the upgrade and
    then lost it. A fresh database never showed this because the failing probe was rolled back.
    """
    _upgrade("v4_baseline")
    assert _state(fresh_database)[0] == {"v4_baseline"}

    _upgrade("head")

    versions, tables = _state(fresh_database)
    assert versions == {_script_head()}
    assert versions != {"v4_baseline"}
    assert {"mcp_registered_clients", "mcp_oauth_sessions", "mcp_auth_codes", "mcp_refresh_tokens"} <= tables
    assert "web_oauth_sessions" in tables
