# Reli — Agent Instructions

## Polecat Scope Discipline

**Fix only what your assigned bead describes.**

If you discover a bug, improvement, or issue outside your bead's scope:
1. Send a mail to mayor: `gt mail send mayor/ --subject "Found: <brief title>" --body "<details>"`
2. Continue your original task — do NOT fix the out-of-scope issue

**Why:** Out-of-scope changes break unrelated tests, cause MR rejections, and waste cycles.

## Architectural rules

Non-negotiables from `docs/vision.md`. They hold even when a bead description or an existing code path suggests otherwise.

- No LLM call originates inside the Reli service. If a task seems to need one, that is a design error — send mail to mayor rather than adding an LLM dependency.
- `parent_id` does not exist. Hierarchy is a `ChildOf` relationship.
- Every mutation writes a journal entry. A code path that changes a Thing without journalling is a bug.
- No derived state without evidence links. No confidence floats.
- The frontend never writes, with one exception: rejecting a preference.
- **This repository is public.** No real user data is ever committed to it. This covers, and is not limited to: graph exports or database dumps; statistics derived from real data, including tag frequencies and counts; recorded Gmail or Calendar fixtures; briefing Things; preference Things and their evidence; and logs containing Thing titles or notes. Test fixtures are synthetic and written by hand. If a task appears to require real data in the repository, that is a design error — send mail to mayor rather than committing it.

The merged code now follows these rules: #1408 deleted the LLM pipeline, replaced the schema and made hierarchy a `ChildOf` relationship. The five relationship-type literals are defined once, in `RelationshipType` in `backend/db_models.py` — use them, do not invent a sixth without an issue that asks for it.

