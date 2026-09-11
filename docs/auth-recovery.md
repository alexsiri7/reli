# Recovering the pre-v4 Google OAuth (requirement 019, #1448)

What the web view and `/mcp` did for authentication immediately before the v4 rebuild, read from
the last `main` commit before #1408's data-layer PR landed, so that #1449 (web view) and #1450
(MCP) are a port and not a reimplementation. This document changes no behaviour.

**Source commit: `553e3f0`** ("Land vision v4 and rewrite CLAUDE.md for the rebuild (#1415)",
2026-09-10). The data-layer rebuild merged as `790be49` directly on top of it, and `ad935b4`
("Delete the pre-v4 backend, the frontend and the legacy migrations") removed the files below.
Every path in this document is read with `git show 553e3f0:<path>`; blob ids are given so a row
can be fetched without the commit.

## 1. The answer to the issue's question

Both sides were **Google OAuth proper**, not a password and not a shared session:

- The **web view** ran an authorization-code + PKCE flow against Google with the `openid`,
  `email` and `profile` scopes, checked the resulting id-token's email against `ALLOWED_EMAILS`, and
  held the session as an HS256 JWT in an `httponly` cookie named `reli_session` for seven days.
- The **MCP endpoint** was *more* complex than the web view, not simpler: `backend/routers/mcp_oauth.py`
  was a complete OAuth 2.1 authorization server for MCP clients — RFC 9728 protected-resource
  metadata, RFC 8414 authorization-server metadata, RFC 7591 dynamic client registration,
  `/oauth/authorize` and `/oauth/token` with mandatory S256 PKCE and refresh tokens — that delegated
  the *identity* step to the same Google login the web view used and then minted its own JWTs with
  `aud="mcp"`. The `/mcp` middleware accepted those JWTs.
- At the same time, the `/mcp` middleware **also** accepted a static `MCP_API_TOKEN` bearer as a
  legacy path, and `backend/auth.py` accepted a second static token, `RELI_API_TOKEN`, on the `/api`
  routes. Three credentials were live at once; the OAuth ones were the ones a claude.ai or Claude
  Code connector used.

The issue's "Note" case — a bearer token or a session shared with the web login — did not apply.
The current `reference/oauth/README.md` says "#1409 answered the auth half: `/mcp` takes a static
bearer token, so none of this is needed for the MCP surface — a full authorization server would be
its own issue." That is an accurate description of what #1409 *built*, but read as history it is
wrong: a full authorization server already existed at `553e3f0` and was deleted with the rest. Its
"not built, not shipped" framing of the retained code still holds.

## 2. Web view auth

### 2.1 Flow

All in `backend/routers/auth.py` (blob `2a57eaf4f72c`), mounted with `prefix="/api"` and listed
as public in `backend/main.py` (`app.include_router(auth.router, prefix="/api")`, before the
`Depends(require_user)` routers).

