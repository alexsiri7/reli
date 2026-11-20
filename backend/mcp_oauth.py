"""The OAuth 2.1 authorization server an MCP client authorises against, restored from the pre-v4 tree.

Implements the MCP authorization spec
(https://modelcontextprotocol.io/specification/draft/basic/authorization):

- ``GET  /.well-known/oauth-protected-resource``   — RFC 9728
- ``GET  /.well-known/oauth-authorization-server`` — RFC 8414
- ``POST /oauth/register``                          — RFC 7591 dynamic client registration
- ``GET  /oauth/authorize``                         — sends the browser to Google, then back to the
  client with an authorization code via :func:`backend.auth.google_callback`
- ``POST /oauth/token``                             — code or refresh token for an ``aud="mcp"`` JWT

PKCE is mandatory and only ``S256`` is accepted; refresh tokens rotate on every use, and presenting
one that has already been rotated away revokes every token from that sign-in (OAuth 2.1 §4.3.1), so
the connector re-authorises. The identity step is Google's: a client never holds a shared secret,
and a token is only ever minted for an account in ``ALLOWED_EMAILS`` — re-checked on every
issuance, not just at sign-in, so removing an email cuts off its refresh chain. Rotation preserves
the family's original expiry rather than renewing it, so a family cannot outlive its sign-in by
refreshing indefinitely. A registration lives an hour until its first token is minted, then exactly
as long as that family; the stores a caller without a credential can write to evict their row
nearest expiry rather than refuse, so a flood of registrations or sign-in starts displaces other
unfinished flows and nothing else. The JWT is the only credential ``/mcp`` accepts, and it lives an
hour: when the client holds a refresh family, the token names it, and revoking the family ends it
on its next request.
"""

from __future__ import annotations

import html
import logging
import secrets
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from pydantic import AfterValidator, AnyUrl, BaseModel, ValidationError
from sqlmodel import Session

from . import auth, google_login
from .config import settings
from .oauth_state import (
    Store,
    StoreFullError,
    cleanup_and_get,
    cleanup_and_pop,
    cleanup_and_store,
    consume_refresh_token,
    credential_digest,
    extend_expiry,
    mcp_auth_codes,
    mcp_oauth_sessions,
    mcp_refresh_tokens,
    mcp_registered_clients,
    revoke_refresh_token_family,
)

logger = logging.getLogger(__name__)

# A sign-in that takes longer than this answers "start again", which is the remedy.
SESSION_TTL_SECONDS = 60 * 10
# RFC 6819 §4.1.1: an authorization code lives just long enough to be exchanged.
AUTH_CODE_TTL_SECONDS = 60
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
# The life of a registration the owner has signed in through: that of the refresh family it serves.
CLIENT_TTL_SECONDS = REFRESH_TOKEN_TTL_SECONDS
# Until then a registration lives an hour — longer than any sign-in it can host (a ten-minute
# session plus a one-minute code), short enough that eviction reaches an unused registration long
# before a used one. A person who takes over an hour between adding the connector and finishing
# the sign-in re-adds it.
UNUSED_CLIENT_TTL_SECONDS = 60 * 60
# A real registration is a few hundred bytes, and a consent or token form fewer. This bounds what
# any request body here can hold in memory, and with it every stored field of a registration.
MAX_BODY_BYTES = 8 * 1024
# The longest redirect URI a registration keeps, in UTF-8 bytes, and the bound authorize puts on
# every value it stores. Percent-encoding turns a byte into at most three, so a token form carrying
# the longest URI still fits in MAX_BODY_BYTES — a bound in characters would not, since one
# character can be four bytes.
MAX_PARAM_LENGTH = 2048

