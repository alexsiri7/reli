# OAuth reference (not built, not shipped)

The Google OAuth, Calendar and Gmail code that ran against the pre-v4 backend, kept here because
#1408 asks for it to be retained as reference rather than deleted.

| File | Was |
|---|---|
| `router_auth.py` | `backend/routers/auth.py` |
| `router_calendar.py` | `backend/routers/calendar.py` |
| `router_gmail.py` | `backend/routers/gmail.py` |
| `auth.py` | `backend/auth.py` |
| `google_calendar.py` | `backend/google_calendar.py` |
| `oauth_state.py` | `backend/oauth_state.py` |
| `token_encryption.py` | `backend/token_encryption.py` |

Nothing here is imported, linted, typechecked or copied into the Docker image — the gates and the
`COPY backend/` in the `Dockerfile` only ever look under `backend/`.

It targets the schema the #1408 baseline migration drops (`users`, `google_tokens`,
`gmail_oauth_states`, `revoked_tokens`, the multi-user `user_id` columns) and the settings
`backend/config.py` no longer defines. #1412 rewrites the Calendar and Gmail readers against the new
data layer. #1409 has since answered the auth half: `/mcp` takes a static bearer token
(`MCP_API_TOKEN`), so none of this is needed for the MCP surface — a full authorization server
would be its own issue. Read it for the OAuth flow and the token handling, do not reuse it
wholesale.
