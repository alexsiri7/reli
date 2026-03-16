"""Symmetric encryption for OAuth tokens at rest.

Uses Fernet (AES-128-CBC with HMAC-SHA256) from the ``cryptography``
package.  The encryption key is read from the ``TOKEN_ENCRYPTION_KEY``
environment variable (base64-encoded 32-byte key).  If the variable is
not set, a key is auto-generated and persisted to a file alongside the
database so that tokens survive restarts.

Plaintext tokens written before encryption was enabled are transparently
migrated on first read: if decryption fails, the value is assumed to be
plaintext, re-encrypted, and written back.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

logger = logging.getLogger(__name__)

_KEY_FILE = Path(settings.DATA_DIR) / ".token_key"

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Return a cached Fernet instance, creating the key if needed."""
    global _fernet
    if _fernet is not None:
        return _fernet

    # Read at call time so tests can override via monkeypatch
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")

    if key:
        # Validate that it's a proper Fernet key (url-safe base64, 32 bytes)
        _fernet = Fernet(key.encode())
        return _fernet

    # Auto-generate and persist a key file
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
    else:
        key = Fernet.generate_key().decode()
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(key)
        # Restrict permissions to owner-only
        _KEY_FILE.chmod(0o600)
        logger.info("Generated new token encryption key at %s", _KEY_FILE)

    _fernet = Fernet(key.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return the Fernet token as a UTF-8 string."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token string. Returns the plaintext."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


def decrypt_or_plaintext(value: str) -> tuple[str, bool]:
    """Try to decrypt *value*.  If it fails, assume it's plaintext.

    Returns ``(plaintext, was_encrypted)`` — callers can use the flag to
    decide whether to re-encrypt and write back the migrated value.
    """
    try:
        return decrypt(value), True
    except (InvalidToken, Exception):
        return value, False


def encrypt_json(data: str) -> str:
    """Encrypt a JSON string (used for Gmail token file)."""
    return encrypt(data)


def decrypt_json(data: str) -> str:
    """Decrypt an encrypted JSON string."""
    return decrypt(data)


def decrypt_json_or_plaintext(data: str) -> tuple[str, bool]:
    """Try to decrypt JSON data; if it fails, assume plaintext JSON.

    Returns ``(json_str, was_encrypted)``.
    """
    return decrypt_or_plaintext(data)


def reset_for_testing() -> None:
    """Reset the cached Fernet instance (for tests only)."""
    global _fernet
    _fernet = None
