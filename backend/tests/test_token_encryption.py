"""Tests for token encryption module."""

from __future__ import annotations

import json

import pytest

from backend.token_encryption import (
    decrypt,
    decrypt_json_or_plaintext,
    decrypt_or_plaintext,
    encrypt,
    encrypt_json,
    reset_for_testing,
)


@pytest.fixture(autouse=True)
def _fresh_key(tmp_path, monkeypatch):
    """Use a fresh encryption key for each test."""
    reset_for_testing()
    key_file = tmp_path / ".token_key"
    monkeypatch.setattr("backend.token_encryption._KEY_FILE", key_file)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    yield
    reset_for_testing()


class TestEncryptDecrypt:
    def test_round_trip(self):
        plaintext = "my-secret-access-token-12345"
        ciphertext = encrypt(plaintext)
        assert ciphertext != plaintext
        assert decrypt(ciphertext) == plaintext

    def test_different_ciphertexts(self):
        """Each encryption produces a different ciphertext (Fernet uses random IV)."""
        plaintext = "same-token"
        c1 = encrypt(plaintext)
        c2 = encrypt(plaintext)
        assert c1 != c2
        assert decrypt(c1) == decrypt(c2) == plaintext

    def test_empty_string(self):
        ciphertext = encrypt("")
        assert decrypt(ciphertext) == ""


class TestDecryptOrPlaintext:
    def test_encrypted_value(self):
        original = "secret-token"
        encrypted = encrypt(original)
        value, was_encrypted = decrypt_or_plaintext(encrypted)
        assert value == original
        assert was_encrypted is True

    def test_plaintext_value(self):
        plaintext = "ya29.plaintext-access-token"
        value, was_encrypted = decrypt_or_plaintext(plaintext)
        assert value == plaintext
        assert was_encrypted is False

    def test_json_plaintext(self):
        """Plain JSON (like a Gmail token file) is detected as not encrypted."""
        token_json = json.dumps({"token": "ya29.xxx", "refresh_token": "1//xxx"})
        value, was_encrypted = decrypt_json_or_plaintext(token_json)
        assert value == token_json
        assert was_encrypted is False

    def test_json_encrypted(self):
        token_json = json.dumps({"token": "ya29.xxx"})
        encrypted = encrypt_json(token_json)
        value, was_encrypted = decrypt_json_or_plaintext(encrypted)
        assert value == token_json
        assert was_encrypted is True


class TestKeyPersistence:
    def test_auto_generates_key_file(self, tmp_path, monkeypatch):
        key_file = tmp_path / "subdir" / ".token_key"
        monkeypatch.setattr("backend.token_encryption._KEY_FILE", key_file)
        reset_for_testing()

        encrypt("test")

        assert key_file.exists()
        # File should have restricted permissions
        assert oct(key_file.stat().st_mode & 0o777) == "0o600"

    def test_reuses_existing_key(self, tmp_path, monkeypatch):
        key_file = tmp_path / ".token_key"
        monkeypatch.setattr("backend.token_encryption._KEY_FILE", key_file)
        reset_for_testing()

        encrypted = encrypt("test-value")

        # Reset and re-initialize — should reuse the same key
        reset_for_testing()
        assert decrypt(encrypted) == "test-value"

    def test_env_var_overrides_file(self, tmp_path, monkeypatch):
        from cryptography.fernet import Fernet

        custom_key = Fernet.generate_key().decode()
        monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", custom_key)
        reset_for_testing()

        encrypted = encrypt("env-key-test")
        # Decrypt with the same env key
        assert decrypt(encrypted) == "env-key-test"

        # The key file should NOT have been created
        key_file = tmp_path / ".token_key_env"
        assert not key_file.exists()