1. **`GET /api/auth/google`** — refuses with 501 "Authentication service unavailable" if
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` or `SECRET_KEY` is empty. Otherwise builds a
   `google_auth_oauthlib.flow.Flow` from `_client_config()` — client id, client secret, Google's
   `auth_uri`/`token_uri`, and `redirect_uris=[GOOGLE_AUTH_REDIRECT_URI]` — with
   `AUTH_SCOPES = ["openid", "email", "profile"]`, calls `authorization_url(access_type="offline",
   include_granted_scopes="true", prompt="consent")`, stores the PKCE `code_verifier` under the
   Google `state` in the in-process dict `_pending_flows` (TTL 600 s, capped at 10 000 entries,
   503 when full), and returns `{"auth_url": ...}` as JSON. The browser is *not* redirected by the
   server; the frontend navigates to `auth_url`.
2. **`GET /api/auth/google/callback?code=&state=`** — pops the verifier for `state` from
   `_pending_flows`; if absent, looks in the DB-backed `mcp_oauth_sessions` store (the MCP flow,
   §3) under `google_code_verifier`; if neither, 400 "Invalid or expired OAuth state." Exchanges the
   code (`flow.fetch_token`, 502 on failure), then verifies the id-token with
   `google.oauth2.id_token.verify_oauth2_token(..., GOOGLE_CLIENT_ID)` and reads `sub`, `email`,
   `name`, `picture`.
3. **Allowlist.** `settings.allowed_emails_set` is `ALLOWED_EMAILS` split on commas, stripped and
   lower-cased; empty meant *allow all*. A non-member is redirected to `/?error=invite_only` and
   the rejection is logged without the email (`test_oauth_rejection_log_contains_no_email`). That
   redirect, not a 401, is what the frontend turned into a message.
4. **User upsert.** `_upsert_user` keyed on `google_id` in the `users` table, creating a
   `u-<12 hex>` id and a `person` Thing as the user's anchor on first login, refreshing
   `email`/`name`/`picture` on later logins, with an `IntegrityError` retry for concurrent first
   logins.
5. **Session.** If `state` belonged to an MCP session the callback branches into §3.3. Otherwise
   `_create_jwt(user_id, email, aud="web")` and `RedirectResponse("/")` with the cookie.

### 2.2 The session cookie

| | |
|---|---|
| Name | `reli_session` (`COOKIE_NAME`, defined in both `routers/auth.py` and `backend/auth.py`) |
| Value | HS256 JWT signed with `SECRET_KEY`; claims `sub` (user id), `email`, `aud` (`"web"`), `iat`, `exp`, `jti` |
| Lifetime | `JWT_EXPIRY_SECONDS = 60 * 60 * 24 * 7` (7 days), also the cookie `max_age` |
| Flags | `httponly=True`, `samesite="lax"`, `path="/"`, `secure=settings.cookie_secure_bool` (`COOKIE_SECURE`, default `"true"`, `"false"` only for local HTTP) |

`backend/auth.py` (blob `b4fc57da02ee`) holds `require_user`, the dependency every `/api` router
except `auth` carried. Order of checks: if neither `SECRET_KEY` nor `RELI_API_TOKEN` is set, auth
is off and it returns `""` (production refused to boot in that state — `Settings` raised unless
`AUTH_DISABLED=true`). A `Bearer` header is compared with `RELI_API_TOKEN` and resolves to
`RELI_API_TOKEN_USER_ID` or the oldest `users` row. Otherwise the cookie is decoded with
`audience="web"` — 401 "Session expired" / "Invalid session" / "Not authenticated" — and the `jti`
is checked against the `revoked_tokens` table, failing *open* if the database is unreachable.

- **`GET /api/auth/me`** — decodes the cookie, loads the `users` row, returns
  `{id, email, name, picture}`; 401 otherwise. This is the frontend's "am I logged in" probe.
- **`POST /api/auth/logout`** — inserts the cookie's `jti` into `revoked_tokens` with the JWT's
  `exp` (so the row can be pruned once the token would have died anyway; `require_user` prunes
  opportunistically on 1 % of requests) and deletes the cookie.

Audience separation was tested: a `aud="mcp"` token is rejected as a web cookie
(`test_mcp_token_rejected_as_web_cookie`) and vice versa.

### 2.3 Frontend

The frontend at `553e3f0` was the full pre-v4 SPA (Zustand store, chat, PWA), not the three-view
read-only bundle of today. The auth pieces:

- `frontend/src/api.ts` (blob `8b144a939d18`) — `apiFetch` wraps `fetch` with
  `credentials: 'same-origin'` and, on a **401** from any path outside `/api/auth/`, re-runs
  `useStore.getState().fetchCurrentUser()`. There was no redirect and no stored token: the cookie
  was the whole session and the browser sent it.
- `frontend/src/store.ts` (blob `8c459a4ea098`) — `fetchCurrentUser` calls `GET /api/auth/me`; on
  200 it sets `currentUser` and `authChecked: true`, on anything else `currentUser: null,
  authChecked: true`. `logout` posts `/api/auth/logout`, clears `currentUser` and sets
  `window.location.href = '/'`.
- `frontend/src/App.tsx` (blob `5a429e8f795a`) — calls `fetchCurrentUser()` on mount, shows a
  spinner until `authChecked`, renders **`LandingPage`** while `currentUser` is null, and loads the
  app's data only once a user exists. So a 401 mid-session collapsed the app back to the landing
  page via the store, without a navigation.
- `frontend/src/components/LandingPage.tsx` (blob `7ff89749be79`) — the marketing page with a
  "Sign in with Google" button that `fetch`es `/api/auth/google`, shows `detail` from a non-2xx
  response (or "Could not connect to server"), and otherwise sets `window.location.href` to
  `auth_url`. It reads `?error=invite_only` from the query string and shows "This app is
  invite-only. Your Google account is not on the access list."
- `frontend/src/components/LoginPage.tsx` (blob `093a660d0f22`) — the same button and the same
  `invite_only` message on a plain card. It had a Vitest suite
  (`frontend/src/__tests__/LoginPage.test.tsx`) but **no import site outside that test** at
  `553e3f0`; `LandingPage` is what shipped. Either is a fair template for the sign-in screen.

## 3. MCP auth

### 3.1 The middleware on `/mcp`

`_TokenAuthMiddleware` in `backend/mcp_server.py` (blob `e571fb0ae2a9`), wrapping
`mcp.streamable_http_app()` and mounted at `/mcp` from `backend/main.py`. Per request:

1. If neither `MCP_API_TOKEN` nor `SECRET_KEY` is set, everything passes (dev mode).
2. `Authorization: Bearer <x>`: if `MCP_API_TOKEN` is set and matches (`secrets.compare_digest`),
   authorised as `_resolve_api_token_user()`. Otherwise, if `SECRET_KEY` is set, `jwt.decode(x,
   SECRET_KEY, algorithms=["HS256"], audience="mcp")` and the `sub` claim becomes the request's
   user id (a `contextvars.ContextVar` the tools read).
3. Anything else: 401 with
   `WWW-Authenticate: Bearer realm="reli", resource_metadata="<base>/.well-known/oauth-protected-resource"`.
   That header is the RFC 9728 hint an MCP client follows to discover the authorization server.

The server also enabled the SDK's DNS-rebinding protection with an `allowed_hosts` list of
localhost plus the host of `RELI_BASE_URL`, falling back to the host of `GOOGLE_AUTH_REDIRECT_URI`.

### 3.2 The authorization server

`backend/routers/mcp_oauth.py` (blob `cdba5451949c`), included in `main.py` with **no prefix**
and no auth dependency. It imports `AUTH_SCOPES`, `GOOGLE_REDIRECT_URI` (the login one),
`JWT_EXPIRY_SECONDS`, `_client_config` and `_create_jwt` from `routers/auth.py` — the two routers
are one implementation. `_base_url()` is `RELI_BASE_URL` or the scheme+host of
`GOOGLE_AUTH_REDIRECT_URI`.

| Endpoint | Spec | Did |
|---|---|---|
| `GET /.well-known/oauth-protected-resource` | RFC 9728 | `{"resource": "<base>/mcp/", "authorization_servers": ["<base>"], "scopes_supported": ["mcp"]}` |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 | `issuer=<base>`, the three endpoints below, `response_types_supported=["code"]`, `grant_types_supported=["authorization_code","refresh_token"]`, `code_challenge_methods_supported=["S256"]`, `scopes_supported=["mcp"]` |
| `POST /oauth/register` | RFC 7591 | Accepts a JSON body; every `redirect_uris` entry must be `https://` (or `http://` on `localhost`/`127.0.0.1`), else 400. Mints a `uuid4` `client_id` and a 32-byte `client_secret`, stores the client for 30 days (cap 100 live clients, 503 when full), returns 201 with the registration echoed and `client_secret_expires_at`. No approval step — single tenant. |
| `GET /oauth/authorize` | — | Requires a registered `client_id`, a `redirect_uri` on that registration, `response_type=code`, `code_challenge` with `code_challenge_method=S256`; 501 if the Google client or `SECRET_KEY` is unset. Generates its own `server_state`, starts the same Google `Flow` as the web login (same scopes, same `GOOGLE_AUTH_REDIRECT_URI`), saves `{client_state, redirect_uri, code_challenge, client_id, scope, google_code_verifier}` under `server_state` in `mcp_oauth_sessions` (TTL 10 min), and 302s the user to Google. |
| `POST /oauth/token` | RFC 6749 | Form-encoded. `grant_type=authorization_code`: pops the code from `mcp_auth_codes`, checks expiry, `redirect_uri` equality, `client_id` equality (code bound to the client that asked), the client secret (skipped when the registration's `token_endpoint_auth_method` is `none`), and the S256 verifier; then issues. `grant_type=refresh_token`: pops the token from `mcp_refresh_tokens`, checks expiry and `client_id`, validates the secret, issues again. |

### 3.3 The Google callback's MCP branch

The Google redirect for an MCP login lands on the **web** callback, `GET /api/auth/google/callback`.
Because the `state` is a `server_state` from `/oauth/authorize`, the verifier is found in
`mcp_oauth_sessions`, the allowlist and user upsert run exactly as for the web, and then — instead
of a cookie — the callback mints a 32-byte auth code, stores `{user_id, email, code_challenge,
code_challenge_method, redirect_uri, client_id}` in `mcp_auth_codes` with a **60 s** TTL, and 302s
to the client's `redirect_uri` with `?code=<auth_code>&state=<client_state>`.

`_issue_token_response` returns `{"access_token": <JWT aud="mcp", 7 days>, "token_type":
"bearer", "expires_in": 604800, "refresh_token": <32 bytes, 30 days>, "scope": "mcp"}`.

### 3.4 What the connector was configured against

No connector configuration is recorded in the repository; what follows is what the endpoints
and the commit that added registration (`31d6ad1`) imply, not a captured claude.ai setting.
Nothing was pre-registered. A claude.ai connector or Claude Code pointed at
`https://<host>/mcp/` (bare `/mcp` was 307-redirected to `/mcp/` using `_base_url()` so the scheme
survived a TLS-terminating proxy), received the 401 with `resource_metadata`, fetched the two
`.well-known` documents, **registered itself** with `POST /oauth/register` (commit `31d6ad1`:
"Claude Code requires dynamic client registration to connect to MCP servers with OAuth"), and ran
the authorize/token exchange. The only human-side configuration was the Google Cloud OAuth client
and its redirect URI (§4.2); no client id was ever pasted into claude.ai.

CORS for that exchange was `_MCPCorsMiddleware` in `main.py`: on `/oauth/`, `/.well-known/` and
`/mcp` paths it reflected the `Origin` only when listed in `MCP_CORS_ORIGINS`, allowing
`content-type, authorization`; other origins got no CORS headers.

### 3.5 State storage

`backend/oauth_state.py` (blob `4caf51ce283d`) gives every store the same three calls —
`cleanup_and_store`, `cleanup_and_get`, `cleanup_and_pop`, each purging expired rows first and
raising `StoreFullError` at the cap. Since #1102 the four MCP stores are tables (so a container
restart does not orphan a flow in progress); the web flow's `_pending_flows` stayed an in-process
dict. Both ran under a single-worker `uvicorn` in the Dockerfile, as the current image still does;
that is why the dict was adequate, and a port that keeps it inherits the same constraint.

