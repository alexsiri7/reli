"""Tests for the build_connect_args helper in alembic/utils.py."""

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
