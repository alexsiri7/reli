"""Simple API-key authentication for single-user Reli deployment."""

import os
import secrets
from pathlib import Path

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

_data_dir = os.environ.get("DATA_DIR", str(Path(__file__).parent))
_KEY_FILE = Path(_data_dir) / "api_key.txt"

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_or_create_key() -> str:
    """Load the API key from disk, or generate one on first run."""
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
        if key:
            return key
    key = secrets.token_urlsafe(32)
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(key + "\n")
    _KEY_FILE.chmod(0o600)
    return key


API_KEY: str = _load_or_create_key()


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """FastAPI dependency that validates the X-API-Key header."""
    if api_key is None or not secrets.compare_digest(api_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key
