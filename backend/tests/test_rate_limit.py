"""The rate limiter (#1475): what it counts, what it refuses, and whose bucket a request spends."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI

from backend import auth, rate_limit
from backend.config import settings
from backend.google_login import s256_challenge
from backend.mcp_oauth import MAX_BODY_BYTES
from backend.oauth_state import cleanup_and_store, mcp_auth_codes, mcp_refresh_tokens

SECRET_KEY = "a-test-secret-key-that-is-forty-eight-chars-long"
BASE_URL = "https://reli.example.test"
CLIENT_REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _limits(monkeypatch, registration=10_000, auth_tier=10_000, api=10_000):
    monkeypatch.setattr(settings, "RATE_LIMIT_REGISTRATION_PER_MINUTE", registration)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", auth_tier)
    monkeypatch.setattr(settings, "RATE_LIMIT_API_PER_MINUTE", api)


def _register(client):
    return client.post("/oauth/register", json={"redirect_uris": [CLIENT_REDIRECT]})


def _credentials(registration):
    body = registration.json()
    return {"client_id": body["client_id"], "client_secret": body["client_secret"]}


def test_registration_above_its_limit_is_429_with_retry_after(client, session, monkeypatch, caplog):
    _limits(monkeypatch, registration=5)

    allowed = [_register(client) for _ in range(5)]
    with caplog.at_level(logging.WARNING, logger="backend.rate_limit"):
        refused = _register(client)
        _register(client)

    assert [r.status_code for r in allowed] == [201] * 5
    assert [r.headers["X-RateLimit-Limit"] for r in allowed] == ["5"] * 5
    assert [r.headers["X-RateLimit-Remaining"] for r in allowed] == ["4", "3", "2", "1", "0"]
    assert refused.status_code == 429
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert refused.headers["X-RateLimit-Remaining"] == "0"
    assert refused.json()["detail"].startswith("Too many requests")
    # Once per throttling, and naming neither the address nor a subject.
    warnings = [r.getMessage() for r in caplog.records if r.name == "backend.rate_limit"]
    assert warnings == ["rate limit reached: tier=registration key=addr"]


def test_the_tiers_are_separate_buckets(client, session, monkeypatch):
    _limits(monkeypatch, registration=1)
    _register(client)
    assert _register(client).status_code == 429

    assert client.get("/api/auth/me").status_code != 429


def test_the_sign_in_routes_take_the_auth_tier_not_the_api_tier(client, monkeypatch):
    _limits(monkeypatch, auth_tier=1, api=10_000)
    client.get("/api/auth/me")
    assert client.get("/api/auth/me").status_code == 429


@pytest.mark.parametrize("path", ["/healthz", "/", "/some/view"])
def test_health_and_the_bundle_are_never_counted(client, monkeypatch, path):
    """A throttled /healthz would roll the deploy back."""
    _limits(monkeypatch, registration=1, auth_tier=1, api=1)

    responses = [client.get(path) for _ in range(3)]

    assert all(r.status_code != 429 for r in responses)
    assert all("X-RateLimit-Limit" not in r.headers for r in responses)


def test_a_429_still_carries_the_security_headers(client, monkeypatch):
    """The limiter sits inside the headers layer and outside the web view's own 401."""
    _limits(monkeypatch, api=1)
    assert client.get("/api/things").status_code == 401

    refused = client.get("/api/things")

    assert refused.status_code == 429
    assert refused.headers["Cache-Control"] == "no-store"
    assert refused.headers["X-Frame-Options"] == "DENY"


def test_mcp_and_its_bare_path_share_the_api_tier(client, monkeypatch):
    _limits(monkeypatch, api=2)

    statuses = [client.get("/mcp", follow_redirects=False).status_code for _ in range(2)]

    assert 429 not in statuses
    assert client.get("/mcp/").status_code == 429


