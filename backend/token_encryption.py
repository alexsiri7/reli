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

from cryptography.fernet import Fernet

from .config import settings

logger = logging.getLogger(__name__)

_PRIMARY_KEY_FILE = Path(settings.DATA_DIR) / ".token_key"
_FALLBACK_KEY_DIR = Path("/tmp/.reli")
_FALLBACK_KEY_FILE = _FALLBACK_KEY_DIR / ".token_key"

_fernet: Fernet | None = None


def _is_production() -> bool:
    return bool(os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("PRODUCTION"))


def _key_file_path() -> Path:
    """Return a writable key-file path, preferring DATA_DIR, falling back to /tmp."""
    if _PRIMARY_KEY_FILE.exists():
        return _PRIMARY_KEY_FILE
    # Check if primary directory is writable
    try:
        _PRIMARY_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if os.access(_PRIMARY_KEY_FILE.parent, os.W_OK):
            return _PRIMARY_KEY_FILE
    except OSError:
        pass
    if _is_production():
        logger.critical(
            "TOKEN_ENCRYPTION_KEY is not set and DATA_DIR (%s) is not writable. "
            "Refusing to fall back to world-readable /tmp in production. "
            "Set the TOKEN_ENCRYPTION_KEY environment variable.",
            _PRIMARY_KEY_FILE.parent,
        )
        raise RuntimeError(
            "Cannot store token encryption key securely: DATA_DIR is not writable "
            "and TOKEN_ENCRYPTION_KEY is not set. Set TOKEN_ENCRYPTION_KEY env var."
        )
    return _FALLBACK_KEY_FILE


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
    key_file = _key_file_path()
    if key_file.exists():
        key = key_file.read_text().strip()
    else:
        key = Fernet.generate_key().decode()
        try:
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(key)
            key_file.chmod(0o600)
            logger.info("Generated new token encryption key at %s", key_file)
        except OSError:
            if _is_production():
                logger.critical(
                    "Could not write token encryption key to %s in production. "
                    "Set TOKEN_ENCRYPTION_KEY environment variable.",
                    key_file,
                )
                raise RuntimeError(
                    f"Cannot write token encryption key to {key_file}. Set TOKEN_ENCRYPTION_KEY env var in production."
                )
            # Non-production only: fall back to /tmp
            try:
                _FALLBACK_KEY_DIR.mkdir(parents=True, exist_ok=True)
                _FALLBACK_KEY_FILE.write_text(key)
                _FALLBACK_KEY_FILE.chmod(0o600)
                logger.warning(
                    "Could not write key to %s, using fallback %s",
                    key_file,
                    _FALLBACK_KEY_FILE,
                )
            except OSError as fallback_err:
                logger.error(
                    "Could not write token encryption key to fallback %s either: %s. "
                    "Set TOKEN_ENCRYPTION_KEY environment variable.",
                    _FALLBACK_KEY_FILE,
                    fallback_err,
                )
                raise

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
    except Exception:
        return value, False


def reset_for_testing() -> None:
    """Reset the cached Fernet instance (for tests only)."""
    global _fernet
    _fernet = None
