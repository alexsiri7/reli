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


def test_google_settings_default_to_empty_and_do_not_raise():
    """Unlike database_url, an unset Google credential must never stop the boot."""
    settings = Settings(DATABASE_URL="x")

    assert settings.GOOGLE_CLIENT_ID == ""
    assert settings.GOOGLE_CLIENT_SECRET == ""
    assert settings.GOOGLE_REFRESH_TOKEN == ""


def test_sign_in_settings_default_to_empty_and_do_not_raise():
    """The Google sign-in settings close the sign-in when unset; none of them may stop the boot."""
    settings = Settings(DATABASE_URL="x")

    assert settings.SECRET_KEY == ""
    assert settings.ALLOWED_EMAILS == ""
    assert settings.GOOGLE_AUTH_REDIRECT_URI == ""
    assert settings.RELI_BASE_URL == ""


def test_allowed_emails_is_parsed_lower_cased_and_empty_admits_nobody():
    assert Settings(DATABASE_URL="x", ALLOWED_EMAILS="").allowed_emails == frozenset()
    assert Settings(DATABASE_URL="x", ALLOWED_EMAILS=" , ").allowed_emails == frozenset()
    assert Settings(DATABASE_URL="x", ALLOWED_EMAILS=" Owner@Example.com ,second@example.com,").allowed_emails == {
        "owner@example.com",
        "second@example.com",
    }
