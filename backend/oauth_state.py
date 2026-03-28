"""Shared in-memory state for MCP OAuth flows.

Two stores are needed across two modules (routers/auth.py and routers/mcp_oauth.py):
  _mcp_oauth_sessions — maps server-generated Google state -> MCP client OAuth params
  _mcp_auth_codes     — maps short-lived auth codes -> user info + PKCE challenge
"""

from __future__ import annotations

# server_state -> {
#   client_state, redirect_uri, code_challenge, code_challenge_method,
#   client_id, scope, google_code_verifier
# }
mcp_oauth_sessions: dict[str, dict] = {}

# auth_code -> {
#   user_id, email, code_challenge, code_challenge_method, redirect_uri, expires_at
# }
mcp_auth_codes: dict[str, dict] = {}

# client_id -> {
#   client_id, client_secret, redirect_uris, client_name, grant_types,
#   response_types, token_endpoint_auth_method
# }
mcp_registered_clients: dict[str, dict] = {}
