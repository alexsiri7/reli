"""Shared in-memory state for MCP OAuth 2.1 flows.

Stores pending authorization requests and authorization codes
used by the /oauth/authorize → /oauth/token exchange.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Authorization requests expire after 10 minutes
_FLOW_TTL_SECONDS = 600
# Authorization codes expire after 5 minutes (RFC 6749 §4.1.2)
_CODE_TTL_SECONDS = 300


@dataclass
class MCPFlow:
    """Pending MCP OAuth authorization request."""

    redirect_uri: str
    original_state: str
    code_challenge: str
    code_challenge_method: str
    client_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AuthCode:
    """Issued authorization code awaiting token exchange."""

    user_id: str
    email: str
    code_challenge: str
    code_challenge_method: str
    redirect_uri: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# google_state -> MCPFlow (keyed by the state sent to Google)
_mcp_flows: dict[str, MCPFlow] = {}
# code -> AuthCode (single-use)
_auth_codes: dict[str, AuthCode] = {}


def store_mcp_flow(
    redirect_uri: str,
    original_state: str,
    code_challenge: str,
    code_challenge_method: str,
    client_id: str,
) -> str:
    """Store a pending MCP OAuth flow. Returns the google_state to use."""
    google_state = secrets.token_urlsafe(32)
    _mcp_flows[google_state] = MCPFlow(
        redirect_uri=redirect_uri,
        original_state=original_state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        client_id=client_id,
    )
    return google_state


def pop_mcp_flow(google_state: str) -> MCPFlow | None:
    """Retrieve and remove a pending MCP flow. Returns None if missing or expired."""
    flow = _mcp_flows.pop(google_state, None)
    if flow is None:
        return None
    elapsed = (datetime.now(timezone.utc) - flow.created_at).total_seconds()
    if elapsed > _FLOW_TTL_SECONDS:
        return None
    return flow


def store_auth_code(
    user_id: str,
    email: str,
    code_challenge: str,
    code_challenge_method: str,
    redirect_uri: str,
) -> str:
    """Generate and store an authorization code. Returns the code."""
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = AuthCode(
        user_id=user_id,
        email=email,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        redirect_uri=redirect_uri,
    )
    return code


def pop_auth_code(code: str) -> AuthCode | None:
    """Retrieve and remove an auth code (single-use). Returns None if missing or expired."""
    entry = _auth_codes.pop(code, None)
    if entry is None:
        return None
    elapsed = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
    if elapsed > _CODE_TTL_SECONDS:
        return None
    return entry