_CODE_GONE = "Authorization code is invalid or expired: re-authorise the connector"
_REFRESH_TOKEN_GONE = "Refresh token is invalid or expired: re-authorise the connector"
# The only client authentication methods /oauth/token implements: a secret arrives in the form
# body or not at all. Registration refuses any other, so a client is never told to authenticate a
# way that would fail.
TOKEN_ENDPOINT_AUTH_METHODS = ("none", "client_secret_post")
# The one scope there is: every token grants the whole graph, so any other name would promise a
# narrower grant than the token carries.
MCP_SCOPE = "mcp"
_NO_STORE = {"Cache-Control": "no-store"}


def _too_large() -> HTTPException:
    return HTTPException(status_code=413, detail=f"Request body must be at most {MAX_BODY_BYTES} bytes")


async def _read_bounded(request: Request) -> bytes:
    """The body of *request*, refused with 413 once it passes ``MAX_BODY_BYTES``.

    A declared ``Content-Length`` over the cap is refused before a byte is read; a chunked or
    understated body is refused as soon as what has arrived passes it.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body)


class _BoundedBodyRoute(APIRoute):
    """A route whose body is read through :func:`_read_bounded` before anything else sees it.

    Every route here answers a caller with no credential, and FastAPI reads a ``Form`` body whole
    before the endpoint runs, with no limit of its own — so the cap has to stand in front of it.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            # Starlette's own cache of a body already read: every later reader is served from it.
            request._body = await _read_bounded(request)
            return await handler(request)

        return bounded


router = APIRouter(tags=["oauth"], route_class=_BoundedBodyRoute)


def _within_param_bytes(value: str) -> str:
    if len(value.encode()) > MAX_PARAM_LENGTH:
        raise ValueError(f"must be at most {MAX_PARAM_LENGTH} bytes as UTF-8")
    return value


_RedirectUri = Annotated[str, AfterValidator(_within_param_bytes)]


# --- Discovery -------------------------------------------------------------


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def protected_resource_metadata() -> JSONResponse:
    base = auth.base_url()
    return JSONResponse(
        {
            "resource": f"{base}/mcp/",
            "authorization_servers": [base],
            "scopes_supported": [MCP_SCOPE],
        }
    )


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def authorization_server_metadata() -> JSONResponse:
    base = auth.base_url()
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": list(TOKEN_ENDPOINT_AUTH_METHODS),
            "scopes_supported": [MCP_SCOPE],
        }
    )


def _is_supported_scope(scope: str) -> bool:
    """Whether *scope* asks for ``mcp`` and nothing else; an empty one is the default, RFC 6749 §3.3."""
    return set(scope.split()) <= {MCP_SCOPE}


# --- Registration ----------------------------------------------------------


class _ClientMetadata(BaseModel):
    """The RFC 7591 metadata a registration keeps. Anything else in the body is ignored, as §2 allows."""

    redirect_uris: list[_RedirectUri] | None = None
    client_name: str = ""
    grant_types: list[str] = ["authorization_code"]
    response_types: list[str] = ["code"]
    token_endpoint_auth_method: str = "client_secret_post"
    scope: str = MCP_SCOPE


def _describe(invalid: ValidationError) -> str:
    """The first problem only, as a field path and pydantic's own message.

    Nothing from the body reaches the log or the response, and the size of neither follows the body:
    a list of thousands of wrong elements is one error, not one line each.
    """
    first = invalid.errors()[0]
    return f"{'.'.join(str(part) for part in first['loc']) or 'body'}: {first['msg']}"


def _as_delivered(uri: str) -> AnyUrl:
    """``uri`` as the browser reads it once ``auth.client_redirect`` sends it there.

    ``RedirectResponse`` percent-quotes the URL on the way out, which changes what some characters
    mean: a backslash, which the URL standard reads as ``/``, arrives as ``%5C`` and leaves whatever
    precedes the next ``@`` as user info. So the registered string is sent through that same
    redirect and its ``Location`` parsed by ``AnyUrl``, which parses as a browser does (WHATWG);
    the query the redirect appends cannot move the authority. Raises ``ValidationError`` when that
    form is not a URL.
    """
    return AnyUrl(auth.client_redirect(uri, "").headers["location"])