def test_a_signed_in_owner_spends_their_own_bucket_not_the_addresss(client, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(settings, "RELI_BASE_URL", BASE_URL)
    _limits(monkeypatch, api=2)
    client.get("/api/things")
    client.get("/api/things")
    assert client.get("/api/things").status_code == 429

    token = auth.create_jwt("1234567890", "owner@example.com", auth.WEB_AUDIENCE)
    cookie = {"Cookie": f"{auth.SESSION_COOKIE}={token}"}
    statuses = [client.get("/api/things", headers=cookie).status_code for _ in range(2)]

    assert statuses == [200, 200]


def test_a_token_reli_did_not_sign_spends_the_address_bucket(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    forged = {"type": "http", "headers": [(b"authorization", b"Bearer not-a-jwt")]}

    assert asyncio.run(rate_limit._user_subject(forged)) is None


def test_a_bearer_token_while_the_secret_key_is_unset_spends_the_address_bucket():
    """A deploy without SECRET_KEY admits no credential, so no bearer may claim a subject's bucket."""
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer anything")]}

    assert asyncio.run(rate_limit._user_subject(scope)) is None


def test_a_revoked_cookie_does_not_spend_the_owners_live_bucket(client, session, monkeypatch):
    """A copy of a cookie kept after logout would otherwise drain the bucket the next sign-in uses."""
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(settings, "RELI_BASE_URL", BASE_URL)
    stolen = {
        "Cookie": f"{auth.SESSION_COOKIE}={auth.create_jwt('1234567890', 'owner@example.com', auth.WEB_AUDIENCE)}"
    }
    assert client.post("/api/auth/logout", headers={**stolen, "Origin": BASE_URL}).status_code == 204
    _limits(monkeypatch, api=2)

    assert [client.get("/api/things", headers=stolen).status_code for _ in range(3)] == [401, 401, 429]

    fresh = auth.create_jwt("1234567890", "owner@example.com", auth.WEB_AUDIENCE)
    statuses = [
        client.get("/api/things", headers={"Cookie": f"{auth.SESSION_COOKIE}={fresh}"}).status_code for _ in range(2)
    ]
    assert statuses == [200, 200]


def test_a_token_for_an_account_off_the_allowlist_spends_the_address_bucket(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(settings, "RELI_BASE_URL", BASE_URL)
    token = auth.create_jwt("1234567890", "former@example.com", auth.MCP_AUDIENCE)
    scope = {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}

    assert asyncio.run(rate_limit._user_subject(scope)) is None


def test_a_token_whose_refresh_family_is_gone_spends_the_address_bucket(session, monkeypatch):
    """#1808: a stolen access token whose family was revoked must not drain the owner's bucket."""
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(settings, "RELI_BASE_URL", BASE_URL)
    token = auth.create_jwt("1234567890", "owner@example.com", auth.MCP_AUDIENCE, family_id="gone")
    scope = {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}

    assert asyncio.run(rate_limit._user_subject(scope)) is None


def _refresh(client, token, registered=None):
    form = {"grant_type": "refresh_token", "refresh_token": token}
    return client.post("/oauth/token", data={**form, **(registered or {})})


def _seed_refresh_token(session, token, client_id="connector", consumed_at=None):
    cleanup_and_store(
        session,
        mcp_refresh_tokens,
        token,
        {
            "client_id": client_id,
            "family_id": "family",
            "scope": "mcp",
            "subject": None if consumed_at else "1234567890",
            "email": None if consumed_at else "owner@example.com",
            "consumed_at": consumed_at,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        },
    )


def test_a_live_refresh_token_spends_its_clients_bucket_not_the_addresss(client, session, monkeypatch):
    """A flood holding no grant must not hold the connector's hourly refresh at 429 (#1802)."""
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    _limits(monkeypatch, auth_tier=2)
    _refresh(client, "bogus")
    _refresh(client, "bogus")
    assert _refresh(client, "bogus").status_code == 429
    registered = _credentials(_register(client))
    _seed_refresh_token(session, "live-token", registered["client_id"])

    # The route redeems the body the limiter read, so the replay reached it whole.
    refreshed = _refresh(client, "live-token", registered)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"]
    assert _refresh(client, "bogus").status_code == 429


def test_a_consumed_refresh_token_spends_the_address_bucket(client, session, monkeypatch):
    """A consumed row is kept to recognise a replay; a leaked old token must not reach the live bucket."""
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    _limits(monkeypatch, auth_tier=2)
    _refresh(client, "bogus")
    _refresh(client, "bogus")
    _seed_refresh_token(session, "old-token", consumed_at=datetime.now(UTC))

    assert _refresh(client, "old-token").status_code == 429


def test_a_live_code_spends_its_clients_bucket(client, session, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    _limits(monkeypatch, auth_tier=2)
    registered = _credentials(_register(client))
    verifier = "a-pkce-verifier-that-is-at-least-forty-three-characters-long"
    exchange = {
        "grant_type": "authorization_code",
        "code": "bogus",
        **registered,
        "redirect_uri": CLIENT_REDIRECT,
        "code_verifier": verifier,
    }
    client.post("/oauth/token", data=exchange)
    client.post("/oauth/token", data=exchange)
    assert client.post("/oauth/token", data=exchange).status_code == 429
    cleanup_and_store(
        session,
        mcp_auth_codes,
        "live-code",
        {
            "subject": "1234567890",
            "email": "owner@example.com",
            "code_challenge": s256_challenge(verifier),
            "code_challenge_method": "S256",
            "redirect_uri": CLIENT_REDIRECT,
            "client_id": registered["client_id"],
            "scope": "mcp",
            "expires_at": datetime.now(UTC) + timedelta(seconds=60),
        },
    )

    exchanged = client.post("/oauth/token", data={**exchange, "code": "live-code"})
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["access_token"]


def test_a_form_streamed_past_the_cap_is_not_read_further_and_is_replayed_whole(monkeypatch):
    """The limiter stops buffering at ``MAX_BODY_BYTES``, so a chunked flood cannot grow its memory."""
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    chunk = b"x" * (MAX_BODY_BYTES // 4 + 1)
    stream = [{"type": "http.request", "body": chunk, "more_body": True} for _ in range(8)]
    sent = iter(stream)

    async def receive():
        return next(sent)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/oauth/token",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }

    async def exchange():
        client_id, replay = await rate_limit._grant_client(scope, receive)
        return client_id, [await replay() for _ in stream]

    client_id, replayed = asyncio.run(exchange())

    assert client_id is None
    assert replayed == stream


def test_a_signed_in_owner_spends_their_own_auth_bucket(client, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "ALLOWED_EMAILS", "owner@example.com")
    monkeypatch.setattr(settings, "RELI_BASE_URL", BASE_URL)
    _limits(monkeypatch, auth_tier=2)
    client.get("/api/auth/me")
    client.get("/api/auth/me")
    assert client.get("/api/auth/me").status_code == 429

    token = auth.create_jwt("1234567890", "owner@example.com", auth.WEB_AUDIENCE)
    cookie = {"Cookie": f"{auth.SESSION_COOKIE}={token}"}

    assert client.get("/api/auth/me", headers=cookie).status_code == 200
    assert client.post("/api/auth/logout", headers={**cookie, "Origin": BASE_URL}).status_code == 204


@pytest.mark.parametrize(
    ("production", "cidrs", "warns"),
    [("1", "", True), ("1", "10.0.0.0/8", False), ("", "", False)],
)
def test_a_deploy_without_trusted_proxies_warns_at_startup(monkeypatch, caplog, production, cidrs, warns):
    monkeypatch.setattr(settings, "PRODUCTION", production)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT_NAME", "")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", cidrs)

    with caplog.at_level(logging.WARNING, logger="backend.rate_limit"):
        rate_limit.add_rate_limit(FastAPI())

    assert any("TRUSTED_PROXY_CIDRS is empty on a deploy" in r.getMessage() for r in caplog.records) is warns


def _scope(peer, *forwarded):
    return {
        "type": "http",
        "client": (peer, 1234),
        "headers": [(b"x-forwarded-for", value.encode()) for value in forwarded],
    }


def test_forwarded_for_is_ignored_from_an_untrusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "")

    assert rate_limit.client_address(_scope("10.0.0.2", "203.0.113.9")) == "10.0.0.2"


def test_a_trusted_proxy_yields_the_rightmost_untrusted_hop(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")

    assert rate_limit.client_address(_scope("10.0.0.2", "203.0.113.9, 10.1.1.1")) == "203.0.113.9"
    # A client that prepends its own entry cannot choose its key.
    assert rate_limit.client_address(_scope("10.0.0.2", "198.51.100.1", "203.0.113.9")) == "203.0.113.9"
    assert rate_limit.client_address(_scope("10.0.0.2")) == "10.0.0.2"


def test_the_bucket_store_stays_bounded(monkeypatch):
    monkeypatch.setattr(rate_limit, "MAX_BUCKETS", 3)
    tier = rate_limit.Tier("api", 60)

    for key in ("a", "b", "c", "d"):
        rate_limit._take(tier, f"addr:{key}", now=0.0)

    assert list(rate_limit._BUCKETS) == [("api", "addr:b"), ("api", "addr:c"), ("api", "addr:d")]


def test_an_empty_bucket_refills_at_its_rate():
    tier = rate_limit.Tier("auth", 60)
    for _ in range(60):
        rate_limit._take(tier, "addr:x", now=0.0)

    assert rate_limit._take(tier, "addr:x", now=0.0) == (False, 0, 1)
    assert rate_limit._take(tier, "addr:x", now=1.0)[0]
