"""The only code that reaches Google, and the only place a Google credential is read.

``GOOGLE_CLIENT_ID`` and ``GOOGLE_CLIENT_SECRET`` identify Reli to Google, with
``GOOGLE_AUTH_REDIRECT_URI`` as the address Google sends the browser back to. The invariant is that
nothing here persists anything. The identity that comes out of an exchange is returned to
the caller and never written by this module, and the access token Google sends beside the id token
is never read.

The id token's claims are verified — audience, issuer, expiry, a verified email — but its
signature is not. It arrives directly from Google's token endpoint over TLS, in a request
authenticated with the client secret, which is the case Google's OpenID Connect documentation
describes as not needing signature validation.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from .config import settings

AUTH_SCOPES: tuple[str, ...] = ("openid", "email", "profile")

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"

TOKEN_URL = "https://oauth2.googleapis.com/token"

ISSUERS: tuple[str, ...] = ("https://accounts.google.com", "accounts.google.com")

_TIMEOUT_SECONDS = 10.0


class GoogleSignInFailed(RuntimeError):
    """Google did not turn the authorization code into a usable identity. The message is the remedy."""


@dataclass(frozen=True)
class Identity:
    """Who signed in: Google's stable ``sub`` for the account, and its verified email, lower-cased."""

    subject: str
    email: str


def s256_challenge(verifier: str) -> str:
    """The PKCE ``S256`` challenge for *verifier* (RFC 7636 §4.2)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorization_url(state: str, code_verifier: str) -> str:
    """Where to send the browser to sign in, carrying *state* and the challenge of *code_verifier*.

    ``prompt=select_account`` lets the owner pick the allowlisted account when several are signed
    in. No ``access_type=offline``: a sign-in needs no Google refresh token.
    """
    query = urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_AUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(AUTH_SCOPES),
            "state": state,
            "code_challenge": s256_challenge(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"


def _http_client() -> httpx.Client:
    """The single place an ``httpx.Client`` is built, so tests have one transport to replace."""
    return httpx.Client(timeout=_TIMEOUT_SECONDS)


def exchange_code(code: str, code_verifier: str) -> Identity:
    """Turn the authorization code Google sent back into the identity that signed in.

    Raises:
        GoogleSignInFailed: Google refused the exchange, or the id token's claims do not hold.
    """
    with _http_client() as client:
        response = client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_AUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )

    if response.status_code >= 400:
        raise GoogleSignInFailed(_failure_message(response))

    payload: dict[str, Any] = response.json()
    id_token = payload.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise GoogleSignInFailed("Google's token response carried no id_token: start the sign-in again.")

    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            options={
                "verify_signature": False,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["sub", "email", "exp", "aud", "iss"],
            },
            audience=settings.GOOGLE_CLIENT_ID,
            issuer=list(ISSUERS),
        )
    except jwt.InvalidTokenError as invalid:
        raise GoogleSignInFailed(
            f"Google's id token was not acceptable ({invalid}): start the sign-in again."
        ) from invalid

    if claims.get("email_verified") is not True:
        raise GoogleSignInFailed("Google has not verified the email on this account: sign in with a verified account.")

    return Identity(subject=str(claims["sub"]), email=str(claims["email"]).lower())


def _failure_message(response: httpx.Response) -> str:
    """Say what Google said, and what a human must do about it."""
    try:
        error: str = str(response.json().get("error", ""))
    except ValueError:
        error = ""

    if error == "redirect_uri_mismatch":
        return (
            "Google refused the sign-in as redirect_uri_mismatch: a human adds "
            f"{settings.GOOGLE_AUTH_REDIRECT_URI!r} to the authorised redirect URIs of the OAuth client "
            "GOOGLE_CLIENT_ID names, in the Google Cloud console."
        )
    if error in ("invalid_grant", "invalid_client"):
        return (
            f"Google refused the sign-in as {error}: start the sign-in again. If it "
            "keeps failing, a human checks GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the deploy."
        )
    return f"Google refused the sign-in with HTTP {response.status_code}" + (f" ({error})" if error else "")