def _redirect_uri_is_safe(uri: str) -> bool:
    """Whether ``uri`` may receive an authorization code.

    It must be ``https``, or ``http`` to localhost, and carry no userinfo, as the browser reads it,
    so the host checked is the host the code is delivered to (#1702).
    """
    try:
        parsed = _as_delivered(uri)
    except ValidationError:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.host in ("localhost", "127.0.0.1"))


def _validate_registration_body(raw: bytes) -> _ClientMetadata:
    try:
        return _ClientMetadata.model_validate_json(raw)
    except ValidationError as invalid:
        problems = _describe(invalid)
        logger.warning("MCP OAuth: rejected registration with invalid client metadata: %s", problems)
        raise HTTPException(status_code=400, detail=f"invalid_client_metadata: {problems}") from invalid


def _validate_auth_method(metadata: _ClientMetadata) -> str:
    auth_method = metadata.token_endpoint_auth_method
    if auth_method not in TOKEN_ENDPOINT_AUTH_METHODS:
        logger.warning(
            "MCP OAuth: rejected token_endpoint_auth_method during registration: %s", auth.log_repr.repr(auth_method)
        )
        raise HTTPException(
            status_code=400,
            detail=f"token_endpoint_auth_method must be one of {', '.join(TOKEN_ENDPOINT_AUTH_METHODS)}: {auth_method}",
        )
    return auth_method


def _validate_scope(metadata: _ClientMetadata) -> None:
    if not _is_supported_scope(metadata.scope):
        logger.warning("MCP OAuth: rejected scope during registration: %s", auth.log_repr.repr(metadata.scope))
        raise HTTPException(status_code=400, detail=f"invalid_client_metadata: scope must be {MCP_SCOPE}")


def _validate_redirect_uris(redirect_uris: list[str]) -> None:
    for uri in redirect_uris:
        if not _redirect_uri_is_safe(uri):
            logger.warning("MCP OAuth: rejected unsafe redirect_uri during registration: %s", auth.log_repr.repr(uri))
            raise HTTPException(
                status_code=400,
                detail=(
                    "redirect_uri must use https with no user info "
                    f"(or http://localhost / http://127.0.0.1 for development): {uri}"
                ),
            )


@router.post("/oauth/register", include_in_schema=False)
async def oauth_register(request: Request) -> JSONResponse:
    """Register a client (RFC 7591). Single-tenant: no approval step.

    This is an unauthenticated write, by design — dynamic registration is how a connector that holds
    no credential yet gets one, and the Google sign-in behind ``/oauth/authorize`` is what gates
    identity. What it can cost is bounded: a row of at most ``MAX_BODY_BYTES`` that lives an
    hour unless the owner signs in through it, in a store that evicts the registration nearest
    expiry rather than refusing. A flood therefore displaces other unused registrations — a set-up
    that races it can lose — never a connector the owner has signed in through, and nothing outlasts
    the flood. A registration never yields a token.

    Raises:
        HTTPException 400: The body is not a JSON object of the shapes ``_ClientMetadata`` names, a
            ``redirect_uri`` is not ``https`` (``http`` only for localhost) with no user info or is
            longer than ``MAX_PARAM_LENGTH`` bytes as UTF-8, ``token_endpoint_auth_method`` is one
            the token endpoint does not implement, or ``scope`` names anything but ``mcp``.
        HTTPException 413: The body is over ``MAX_BODY_BYTES``, refused by ``_BoundedBodyRoute``.
    """
    raw = await request.body()
    metadata = _validate_registration_body(raw)
    auth_method = _validate_auth_method(metadata)
    _validate_scope(metadata)
    redirect_uris = metadata.redirect_uris or []
    _validate_redirect_uris(redirect_uris)

    client_id = str(uuid.uuid4())
    client_secret = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    client = {
        "client_secret": credential_digest(client_secret),
        "redirect_uris": redirect_uris,
        "client_name": metadata.client_name,
        "grant_types": metadata.grant_types,
        "response_types": metadata.response_types,
        "token_endpoint_auth_method": auth_method,
        "scope": MCP_SCOPE,
        "expires_at": now + timedelta(seconds=UNUSED_CLIENT_TTL_SECONDS),
    }
    with auth.open_db_session() as session:
        cleanup_and_store(session, mcp_registered_clients, client_id, client)

    logger.info("MCP OAuth: registered client %s (%s)", client_id, auth.log_repr.repr(metadata.client_name))

    return JSONResponse(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": client["redirect_uris"],
            "client_name": client["client_name"],
            "grant_types": client["grant_types"],
            "response_types": client["response_types"],
            "token_endpoint_auth_method": client["token_endpoint_auth_method"],
            "scope": client["scope"],
            # The life the registration has once the owner signs in through it. Advertising the
            # one-hour grace instead would have a client that honours the field re-register hourly
            # and lose its refresh family each time.
            "client_secret_expires_at": int((now + timedelta(seconds=CLIENT_TTL_SECONDS)).timestamp()),
        },
        status_code=201,
    )