| Table | Key | Written by | TTL |
|---|---|---|---|
| `mcp_registered_clients` | `client_id` | `/oauth/register` | 30 days, cap 100 |
| `mcp_oauth_sessions` | `server_state` | `/oauth/authorize` | 10 min |
| `mcp_auth_codes` | `auth_code` | Google callback (MCP branch) | 60 s |
| `mcp_refresh_tokens` | `refresh_token` | `/oauth/token` | 30 days |
| `revoked_tokens` | `jti` | `/api/auth/logout` | until the JWT's own `exp` |
| `users` | `id` | Google callback | — |

The models are in `backend/db_models.py` at `553e3f0` (blob `486bc0ea1bc0`): `UserRecord`,
`McpOAuthSessionRecord`, `McpAuthCodeRecord`, `McpRegisteredClientRecord`,
`McpRefreshTokenRecord`, `RevokedTokenRecord`. `GmailOAuthStateRecord` and `GoogleTokenRecord`
belong to the old per-user Calendar/Gmail grant, which #1412 replaced and which is not part of
this recovery.

## 4. Configuration

### 4.1 Environment variables

Every setting the two flows read from `backend/config.py` at `553e3f0` (blob `3c6742f15bfb`),
against the current `backend/config.py` and the names the owner reports as still set on the
Railway staging and production services (issue comment on #1448 — an owner's report, not something
an agent can read).

