"""The one seam between Reli and Google's REST APIs, and the only place a credential is read.

Two invariants hold here, and both are covered by tests:

- The credential is read from :mod:`backend.config` and written nowhere. There is no file, no
  table, no journal entry; the access token lives in a module-level cache and dies with the
  process. #938 was a token file left behind by a migration — code that never writes a credential
  cannot leave one behind.
- Every call to a Google API is a ``GET``. :func:`get_json` is the only function that reaches one,
  and it has no verb parameter.

The refresh token is human-provisioned via ``scripts/google_oauth_grant.py``; nothing in this
service can mint one.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .config import settings

SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
)

TOKEN_URL = "https://oauth2.googleapis.com/token"

_TIMEOUT_SECONDS = 10.0

# Refresh a little before the token actually dies: treating an expiry as valid until the last
# second produces intermittent 401s in production, where the clock and the network both drift.
_EXPIRY_SKEW = timedelta(seconds=60)

_GRANT_COMMAND = "uv run python scripts/google_oauth_grant.py"


class GoogleError(RuntimeError):
    """Anything that stopped a Google read from succeeding."""


class GoogleNotConfigured(GoogleError):
    """No Google credential is set, so there is nothing to read with."""


class GoogleAuthFailed(GoogleError):
    """The credential exists but Google refused it."""


class GoogleApiError(GoogleError):
    """A Google API answered a read with an error status."""


_token_lock = threading.Lock()
_token: str | None = None
_token_expires_at: datetime | None = None


def is_configured() -> bool:
    """Whether all three human-provisioned Google settings are present."""
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REFRESH_TOKEN)


def reset_token_cache() -> None:
    """Forget the cached access token. The only way the cache is cleared."""
    global _token, _token_expires_at
    with _token_lock:
        _token = None
        _token_expires_at = None


def _http_client() -> httpx.Client:
    """The single place an ``httpx.Client`` is built, so tests have one transport to replace."""
    return httpx.Client(timeout=_TIMEOUT_SECONDS)


def _require_configured() -> None:
    if not is_configured():
        raise GoogleNotConfigured(
            "Google is not configured: set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and "
            f"GOOGLE_REFRESH_TOKEN. A human obtains the refresh token by running `{_GRANT_COMMAND}`."
        )


def _refresh_access_token() -> tuple[str, datetime]:
    with _http_client() as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": settings.GOOGLE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
        )

    if response.status_code >= 400:
        raise GoogleAuthFailed(_auth_failure_message(response))

    payload: dict[str, Any] = response.json()
    access_token: str = payload["access_token"]
    expires_in: int = int(payload.get("expires_in", 3600))
    return access_token, datetime.now(UTC) + timedelta(seconds=expires_in)


def _auth_failure_message(response: httpx.Response) -> str:
    """Say what Google said, and — when the grant itself is dead — what a human must do about it."""
    try:
        error: str = str(response.json().get("error", ""))
    except ValueError:
        error = ""

    if error == "invalid_grant":
        return (
            "Google rejected GOOGLE_REFRESH_TOKEN as invalid_grant: the grant is no longer valid "
            f"(revoked or expired) and a human must re-run `{_GRANT_COMMAND}` and replace "
            "GOOGLE_REFRESH_TOKEN."
        )
    return f"Google refused the refresh token with HTTP {response.status_code}" + (f" ({error})" if error else "")


def _access_token(force_refresh: bool = False) -> str:
    global _token, _token_expires_at
    with _token_lock:
        fresh_enough = _token_expires_at is not None and datetime.now(UTC) + _EXPIRY_SKEW < _token_expires_at
        if _token is not None and fresh_enough and not force_refresh:
            return _token

        _token, _token_expires_at = _refresh_access_token()
        return _token


def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """``GET`` a Google API and return its JSON body. The only function here that leaves the process.

    A 401 costs one refresh and one retry — an access token can expire mid-flight, and Google is
    the authority on that, not the cached ``expires_in``. A second 401 is a credential problem.

    Raises:
        GoogleNotConfigured: One of the three Google settings is empty.
        GoogleAuthFailed: Google refused the credential.
        GoogleApiError: The API answered with any other error status.
    """
    _require_configured()

    with _http_client() as client:
        response = client.get(url, params=params, headers={"Authorization": f"Bearer {_access_token()}"})
        if response.status_code == 401:
            response = client.get(
                url, params=params, headers={"Authorization": f"Bearer {_access_token(force_refresh=True)}"}
            )
            if response.status_code == 401:
                raise GoogleAuthFailed(
                    f"Google answered 401 to {response.request.url.path} after refreshing the access "
                    f"token. A human may need to re-run `{_GRANT_COMMAND}` and replace GOOGLE_REFRESH_TOKEN."
                )

    if response.status_code >= 400:
        raise GoogleApiError(f"Google answered HTTP {response.status_code} to {response.request.url.path}")

    payload: dict[str, Any] = response.json()
    return payload
