"""One-time Google consent, run by a human on their own machine.

Reli cannot mint a Google refresh token: consent requires a person signed in to the Google account
whose Calendar and Gmail are being read. Run this once, then paste the printed refresh token into
`.env` or the Railway variables as GOOGLE_REFRESH_TOKEN.

    export GOOGLE_CLIENT_ID=...
    export GOOGLE_CLIENT_SECRET=...
    uv run python scripts/google_oauth_grant.py

The client id and secret are the same **Web application** OAuth client the sign-in uses — the pair
`backend/google_client.py` refreshes with, so a token minted here is refreshable there. A Web client
accepts only a redirect URI registered verbatim, so before the first run a human adds
`http://127.0.0.1:18765/` (exact string, trailing slash included) to that client's authorised
redirect URIs in the Google Cloud console; a missing entry answers `redirect_uri_mismatch` on the
consent page. The arbitrary-port loopback flow the first version of this script assumed is a
feature of a different client type, and this deploy's client is a Web client (#1460). The id and
secret are read from the environment rather than taken as arguments, so they do not land in shell
history.

This script writes no file. Nothing in Reli ever writes a Google credential anywhere — that is what
keeps #938 (a token file left behind on disk) from happening a second time.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.google_client import SCOPES, TOKEN_URL  # noqa: E402

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# Fixed, and deliberately not configurable: a Web application client only accepts a redirect URI
# registered verbatim, port and trailing slash included. An ephemeral port was #1460, and a port
# read from the environment would fail at Google the same way unless it happened to be registered.
REDIRECT_PORT = 18765
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/"


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches the one redirect Google makes back to the loopback address."""

    code: str | None = None
    state: str | None = None

    def do_GET(self) -> None:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = params.get("code", [None])[0]
        _CallbackHandler.state = params.get("state", [None])[0]
        body = b"Reli has the grant. You can close this tab and return to the terminal."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default request log: the URL it prints carries the authorization code."""


def consent_url(client_id: str, state: str, challenge: str) -> str:
    return f"{AUTH_URL}?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            # offline + consent is what makes Google return a refresh token rather than only an
            # access token; without them a re-grant hands back nothing to store.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def main() -> int:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first (the Web application OAuth client the sign-in uses)."
        )
        return 1

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    try:
        server = HTTPServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    except OSError:
        print(
            f"Port {REDIRECT_PORT} is in use. The grant must come back to {REDIRECT_URI} — the URI "
            "registered on the OAuth client — so free the port and run this again."
        )
        return 1

    consent = consent_url(client_id, state, challenge)

    print(f"Granting: {', '.join(SCOPES)}")
    print(f"\nOpen this and approve:\n\n{consent}\n")
    webbrowser.open(consent)
    server.handle_request()
    server.server_close()

    if _CallbackHandler.state != state:
        print("The callback carried the wrong state. Nothing was exchanged; run this again.")
        return 1
    if not _CallbackHandler.code:
        print("Google sent no authorization code back. Nothing was exchanged; run this again.")
        return 1

    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": _CallbackHandler.code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        print(f"Google refused the exchange with HTTP {response.status_code}: {response.text}")
        return 1

    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        print(
            "Google returned no refresh token. Revoke Reli's access at "
            "https://myaccount.google.com/permissions and run this again."
        )
        return 1

    print("\nPaste this into .env or the Railway variables as GOOGLE_REFRESH_TOKEN:\n")
    print(refresh_token)
    print("\nIt is not stored anywhere by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