| Variable | Old default | Used for | In v4 `config.py` | Still set on Railway |
|---|---|---|---|---|
| `GOOGLE_CLIENT_ID` | `""` | Both flows' OAuth client | yes — but for the Calendar/Gmail refresh-token grant | yes |
| `GOOGLE_CLIENT_SECRET` | `""` | same | yes — same caveat | yes |
| `GOOGLE_AUTH_REDIRECT_URI` | `http://localhost:8000/api/auth/google/callback` | Login redirect URI, both flows; base-URL fallback | no | yes |
| `SECRET_KEY` | `""` | HS256 signing key for every JWT; both flows are 501 without it | no | yes |
| `ALLOWED_EMAILS` | `""` (= allow all) | The allowlist | no | yes |
| `COOKIE_SECURE` | `"true"` | `Secure` flag on `reli_session` | no | not in the list |
| `RELI_BASE_URL` | `""` | Issuer / metadata URLs / DNS-rebinding host | no | not in the list |
| `MCP_CORS_ORIGINS` | `""` | Origins reflected on `/oauth/*`, `/.well-known/*`, `/mcp` | no | not in the list |
| `CORS_ORIGINS` | `""` | The restrictive CORS on everything else | no | yes |
| `MCP_API_TOKEN` | `""` | Static bearer on `/mcp`, legacy path beside the JWT | yes — the *only* `/mcp` credential now | not in the list |
| `RELI_API_TOKEN` / `RELI_API_TOKEN_USER_ID` | `""` | Static bearer on `/api` for programmatic clients | no | not in the list (`API_TOKEN` is set on staging, a name neither tree reads) |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/calendar/callback` | Calendar grant callback, and base for the Gmail one — **not** login | no | yes |
| `TOKEN_ENCRYPTION_KEY` | `""` | Encrypting stored Calendar/Gmail refresh tokens (`token_encryption.py`) — not login | no | yes |
| `WEB_UI_PASSWORD` | — | did not exist | yes — the only web credential now | not in the list |
| `GOOGLE_REFRESH_TOKEN` | — | did not exist | yes — the Calendar/Gmail grant | not in the list |

Two readings of that table matter for the restore:

- **The Google client is shared.** `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` survived the rebuild
  and are read today by `backend/google_client.py` for a *different* grant: `gmail.readonly` +
  `calendar.readonly`, a refresh token minted once by `scripts/google_oauth_grant.py` against a
  loopback redirect. Restoring login puts a second grant type (`openid email profile`, a browser
  redirect to `GOOGLE_AUTH_REDIRECT_URI`) on the same OAuth client. That is how it was at `553e3f0`
  too — the Calendar and Gmail routers used the same `_client_config()` shape with their own
  redirect URIs — so it is known to work, but the two must not be confused when reading logs or
  the console.
- **The current credentials are not in the owner's list.** `MCP_API_TOKEN` and `WEB_UI_PASSWORD`
  are absent from the reported names while `SECRET_KEY`, `ALLOWED_EMAILS` and
  `GOOGLE_AUTH_REDIRECT_URI` are present. Read literally, that is the deploy that requirement 019
  describes: the old secrets are waiting and the new ones were never provisioned.

The old `Settings` also validated: in production (`RAILWAY_ENVIRONMENT_NAME` or `PRODUCTION` set)
`SECRET_KEY` was required at boot, and with neither `SECRET_KEY` nor `RELI_API_TOKEN` the boot
refused unless `AUTH_DISABLED=true`. The v4 rule is the opposite — an empty secret never stops the
boot, `/healthz` stays green and the surface answers 401 — and that rule should win in the port.

### 4.2 Redirect URIs registered with Google

Every URI the pre-v4 code sent as `redirect_uri`, for checking against the Google Cloud console's
authorised redirect list. Only the first is needed for login.

| URI | Set by | Flow |
|---|---|---|
| `<GOOGLE_AUTH_REDIRECT_URI>` — by default `<base>/api/auth/google/callback` | `GOOGLE_AUTH_REDIRECT_URI` | Web login **and** MCP login (both flows share the one callback) |
| `<GOOGLE_REDIRECT_URI>` — by default `<base>/api/calendar/callback` | `GOOGLE_REDIRECT_URI` | Old per-user Calendar grant (superseded by #1412) |
| `<RELI_BASE_URL>/api/gmail/callback`, falling back to `GOOGLE_REDIRECT_URI`'s scheme+host | derived in `routers/gmail.py` | Old per-user Gmail grant (superseded by #1412) |
| `http://127.0.0.1:<ephemeral port>/` | `scripts/google_oauth_grant.py` | The current Calendar/Gmail refresh-token grant (loopback, no console entry needed) |