# --- Authorization ---------------------------------------------------------


def _consent_page(server_state: str, client_name: str, redirect_uri: str) -> HTMLResponse:
    """The approval step between the client's request and the Google sign-in.

    Names the registered client and where its authorization code will be delivered, so a link the
    owner did not initiate announces itself instead of completing silently (confused deputy):
    without this page, ``/oauth/authorize`` sent the browser straight to Google and back to
    whatever client had registered, with nothing on any screen naming it. The host is shown on its own,
    read as ``_redirect_uri_is_safe`` reads it, so it is the host the code reaches. The host leads
    because it is the one value on the page Reli establishes; registration is open, so the name is
    whatever the client chose and is shown as self-declared (#1811).
    """
    name = html.escape(client_name)
    name_sentence = (
        f"The client calls itself &ldquo;{name}&rdquo; (self-declared — Reli has not verified it)."
        if name
        else "It gave no name."
    )
    host = html.escape(_as_delivered(redirect_uri).host or "")
    uri = html.escape(redirect_uri)
    state = html.escape(server_state)
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>Authorize access to Reli</title>"
        "<meta name='robots' content='noindex'></head><body>"
        "<h1>Authorize access to Reli?</h1>"
        "<p>Continuing gives full access to your graph to whatever receives the sign-in result at "
        f"<strong>{host}</strong> (<code>{uri}</code>).</p>"
        f"<p>{name_sentence}</p>"
        "<p>Only continue if you just started this from a connector you are setting up and "
        f"<strong>{host}</strong> is where you expect it to land.</p>"
        "<form method='post' action='/oauth/authorize/confirm'>"
        f"<input type='hidden' name='server_state' value='{state}'>"
        "<button type='submit'>Continue with Google</button></form>"
        "</body></html>",
        headers=_NO_STORE,
    )


