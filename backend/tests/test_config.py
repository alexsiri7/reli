"""Settings: the database URL comes from the environment, or not at all."""

import pytest

from backend.config import Settings


def test_database_url_raises_when_unset():
    """There is no local-file fallback, so a missing DATABASE_URL fails loudly."""
    settings = Settings(DATABASE_URL="")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        _ = settings.database_url


def test_database_url_is_returned_verbatim():
    url = "postgresql://reli:secret@db.example.test:5432/reli"
    assert Settings(DATABASE_URL=url).database_url == url