Redirect URIs an MCP client registers with `POST /oauth/register` are Reli's own concern, not
Google's: Google only ever sees `GOOGLE_AUTH_REDIRECT_URI`.

## 5. File-by-file inventory at `553e3f0`

| Path | Blob | What it is |
|---|---|---|
| `backend/routers/auth.py` | `2a57eaf4f72c` | Web login: `/api/auth/google`, `/api/auth/google/callback` (with the MCP branch), `/api/auth/me`, `/api/auth/logout`; `_create_jwt`, `_client_config`, `AUTH_SCOPES` |
| `backend/routers/mcp_oauth.py` | `cdba5451949c` | The OAuth 2.1 authorization server: two `.well-known` documents, `/oauth/register`, `/oauth/authorize`, `/oauth/token` |
| `backend/auth.py` | `b4fc57da02ee` | `require_user` dependency for `/api`: cookie JWT, `RELI_API_TOKEN` bearer, revocation check |
| `backend/oauth_state.py` | `4caf51ce283d` | The bounded, TTL-purged stores; DB-backed for MCP, dict for the web verifier |
| `backend/mcp_server.py` (`_TokenAuthMiddleware`, `_resource_metadata_url`, `_allowed_hosts`) | `e571fb0ae2a9` | The `/mcp` bearer check accepting the static token or an `aud="mcp"` JWT |
| `backend/main.py` (router wiring, `_MCPCorsMiddleware`, `SentryUserContextMiddleware`, `mcp_redirect`) | `16afa1b8266c` | Public `auth` and `mcp_oauth` routers, `Depends(require_user)` on the rest, MCP CORS, `/mcp` → `/mcp/` |
| `backend/config.py` | `3c6742f15bfb` | The settings in §4.1 and the boot-time secret validation |
| `backend/db_models.py` (`UserRecord`, `RevokedTokenRecord`, the four `Mcp*Record`) | `486bc0ea1bc0` | The tables in §3.5 |
| `backend/alembic/versions/j4k5l6m7n8o9_add_oauth_state_tables.py` | `0fb6c19ee064` | Created the four `mcp_*` tables (#1102) |
| `backend/alembic/versions/q1r2s3t4u5v6_add_revoked_tokens_table.py` | `dcac4edf30bb` | Created `revoked_tokens` (#1221) |
| `backend/tests/test_auth.py` | `e3657cfa51e5` | Cookie/JWT acceptance and rejection, audience separation, `COOKIE_SECURE`, allowlist rejection logging, callback never logging the code, logout revocation, fail-open on DB outage, pruning |
| `backend/tests/test_mcp_oauth.py` | `97aeb2782b76` | Metadata uses `RELI_BASE_URL` / https, CORS preflights on `/oauth/*` and `.well-known`, `/mcp` redirect scheme, `register` redirect-URI scheme rules, token response `aud="mcp"`, confidential vs public client secret checks |
| `backend/tests/test_mcp_server.py` (auth classes) | `391c3c004758` | Static token accepted/rejected, `WWW-Authenticate` carries `resource_metadata`, wrong-audience JWT rejected |
| `backend/tests/test_oauth_state.py`, `test_oauth_state_cleanup.py` | `11ee553a3360`, `04dbf07512cf` | Store semantics: TTL purge, caps, JSON list fields |
| `frontend/src/api.ts` | `8b144a939d18` | `apiFetch`: cookies on every call, 401 → re-probe `/api/auth/me` |
| `frontend/src/store.ts` (`fetchCurrentUser`, `logout`) | `8c459a4ea098` | The session probe and logout |
| `frontend/src/App.tsx` | `5a429e8f795a` | Probe on mount; `LandingPage` until a user exists |
| `frontend/src/components/LandingPage.tsx` | `7ff89749be79` | The sign-in button that shipped, plus the `invite_only` message |
| `frontend/src/components/LoginPage.tsx`, `frontend/src/__tests__/LoginPage.test.tsx` | `093a660d0f22`, `f0a82d58b0d5` | The plain sign-in card (unused outside its test) |
| `docs/mcp-design.md` §3 and §10 | `d1c3f9bde122` | The contemporary description of the middleware and the OAuth 2.1 endpoints |

Origin commits, for `git log -p` on a single concern: `0e6f585` (Google OAuth + JWT sessions
replacing an API key), `1ccc4de` (#298, the MCP OAuth flow replacing the static token), `31d6ad1`
(#299, dynamic client registration), `be29124` (#382, `expires_in` and refresh tokens), `0cda6f8`
(#1102, MCP state to tables), `8b23a03` (#1221, logout revocation).

### 5.1 Relationship to `reference/oauth/`

`reference/oauth/` is the copy #1408 kept. Its `auth.py`, `oauth_state.py`, `token_encryption.py`
and `router_auth.py` are **byte-identical** to the `553e3f0` files above (`diff` is empty), so
the web half can be read from the working tree. **`backend/routers/mcp_oauth.py` was not
retained** — the MCP authorization server exists only in git history, at
`git show 553e3f0:backend/routers/mcp_oauth.py`. The same goes for the `_TokenAuthMiddleware` in
the old `mcp_server.py`, the `main.py` wiring, the models, the migrations and every test. #1450
should start from the commit, not from `reference/oauth/`.

## 6. Assessment: what ports, what must change

### Ports as-is

- The OAuth mechanics of both routers: `Flow` construction, PKCE, id-token verification, the
  allowlist check, JWT minting with separate audiences, the `WWW-Authenticate` +
  `resource_metadata` handshake, the three RFC endpoints, S256 verification, code-to-client
  binding, refresh rotation. None of it touched the data model beyond the six tables in §3.5.
- The `oauth_state.py` store API, which is independent of what the tables are called.
- The frontend contract: `GET /api/auth/google` → `{auth_url}`, `GET /api/auth/me` → user or 401,
  `POST /api/auth/logout`, and the `?error=invite_only` redirect. Small enough to re-implement in
  the three-view bundle.
- The tests in §5 as specifications, with the fixtures rewritten for the v4 conftest.

### Must change

1. **Schema.** `users`, `revoked_tokens`, `mcp_oauth_sessions`, `mcp_auth_codes`,
   `mcp_registered_clients` and `mcp_refresh_tokens` are in the baseline migration's drop list
   (`backend/alembic/versions/v4_baseline_things_relationships_journal.py`, the `LEGACY_TABLES`
   tuple). The additive-only rule means new `CREATE TABLE IF NOT EXISTS` migrations on top of the
   v4 baseline, not a revert of `790be49`. The `users` table itself is the part to reconsider
   before porting: v4 has one `#User` Thing at `USER_ANCHOR_ID` and no `user_id` on anything, so
   `_upsert_user`'s "create a `person` Thing per login" and `_resolve_api_token_user`'s "oldest
   user" have nothing to attach to. The allowlist already is the account; a port needs the
   allowlisted email (and Google `sub`) in the JWT, not a `users` row. What the MCP tables hold —
   short-lived flow state — has no equivalent in the Things/relationships/journal model and should
   stay as its own tables. None of these writes are Thing mutations, so none of them journals;
   that matches the rule as written (every *Thing* mutation journals).
2. **Frontend.** The v4 bundle (`frontend/src/`: `api.ts` with `getJson`/`rejectPreference`,
   `useJson.ts`, three views, no store) has no auth concept: the browser's Basic prompt is the
   login screen. `apiFetch`, `fetchCurrentUser`, `authChecked` and `LandingPage` cannot be copied
   over; the sign-in view and the 401 → sign-in behaviour are re-integrated in the v4 idiom. The
   frontend stays read-only apart from rejecting a preference; logout and login are not graph
   writes, so this does not widen that exception. The screenshot suite stubs every `/api` route
   from `frontend/e2e/fixtures.ts`, so `/api/auth/me` gets a stub and the sign-in view gets a
   snapshot.
3. **Backend wiring.** v4 has no `backend/routers/`; `backend/api.py` owns `/api` and the
   `_BasicAuthMiddleware`, `backend/mcp_server.py` owns `_BearerTokenMiddleware`. The port
   replaces those two middlewares (the Basic one only once Google sign-in is verified — requirement
   019 is explicit that `WEB_UI_PASSWORD` goes after, not before) and the `.well-known`/`/oauth`
   routes must be added **before** `api.mount_frontend`'s catch-all. The current `/mcp` runs with
   DNS-rebinding protection *disabled*, justified in `docs/mcp-design.md` §2 by the mandatory
   `Authorization` header; a JWT bearer keeps that invariant, so the old `allowed_hosts` list is
   not needed back, but the justification must stay true.
4. **Settings.** `SECRET_KEY`, `ALLOWED_EMAILS`, `GOOGLE_AUTH_REDIRECT_URI`, `COOKIE_SECURE`,
   `RELI_BASE_URL` and `MCP_CORS_ORIGINS` return to `backend/config.py`. `RELI_API_TOKEN` and
   `RELI_API_TOKEN_USER_ID` do not: nothing in v4 is a programmatic `/api` client. Whether the
   static `MCP_API_TOKEN` path stays beside the JWT is #1450's call; requirement 019's wording ("a
   claude.ai connector authorises against Google rather than carrying a shared bearer token")
   reads as dropping it once OAuth is verified, on the same terms as `WEB_UI_PASSWORD`. The old
   "allow all when `ALLOWED_EMAILS` is empty" default and the old dev-mode bypass when secrets are
   unset both contradict the v4 rule that an empty secret closes a surface; the port should close.
5. **Dependencies.** `553e3f0`'s `pyproject.toml` carried `google-auth`, `google-auth-oauthlib`,
   `PyJWT` and `cryptography`; the current one has `httpx` as the only Google transport, and
   `backend/google_client.py` already exchanges tokens with plain `POST` requests to
   `oauth2.googleapis.com/token`. The port either re-adds `google-auth-oauthlib` + `PyJWT` (a
   `pyproject.toml` and `uv.lock` change) or does the code exchange and id-token verification over
   `httpx` in the style of `google_client.py`. Either is a port of the same flow.
6. **A revoked or expired grant must say what to re-run.** The old flows answered 501
   "Authentication service unavailable" for missing settings and 400/502 for a failed exchange.
   Requirement 019 asks for the failure to name the human step, the way `GoogleAuthFailed` does for
   the Calendar/Gmail grant today; that is new text, not old code.
7. **Google Cloud console.** Confirm `GOOGLE_AUTH_REDIRECT_URI`'s value is still an authorised
   redirect URI on the OAuth client, per environment. Nothing in the repository can check this.

### Stays out

`token_encryption.py`, `GoogleTokenRecord`, `GmailOAuthStateRecord`, `GOOGLE_REDIRECT_URI` and
`TOKEN_ENCRYPTION_KEY` belong to the per-user Calendar/Gmail grant that #1412 replaced with the
three-variable credential. They are not part of the login and should not come back with it.