@router.get("/oauth/authorize", include_in_schema=False)
def oauth_authorize(
    client_id: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = "",
    redirect_uri: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = "",
    state: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = "",
    code_challenge: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = "",
    code_challenge_method: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = "S256",
    scope: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = MCP_SCOPE,
    response_type: Annotated[str, Query(max_length=MAX_PARAM_LENGTH)] = "code",
) -> HTMLResponse:
    """Take the client's request, remember it, and show a consent page naming it before Google.

    Refuses up front — 501 naming every empty setting — when the sign-in cannot complete, so nobody
    is sent through Google only to be bounced at the callback.
    """
    missing = auth.missing_sign_in_settings()
    if missing:
        logger.error("MCP OAuth: authorize refused, sign-in not configured: %s", ", ".join(missing))
        raise HTTPException(status_code=501, detail=auth.not_configured_detail(missing))
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only code_challenge_method=S256 is supported")
    if not _is_supported_scope(scope):
        raise HTTPException(status_code=400, detail=f"invalid_scope: only scope={MCP_SCOPE} is supported")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri is required")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="code_challenge is required (PKCE required)")

    with auth.open_db_session() as session:
        registered = cleanup_and_get(session, mcp_registered_clients, client_id)
        if registered is None:
            raise HTTPException(status_code=400, detail="Unknown client_id — register first via POST /oauth/register")
        if redirect_uri not in registered["redirect_uris"]:
            raise HTTPException(status_code=400, detail="redirect_uri not registered for this client")
        # A registration stored before the check tightened can still hold an unsafe URI.
        if not _redirect_uri_is_safe(redirect_uri):
            logger.warning(
                "MCP OAuth: refused stored unsafe redirect_uri for client %s: %s",
                client_id,
                auth.log_repr.repr(redirect_uri),
            )
            raise HTTPException(
                status_code=400, detail="redirect_uri is not one this server accepts: re-register the client"
            )

        server_state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        cleanup_and_store(
            session,
            mcp_oauth_sessions,
            server_state,
            {
                "client_state": state,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "client_id": client_id,
                "scope": MCP_SCOPE,
                "google_code_verifier": code_verifier,
                "expires_at": datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS),
            },
        )

    return _consent_page(server_state, registered["client_name"], redirect_uri)


@router.post("/oauth/authorize/confirm", include_in_schema=False)
def oauth_authorize_confirm(request: Request, server_state: str = Form(...)) -> RedirectResponse:
    """The owner approved the named client on the consent page: now send the browser to Google.

    *server_state* is not a secret an attacker cannot obtain — the attacker registers their own
    client and runs ``GET /oauth/authorize`` themselves to read one out of their own consent page.
    What must be refused is a cross-site auto-submitting form reusing that value against the
    owner's browser, which would complete the flow with nobody having seen the consent page at
    all. A browser always sends ``Origin`` on a POST, same-origin included, and never lets script
    override it, so this is what actually distinguishes the real form's submission from a lure's.
    Single-use consumption of the underlying flow stays where it already was, at the Google
    callback. The ``MCP_FLOW_COOKIE`` set here is what lets that callback refuse a state this
    browser never approved (#1701).
    """
    if not auth.is_same_origin(request):
        raise HTTPException(
            status_code=400, detail="Approve from Reli's own consent page: start again from the connector."
        )
    with auth.open_db_session() as session:
        flow = cleanup_and_get(session, mcp_oauth_sessions, server_state)
    if flow is None:
        raise HTTPException(status_code=400, detail="Sign-in expired: start again from the connector.")
    response = RedirectResponse(
        url=google_login.authorization_url(server_state, flow["google_code_verifier"]), status_code=302
    )
    auth.set_host_cookie(response, auth.MCP_FLOW_COOKIE, server_state, SESSION_TTL_SECONDS)
    return response


def finish_sign_in(session: Session, flow: dict[str, Any], code: str, error: str) -> RedirectResponse:
    """The MCP branch of :func:`backend.auth.google_callback`: an authorization code for the client, or why not.

    A cancelled sign-in or an account outside the allowlist is delivered to the client's redirect
    URI as an ``access_denied`` error (RFC 6749 §4.1.2.1), because that is where the person is.
    """
    if error:
        logger.info("MCP sign-in cancelled at Google (%s)", auth.log_repr.repr(error))
        return auth.client_redirect(
            flow["redirect_uri"],
            flow["client_state"],
            error="access_denied",
            error_description="Google sign-in was cancelled",
        )

    identity = auth.google_identity("MCP", flow, code)
    if identity is None:
        return auth.client_redirect(
            flow["redirect_uri"], flow["client_state"], error="access_denied", error_description=auth.INVITE_ONLY
        )

    auth_code = secrets.token_urlsafe(32)
    try:
        cleanup_and_store(
            session,
            mcp_auth_codes,
            auth_code,
            {
                "subject": identity.subject,
                "email": identity.email,
                "code_challenge": flow["code_challenge"],
                "code_challenge_method": flow["code_challenge_method"],
                "redirect_uri": flow["redirect_uri"],
                "client_id": flow["client_id"],
                "scope": flow["scope"],
                "expires_at": datetime.now(UTC) + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
            },
        )
    except StoreFullError as full:
        logger.warning("MCP sign-in refused: %s", full)
        raise HTTPException(status_code=503, detail=auth.AT_CAPACITY) from full

    logger.info("MCP sign-in complete for client %r, redirecting to %r", flow["client_id"], flow["redirect_uri"])
    return auth.client_redirect(flow["redirect_uri"], flow["client_state"], code=auth_code)