The user model (#1410) follows from the same rules. Preferences are Things tagged `#Preference`,
anchored to the single `#User` Thing at `USER_ANCHOR_ID` by a `RelatedTo` edge running anchor →
preference. Evidence is an `EvidenceFor` edge from a Thing, so a journal entry becomes evidence only
once a Thing tagged `#Observation` carrying `notes["journal_entry_id"]` stands for it — a
relationship cannot point at anything but a Thing. Strength is the count of those edges; there is no
confidence anywhere and none may be added. `McpActor` was deliberately **not** widened with
`Actor.USER`: `reject_preference` over MCP records the Claude session that relayed the rejection.

## Deployment

The app runs in Docker. After merging code changes, the container must be rebuilt:

```bash
cd /home/asiri/gt/reli/mayor/rig
git pull
docker compose build && docker compose up -d
```

`DATABASE_URL` must be set in the environment — there is no default, and the service refuses to
start without it rather than silently using an empty database.

The only credential `/mcp` accepts is a JWT the OAuth 2.1 authorization server at `/oauth/*` mints
after a Google sign-in (see *Google sign-in* below), which is how a claude.ai connector authorises
without holding a shared secret; the static `MCP_API_TOKEN` it used to accept beside the JWT was
retired in #1461 and a value left in a deploy's environment is ignored. `SECRET_KEY` is
human-provisioned: agents cannot mint it. An empty value is not a dev-mode bypass — `/mcp` answers
401 to every request and logs a warning at startup, while `/healthz` stays green so a missing
secret cannot roll a deploy back. `/mcp` is open to every account in `ALLOWED_EMAILS`.

The container runs `alembic upgrade head` on startup. A migration failure now fails the boot: there
is no `create_all` fallback, because a schema built from ORM metadata would omit the journal's
append-only trigger.

**One-time step before the first v4 deploy.** The v4 baseline has no `down_revision`, so Alembic
cannot resolve a pre-v4 revision recorded in the database:

```bash
psql "$DATABASE_URL" -c 'DROP TABLE IF EXISTS alembic_version'
```

The `/api` routes serve the user's whole graph and admit a request two ways: the `reli_session`
cookie the Google sign-in below sets, or `WEB_UI_PASSWORD` as an HTTP Basic password. The bundle
at `/` is public — it is the sign-in view, and static code from a public repository — so opening
`/` presents Google sign-in rather than a browser password prompt, and a 401 from `/api` carries no
`WWW-Authenticate` challenge for the same reason. `WEB_UI_PASSWORD` is human-provisioned like
`SECRET_KEY`: agents cannot mint it, and an empty value is not a dev-mode bypass. With neither
it nor the sign-in configured, `/api` answers 401 to every request and logs a warning at startup,
while `/healthz` stays green so a missing secret cannot roll a deploy back. The password stays
beside the cookie — it is what `curl` and the scheduled-pass watchdog carry — until a human
confirms Google sign-in works on the deploy and retires it in its own change (#1449). Agents must
not remove it. `/mcp` is exempt from this check; its own bearer check still decides.

The frontend is built inside the image: the Dockerfile's `frontend-build` stage runs `npm ci` and
`npm run build`, and the python stage copies `frontend/dist` in. `docker compose build` therefore
rebuilds the web view too — there is nothing to build separately. The backend serves the bundle only
when `frontend/dist` is present, so a local `uvicorn` run without one still serves `/api`; use
`npm --prefix frontend run dev` for the view in development.

## Google credentials

A Google credential lives in exactly three environment variables and nowhere else:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`. The access token derived from
them is held in process memory by `backend/google_client.py` and is never persisted — not to disk,
not to Postgres, not to the journal. Nothing under `backend/` writes a credential anywhere, and
`test_the_google_modules_never_persist_a_credential` fails the build if either module gains a file
write or a database import. That is the answer to #938: a token file cannot be left behind by code
that never writes one.

The scopes granted are `gmail.readonly` and `calendar.readonly`, listed in `SCOPES` in
`backend/google_client.py`. Widening them is a visible edit to that tuple and needs an issue that
asks for it.

**Agents cannot perform the consent step.** It requires a human signed in to the Google account, in
the same class as `WEB_UI_PASSWORD` and `RAILWAY_TOKEN`. Do not claim a credential is provisioned.

Runbook — when the Google tools start raising `GoogleAuthFailed`, the grant has been revoked or has
expired, and a human re-runs the one-time consent:

```bash
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
uv run python scripts/google_oauth_grant.py
```

Before the first run, a human adds `http://127.0.0.1:18765/` — the exact string, trailing slash
included — to the authorised redirect URIs of the Web application client `GOOGLE_CLIENT_ID` names,
in the Google Cloud console. A Web client accepts only a redirect registered verbatim, so the script
sends that one fixed loopback URI (#1460); a missing entry answers `redirect_uri_mismatch` on the
consent page. Nothing in the repository can perform or check the console step.

It prints a refresh token and stores nothing. Replace `GOOGLE_REFRESH_TOKEN` with it and restart.
Leaving all three unset is safe: the boot succeeds, `/healthz` stays green, the graph tools work,
and only the three Google tools fail — with a message naming what to set.

The same `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` also identify Reli to Google for the sign-in
below, read by `backend/google_login.py` under the same never-persist rule (it is in the same
test's `GOOGLE_MODULES`), with the `openid email profile` scopes — the readers' `SCOPES` tuple is
unchanged. The readers' grant is minted through that same Web client, which is why one pair
suffices: a refresh token is only refreshable with the secret of the client that minted it, and
`backend/google_client.py` sends this one.

## Google sign-in

The OAuth 2.1 authorization server in `backend/mcp_oauth.py` (#1450, requirement 019) lets a
claude.ai connector authorise against `/mcp` by signing in to Google rather than carrying a shared
secret: the connector discovers `/.well-known/oauth-authorization-server`, registers
itself at `/oauth/register`, is sent through Google by `/oauth/authorize`, lands on
`/api/auth/google/callback` (`backend/auth.py`), and exchanges the code at `/oauth/token` for an
`aud="mcp"` JWT that `/mcp` accepts. Identity is the Google account: there is no users table, the
allowlisted email lives in the token, and the five tables in `backend/oauth_state.py` — four
`mcp_*` and `web_oauth_sessions` — hold only flow state — none of it is a Thing, so none of it
journals.

The web view (#1449) signs in through the same Google client and the same callback. The sign-in
view calls `GET /api/auth/google` for the Google URL (a 501 names each missing setting, shown in
place), Google lands on `/api/auth/google/callback`, and the callback sets `reli_session` — an
`httponly`, `samesite=lax` cookie holding an `aud="web"` JWT good for seven days, `Secure` whenever
the base URL is https — and redirects to `/`. An account outside `ALLOWED_EMAILS` is sent to
`/?error=invite_only`, which the view turns into a sentence; a Google refusal at the exchange is a
502 whose detail names the human step, as for MCP. `GET /api/auth/me` is the view's "am I signed
in" probe and `POST /api/auth/logout` deletes the cookie; there is no revocation list. The
redirect URI is the one already documented below — the web sign-in adds no console entry.

Its settings are `SECRET_KEY`, `ALLOWED_EMAILS`, `GOOGLE_AUTH_REDIRECT_URI` and `RELI_BASE_URL`,
beside `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Every one is human-provisioned on the
`WEB_UI_PASSWORD` pattern: empty closes the sign-in — `/oauth/authorize` answers 501 naming each
missing setting, and no JWT is issued or accepted — and never stops the boot. **Empty
`ALLOWED_EMAILS` admits nobody.**

**The human steps, none of which an agent can perform or verify.** Do not claim any of these is
done:

1. Set the settings on the deploy: `SECRET_KEY` to at least 32 random bytes
   (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), `ALLOWED_EMAILS` to the
   owner's Google address, `GOOGLE_AUTH_REDIRECT_URI` to `https://<host>/api/auth/google/callback`.
   #1448 found `SECRET_KEY`, `ALLOWED_EMAILS` and `GOOGLE_AUTH_REDIRECT_URI` still set on Railway
   from before the rebuild; a human checks the values, in particular that the redirect URI's path
   is exactly this one.
2. In the Google Cloud console, confirm the OAuth client `GOOGLE_CLIENT_ID` names is a **Web
   application** client with that exact redirect URI authorised. Nothing in the repository can
   check this; when it is wrong the callback answers 502 naming `redirect_uri_mismatch`. The
   readers' grant shares this Web client: its loopback redirect `http://127.0.0.1:18765/` is
   registered on the same client (see *Google credentials*).
3. Add the claude.ai connector for `https://<host>/mcp` with **no** bearer token. It discovers the
   server, registers itself, opens Google sign-in, and the allowlisted account completes it. The
   owner confirmed this on 2026-09-11, which is what retired `MCP_API_TOKEN` (#1461).
4. Open `https://<host>/`, sign in with the allowlisted account, and confirm the tree loads. Then
   retire `WEB_UI_PASSWORD` in a follow-up change — remembering the watchdog in
   `.github/workflows/scheduled-run-health.yml` reads `/api/things` with it and needs another way
   in first. Until then the password stays, and agents must not remove it.

## Scheduled passes

The proactive half (#1413) is three saved prompts under `prompts/scheduled/` — `resolution-pass.md`,
`learning-pass.md`, `morning-conversation.md`, in that order — each the text of a claude.ai
scheduled task with the Reli connector attached: the same `/mcp`, through the same Google sign-in,
an interactive session uses. Nothing runs on a schedule inside Reli, and nothing here may be turned
into a background task in the service. [`prompts/scheduled/README.md`](prompts/scheduled/README.md)
describes what the passes leave in the graph.

**Agents cannot create the scheduled tasks, add the watchdog's secret, or verify that claude.ai
scheduled tasks run reliably unattended.** Those are human steps, in the same class as the Google
consent step and `WEB_UI_PASSWORD`; do not claim any of them is done. A human:

1. creates three claude.ai scheduled tasks, each pasting one file's text — the resolution pass
   overnight, the learning pass at least half an hour later, the morning conversation in waking
   hours — with the Reli connector attached;
2. adds `WEB_UI_PASSWORD` to the repository's GitHub Actions secrets, the same value as the
   deploy's, so the watchdog can read `/api/things`;
3. watches the first night. Reliability is *observed*, not assumed: the watchdog below is what
   makes running the trial in production safe.

**The failure signal.** Each task owns one active Thing tagged `#ScheduledTask` (titled
`Resolution pass`, `Learning pass`, `Morning conversation`) and ends every run by setting its
`checkin_date` to tomorrow. A run that did not complete leaves the Thing due, so a missed run is a
due Thing that every session sees: the next resolution pass notes it in the briefing, the morning
conversation says so in its first line, and `daily-planning` lists it.
`.github/workflows/scheduled-run-health.yml` reads the tree's top level at noon UTC, after all
three windows, and files a "Scheduled pass missed" issue — and pings `NTFY_TOPIC` if set — when
fewer than three heartbeats exist or any is still due. It files an issue until the secret is added
and the tasks have run once; that first issue is the reminder, not a bug in the check. The
heartbeats must never be archived or made a child of anything, because the check reads
`/api/things`, which is the top level only.

**The fallback, documented and not built.** If claude.ai scheduled tasks prove unreliable — the
first "Scheduled pass missed" issue that is not a human step left undone — the overnight two move
to a host cron running headless Claude Code: `claude -p "$(cat prompts/scheduled/resolution-pass.md)"`
with an `--mcp-config` naming the same `/mcp` URL, the shape the owner's overnight development
tooling already uses outside this repository. Same files, same heartbeats, same
watchdog. The morning conversation is a conversation and can only be a claude.ai session.

**Actor discipline.** The overnight passes pass `actor="claude_scheduled"` on every write. The
morning conversation splits: `claude_scheduled` for its own bookkeeping (its heartbeat, archiving
the briefing) and `claude_interactive` for every write that encodes something the user said.
`user` is the web view's reject button and nothing else. The learning pass reads
`journal_since(actors=["user", "claude_interactive"])`, so a `claude_scheduled` write is never
mistaken for user behaviour — that is the whole reason the split must be honest.

## Database Safety Policy

The legacy SQLite (`data/reli.db`) and ChromaDB (`backend/chroma_db/`) data are superseded. The owner holds an offline export of the legacy graph outside this repository — the repo is public, so the export is not here and must not be committed or recreated here.

The clean baseline has landed: `backend/alembic/versions/v4_baseline_things_relationships_journal.py` is the only revision, it has no `down_revision`, and it drops the 29 pre-v4 tables — and with them `parent_id` and the confidence floats — before creating `things`, `relationships` and `journal`.

**The additive-only rule is now in force.** Every migration from here is additive:

1. **Schema changes are additive migrations** (`ALTER TABLE`, `CREATE TABLE IF NOT EXISTS`). Destructive DDL (`DROP TABLE`, `DROP COLUMN`) needs a data migration plan. When a destructive operation is intentional and the data is preserved, add `# reli:allow-destructive-ddl` as a top-level comment in the migration file to opt in per-migration (preferred over the global `ALLOW_DESTRUCTIVE_DDL=true` env override).
2. **Test migrations against a copy first**, never against the live database.
3. **Never hard-code a connection string or DB path** — it comes from the environment.

Post-baseline data is production data again: once the new schema holds real Things, deleting or recreating the database is off the table.

## GitHub Issue Linking

PRs MUST reference the GitHub issue they contribute to. This is how we track feature progress.

When creating a PR (or when `gt done` creates one), include in the PR body:
- `Fixes #N` — if the PR fully completes the feature/issue
- `Part of #N` — if the PR is partial progress toward the feature

Current feature issues: https://github.com/alexsiri7/reli/issues

If your bead description mentions a GitHub issue number, use it. If not, check the
issues list to see if your work maps to an existing feature issue.

## Screenshot Tests (Visual Regression)

#1414 rebuilt `frontend/` and its screenshot suite. The specs live in `frontend/e2e/views.spec.ts`,
one per view, and the committed snapshots in `frontend/e2e/views.spec.ts-snapshots/`.

**Every `/api` response is stubbed** with `page.route` from `frontend/e2e/fixtures.ts`. No database,
no backend, no clock: a screenshot test is a view test, and the API contract is proven by
`backend/tests/test_api.py` instead. A spec that reaches for a real server is the wrong fix.

**Snapshots are only valid from the pinned Playwright container**, whose tag matches the
`@playwright/test` version in `frontend/package.json` exactly. CI runs the `frontend` job in that
same `container:`. Never regenerate on a developer's host — the host's fonts render different pixels
and the diff means nothing:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work/frontend \
  mcr.microsoft.com/playwright:v1.63.0-noble npx playwright test --update-snapshots
```

Bumping `@playwright/test` means bumping the tag in that command and in `.github/workflows/ci.yml`
together, and regenerating.

## Railway Token Rotation

**Agents cannot rotate the Railway API token.** The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.

When CI fails with `RAILWAY_TOKEN is invalid or expired`:
1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
2. File a GitHub issue or send mail to mayor with the error details.
3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.

Creating documentation that claims success on an action you cannot perform is a Category 1 error.

## Key paths

- Backend: `backend/` (FastAPI, Python) — the whole service
- Schema: `backend/db_models.py` — `things`, `relationships`, `journal`, and the enums
- Writes: `backend/service.py` — the only module that may mutate a Thing; every function journals
- Reads: `backend/queries.py` — the indexed queries, including `user_model`
- Retained reference, not built or shipped: `reference/oauth/` (see its README)
- MCP: `backend/mcp_server.py` — the twenty-two tools wrapping `service.py`, `queries.py` and
  `google_readers.py`, behind the OAuth JWT the Google sign-in mints; every writing tool takes a
  required `actor`, and hard delete is not exposed.
  `journal_since` is the one cross-Thing journal read, filtered by actor, for the learning pass.
  The three Google tools take no `actor` and journal nothing, because they mutate nothing. The four
  user-model tools are `record_preference`, `add_preference_evidence`, `reject_preference` and
  `get_user_model`; the same model is also served as the `reli://user-model` resource
- Scheduled passes: `prompts/scheduled/` — the three saved prompts for the claude.ai scheduled
  tasks, plain files rather than MCP prompts, with the conventions from `backend/prompts.py` pasted
  verbatim and `backend/tests/test_scheduled_prompts.py` holding them to it
- Prompts: `backend/prompts.py` — the text of the four MCP prompts `capture`, `daily-planning`,
  `project-planning` and `review`, registered in `mcp_server.py`. Every one carries the
  preference-capture convention and the check-in semantics, held as constants there so a test can
  prove it, and names the one preference scope it loads; those scope labels (`capture`,
  `scheduling`, `planning`, `review`) are the scope vocabulary — reuse them rather than coin new ones
- Google reads: `backend/google_readers.py` — `find_correspondence`, `find_events`,
  `check_occurred`; read-only and summarising, and they return evidence rather than a verdict
- Google credentials and transport: `backend/google_client.py` — the only module that reads the
  credential and the only one that reaches a Google API, always with a `GET`
- Google sign-in: `backend/google_login.py` — the only code that reaches Google for sign-in: the
  authorization URL, the code exchange and the id-token claims; persists nothing
- JWTs, the callback and the web session: `backend/auth.py` — `create_jwt` / `decode_jwt`, the
  allowlist, `GET /api/auth/google/callback` (the one address Google redirects to, for both
  flows), the web view's `GET /api/auth/google`, `GET /api/auth/me` and `POST /api/auth/logout`,
  and `web_session`, the one reading of the `reli_session` cookie
- Authorization server: `backend/mcp_oauth.py` — `/.well-known/*`, `/oauth/register`,
  `/oauth/authorize`, `/oauth/token`
- OAuth flow state: `backend/oauth_state.py` — the four bounded `mcp_*` stores and
  `web_oauth_sessions`; not graph state, not journalled
- HTTP: `backend/main.py` serves `/healthz`, includes the auth, OAuth and `/api` routers in that
  order, mounts the MCP streamable-HTTP app at `/mcp`, and mounts the frontend bundle **last** — its
  catch-all answers every unmatched path, so anything mounted after it would be dead
- Web view API: `backend/api.py` — the five `/api` routes, their response models, the
  session-or-password middleware and the SPA mount. Read-only apart from
  `POST /api/preferences/{id}/reject`, the only place `Actor.USER` is used
- Frontend: `frontend/` — Vite + React + TypeScript. Three views and the sign-in view in
  `frontend/src/views/`, the `/api` types mirrored in `frontend/src/api.ts`, screenshot tests in
  `frontend/e2e/`
- Docker service name: `reli` (not `app`)
