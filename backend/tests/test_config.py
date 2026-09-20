"""Settings: the database URL comes from the environment, or not at all."""

import pytest

from backend.config import MIN_SECRET_KEY_BYTES, Settings


def test_database_url_raises_when_unset():
    """There is no local-file fallback, so a missing DATABASE_URL fails loudly."""
    settings = Settings(DATABASE_URL="")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        _ = settings.database_url


def test_database_url_is_returned_verbatim():
    url = "postgresql://reli:secret@db.example.test:5432/reli"
    assert Settings(DATABASE_URL=url).database_url == url


def test_sign_in_settings_default_to_empty_and_do_not_raise():
    """The Google sign-in settings close the sign-in when unset; none of them may stop the boot."""
    settings = Settings(DATABASE_URL="x")

    assert settings.SECRET_KEY == ""
    assert settings.ALLOWED_EMAILS == ""
    assert settings.GOOGLE_AUTH_REDIRECT_URI == ""
    assert settings.RELI_BASE_URL == ""
    assert settings.GOOGLE_CLIENT_ID == ""
    assert settings.GOOGLE_CLIENT_SECRET == ""


def test_secret_key_is_configured_only_at_thirty_two_bytes_or_more():
    """#1534: a set-but-short key is treated as unset, so it closes the sign-in instead of signing."""
    assert MIN_SECRET_KEY_BYTES == 32
    assert not Settings(DATABASE_URL="x", SECRET_KEY="").secret_key_configured
    assert not Settings(DATABASE_URL="x", SECRET_KEY="x").secret_key_configured
    assert not Settings(DATABASE_URL="x", SECRET_KEY="k" * 31).secret_key_configured
    assert Settings(DATABASE_URL="x", SECRET_KEY="k" * 32).secret_key_configured
    assert Settings(
        DATABASE_URL="x", SECRET_KEY="a-test-secret-key-that-is-forty-eight-chars-long"
    ).secret_key_configured


def test_secret_key_length_is_counted_in_bytes_not_characters():
    """The HMAC key is the UTF-8 encoding, so that is what RFC 7518's 32-byte floor is measured on."""
    assert not Settings(DATABASE_URL="x", SECRET_KEY="é" * 15).secret_key_configured
    assert Settings(DATABASE_URL="x", SECRET_KEY="é" * 16).secret_key_configured


def test_no_google_data_credential_setting_survives():
    """#1488: the Calendar and Gmail grant is gone, so nothing may read a refresh token."""
    assert not hasattr(Settings(DATABASE_URL="x"), "GOOGLE_REFRESH_TOKEN")


def test_allowed_emails_is_parsed_lower_cased_and_empty_admits_nobody():
    assert Settings(DATABASE_URL="x", ALLOWED_EMAILS="").allowed_emails == frozenset()
    assert Settings(DATABASE_URL="x", ALLOWED_EMAILS=" , ").allowed_emails == frozenset()
    assert Settings(DATABASE_URL="x", ALLOWED_EMAILS=" Owner@Example.com ,second@example.com,").allowed_emails == {
        "owner@example.com",
        "second@example.com",
    }