# --- Tokens ----------------------------------------------------------------


class _TokenError(Exception):
    """An RFC 6749 §5.2 refusal: ``error_description`` is the field a client is specified to surface."""

    def __init__(self, status: int, error: str, description: str) -> None:
        super().__init__(description)
        self.status = status
        self.error = error
        self.description = description


def _invalid_grant(description: str) -> _TokenError:
    return _TokenError(400, "invalid_grant", description)


@dataclass(frozen=True)
class IssuedTokens:
    """What a successful exchange mints, RFC 6749 §5.1; :func:`oauth_token` is what serialises it."""

    access_token: str
    refresh_token: str | None
    scope: str
    expires_in: int


class _Grant(NamedTuple):
    """Whom a consumed code or refresh token was issued to, and for what: what a token is minted from."""

    subject: str
    email: str
    client_id: str
    scope: str

    @classmethod
    def of(cls, row: dict[str, Any]) -> _Grant:
        return cls(row["subject"], row["email"], row["client_id"], row["scope"])


class _ConsumedCode(NamedTuple):
    """A row :func:`cleanup_and_pop` took from ``mcp_auth_codes``."""

    grant: _Grant
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str

    @classmethod
    def of(cls, row: dict[str, Any]) -> _ConsumedCode:
        return cls(_Grant.of(row), row["redirect_uri"], row["code_challenge"], row["code_challenge_method"])


class _ConsumedRefreshToken(NamedTuple):
    """A row :func:`consume_refresh_token` marked consumed, with the identity it held before."""

    grant: _Grant
    family_id: str
    expires_at: datetime

    @classmethod
    def of(cls, row: dict[str, Any]) -> _ConsumedRefreshToken:
        return cls(_Grant.of(row), row["family_id"], row["expires_at"])


def _authenticated_client(session: Session, client_id: str, client_secret: str) -> dict[str, Any]:
    """The registration of *client_id*, once it has authenticated.

    A confidential client must present its secret; a public one (``none``) has none to present.
    """
    client = cleanup_and_get(session, mcp_registered_clients, client_id)
    if client is None:
        raise _TokenError(400, "invalid_client", "Unknown client_id: register again via POST /oauth/register")
    if client["token_endpoint_auth_method"] == "none":
        return client
    if not client_secret or not secrets.compare_digest(credential_digest(client_secret), client["client_secret"]):
        raise _TokenError(401, "invalid_client", "Invalid client credentials: re-register the connector")
    return client


def _may_refresh(client: dict[str, Any]) -> bool:
    """Whether *client* registered the ``refresh_token`` grant; RFC 7591's default leaves it out."""
    return "refresh_token" in client["grant_types"]


def _issue_tokens(
    session: Session, grant: _Grant, family_id: str, expires_at: datetime, *, refreshable: bool
) -> IssuedTokens:
    """An access token and, when *refreshable*, a fresh refresh token for *grant*.

    Re-checks ``ALLOWED_EMAILS`` here, not just at the Google callback, so an account removed
    after sign-in cannot keep rolling its refresh token forward — this covers both grant types,
    since both end here. *expires_at* is the family's deadline: fresh from the code exchange,
    carried forward on rotation rather than renewed. The client's registration is promoted to that
    deadline once the tokens are stored and not before — a client that may not refresh is promoted
    too, since it signs in again through the same registration: a refused issuance leaves it at its
    grace hour, the allowlist check above has already passed, so only an allowed account holds a
    registration past its first hour, and the move is only ever later (``GREATEST``), so a second
    family never shortens it. The access token names *family_id* only when *refreshable*: a client
    that never gets a tracked family has nothing for :func:`auth.is_revoked` to check, so its token
    rides out its hour on the ``jti`` list alone, same as before #1808.

    Raises:
        _TokenError: ``invalid_grant`` when the account has left ``ALLOWED_EMAILS``.
        StoreFullError: ``mcp_refresh_tokens`` is at its cap; nothing was issued.
    """
    if not auth.is_allowed(grant.email):
        revoked = revoke_refresh_token_family(session, family_id)
        logger.warning(
            "MCP OAuth: token refused for client %s — account no longer in ALLOWED_EMAILS; revoked %d token(s)",
            grant.client_id,
            revoked,
        )
        raise _invalid_grant(auth.ACCOUNT_NOT_ALLOWED)
    access_token = auth.create_jwt(
        grant.subject, grant.email, audience=auth.MCP_AUDIENCE, family_id=family_id if refreshable else None
    )
    refresh_token = None
    if refreshable:
        refresh_token = secrets.token_urlsafe(32)
        cleanup_and_store(
            session,
            mcp_refresh_tokens,
            refresh_token,
            {**grant._asdict(), "family_id": family_id, "expires_at": expires_at},
        )
    extend_expiry(session, mcp_registered_clients, grant.client_id, expires_at)
    return IssuedTokens(access_token, refresh_token, grant.scope, auth.MCP_JWT_EXPIRY_SECONDS)


def _authenticated_grant(
    session: Session, store: Store, key: str, client_id: str, client_secret: str, gone: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The grant under *key*, not yet consumed, and the registration of the client it was issued to,
    once that client has authenticated.

    The client is authenticated before the grant is consumed (RFC 6749 §3.2.1 puts client
    authentication ahead of processing the grant), so a wrong secret leaves a still-valid code or
    refresh token for its holder to redeem instead of burning it. The grant is bound to the client
    that asked for it, so an injected code exchanges for nothing. Each exchange then consumes the
    grant its own way, and only what that consume returns may mint a token: for a refresh token
    the row found here may already be consumed.

    Raises:
        _TokenError: ``invalid_grant`` when the grant is gone or belongs to another client;
            ``invalid_client`` from :func:`_authenticated_client`.
    """
    grant = cleanup_and_get(session, store, key)
    if grant is None:
        raise _invalid_grant(gone)
    if not client_id or client_id != grant["client_id"]:
        raise _invalid_grant("client_id mismatch: re-authorise the connector")
    return grant, _authenticated_client(session, client_id, client_secret)


def _exchange_refresh_token(session: Session, refresh_token: str, client_id: str, client_secret: str) -> IssuedTokens:
    """Rotate *refresh_token*; a token presented twice revokes its whole family.

    Nothing may commit between :func:`consume_refresh_token` and the replacement's
    :func:`cleanup_and_store` inside :func:`_issue_tokens`: the two commit together, which
    is what lets a concurrent redeem of the same token revoke the replacement as well.
    """
    if not refresh_token:
        raise _invalid_grant("refresh_token is required")
    grant, client = _authenticated_grant(
        session, mcp_refresh_tokens, refresh_token, client_id, client_secret, gone=_REFRESH_TOKEN_GONE
    )
    if not _may_refresh(client):
        raise _TokenError(
            400, "unauthorized_client", "This client did not register the refresh_token grant: re-authorise it"
        )
    row = consume_refresh_token(session, refresh_token)
    if row is None:
        revoked = revoke_refresh_token_family(session, grant["family_id"])
        logger.warning(
            "MCP OAuth: refresh token reuse for client %s — revoked %d token(s) in its family", client_id, revoked
        )
        raise _invalid_grant(
            "Refresh token already used: every token from that sign-in is revoked, re-authorise the connector"
        )
    consumed = _ConsumedRefreshToken.of(row)
    return _issue_tokens(session, consumed.grant, consumed.family_id, consumed.expires_at, refreshable=True)


def _exchange_authorization_code(
    session: Session, code: str, redirect_uri: str, client_id: str, client_secret: str, code_verifier: str
) -> IssuedTokens:
    _, client = _authenticated_grant(session, mcp_auth_codes, code, client_id, client_secret, gone=_CODE_GONE)
    row = cleanup_and_pop(session, mcp_auth_codes, code)
    if row is None:
        raise _invalid_grant(_CODE_GONE)
    consumed = _ConsumedCode.of(row)
    if redirect_uri != consumed.redirect_uri:
        raise _invalid_grant("redirect_uri mismatch: re-authorise the connector")

    if consumed.code_challenge_method == "S256":
        if not code_verifier:
            raise _invalid_grant("code_verifier is required")
        if google_login.s256_challenge(code_verifier) != consumed.code_challenge:
            raise _invalid_grant("PKCE verification failed: re-authorise the connector")

    return _issue_tokens(
        session,
        consumed.grant,
        family_id=str(uuid.uuid4()),
        expires_at=datetime.now(UTC) + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
        refreshable=_may_refresh(client),
    )


@router.post("/oauth/token", include_in_schema=False)
async def oauth_token(
    grant_type: str = Form(...),
    code: str = Form(default=""),
    redirect_uri: str = Form(default=""),
    client_id: str = Form(default=""),
    client_secret: str = Form(default=""),
    code_verifier: str = Form(default=""),
    refresh_token: str = Form(default=""),
) -> JSONResponse:
    """Exchange an authorization code, or rotate a refresh token, for an ``aud="mcp"`` JWT.

    Refused up front — 501 naming ``SECRET_KEY`` — while there is no key to sign with, before any
    grant is consumed: a refresh token issued under a key that was since unset or shortened must
    mint nothing, and stays redeemable once the key is restored. Only the key is checked here:
    an emptied ``ALLOWED_EMAILS`` must still reach :func:`_issue_tokens`, which is where
    the refresh family is revoked.

    The one place an exchange becomes a response: below here a refusal is a :class:`_TokenError`,
    and a full refresh-token store a :class:`StoreFullError`, answered as every capacity refusal is.
    """
    if not settings.secret_key_configured:
        logger.error("MCP OAuth: token refused, SECRET_KEY is not configured")
        raise HTTPException(status_code=501, detail=auth.not_configured_detail(["SECRET_KEY"]))
    try:
        with auth.open_db_session() as session:
            if grant_type == "refresh_token":
                issued = _exchange_refresh_token(session, refresh_token, client_id, client_secret)
            elif grant_type == "authorization_code":
                issued = _exchange_authorization_code(
                    session, code, redirect_uri, client_id, client_secret, code_verifier
                )
            else:
                raise _TokenError(400, "unsupported_grant_type", "Only authorization_code and refresh_token")
    except _TokenError as refused:
        return JSONResponse(
            {"error": refused.error, "error_description": refused.description},
            status_code=refused.status,
            headers=_NO_STORE,
        )
    except StoreFullError as full:
        logger.warning("MCP OAuth: token issuance refused for client %s — %s", client_id, full)
        raise HTTPException(status_code=503, detail=auth.AT_CAPACITY) from full
    body = {
        "access_token": issued.access_token,
        "token_type": "bearer",
        "expires_in": issued.expires_in,
        "scope": issued.scope,
    }
    if issued.refresh_token:
        body["refresh_token"] = issued.refresh_token
    return JSONResponse(body, headers=_NO_STORE)
