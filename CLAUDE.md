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
- Reli's operating behaviour lives in `backend/prompts.py` and is served to sessions by the
  `get_initial_instructions` tool (#1466), because claude.ai applies an MCP prompt only when the
  user picks one. A Claude Project, system prompt or scheduled-task prompt calls the tool rather
  than restating the rules in its own words — a restatement is a copy that drifts with nothing to
  catch it. The scheduled prompts under `prompts/scheduled/` carry the default voice and the two
  conventions pasted verbatim, which is not a restatement:
  `backend/tests/test_scheduled_prompts.py` fails when they diverge.
- **Reli holds no third-party data integration.** If a pass needs outside data, the session
  running it brings its own connector. #1488 deleted the Calendar and Gmail readers, the credential
  reader and the consent script: a check-in is settled by the claude.ai session looking through the
  connectors attached to it and writing what it concluded into the graph. Reli reaches Google to
  sign a user in and for nothing else. Re-adding a data integration inside the service is a design
  error — send mail to mayor.
- **This repository is public.** No real user data is ever committed to it. This covers, and is not limited to: graph exports or database dumps; statistics derived from real data, including tag frequencies and counts; recorded Gmail or Calendar fixtures; briefing Things; preference Things and their evidence; and logs containing Thing titles or notes. Test fixtures are synthetic and written by hand. If a task appears to require real data in the repository, that is a design error — send mail to mayor rather than committing it.
- **Nothing in GitHub Actions reads the graph.** No workflow, job or automation in this
  repository may read an `/api` route or anything else that answers with Things. `/healthz` and
  the Railway and GitHub APIs carry no graph content and stay. GitHub issues are never an
  alerting channel for anything touching user data — alerting for a private system goes to ntfy
  or to the user's own chat. Whether the scheduled passes ran is noticed in-session, by the
  heartbeat Thing falling due, not by an external job (#1484).
  `backend/tests/test_gates.py` scans the workflows and fails on an `/api` read.

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

The `/api` routes serve the user's whole graph and admit a request one way: the `reli_session`
cookie the Google sign-in below sets. There is no HTTP Basic password — #1471 retired
`WEB_UI_PASSWORD` on the owner's decision that the web view is OAuth-only, and no password will be
provisioned, so nothing may reintroduce one. The bundle at `/` is public — it is the sign-in view,
and static code from a public repository — so opening `/` presents Google sign-in rather than a
browser password prompt, and a 401 from `/api` carries no `WWW-Authenticate` challenge for the same
reason. Without the sign-in configured, `/api` answers 401 to every request and logs a warning at
startup, while `/healthz` stays green so a missing secret cannot roll a deploy back. `/mcp` is
exempt from this check; its own bearer check still decides.

`/api/auth/` is the only exemption: it is how a browser gets a session, so it must answer before
there is one. Every other `/api` path is behind the cookie, and #1484 removed the one unauthenticated
route there used to be beside it. Adding another needs an issue that asks for it.

The frontend is built inside the image: the Dockerfile's `frontend-build` stage runs `npm ci` and
`npm run build`, and the python stage copies `frontend/dist` in. `docker compose build` therefore
rebuilds the web view too — there is nothing to build separately. The backend serves the bundle only
when `frontend/dist` is present, so a local `uvicorn` run without one still serves `/api`; use
`npm --prefix frontend run dev` for the view in development.

## Google credentials

A Google credential lives in exactly two environment variables and nowhere else:
`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, the Web application OAuth client that identifies
Reli to Google during the sign-in below. Nothing is derived from them that outlives a request:
`backend/google_login.py` reads them, exchanges a sign-in code and returns the identity, and
persists nothing — not to disk, not to Postgres, not to the journal. Nothing under `backend/`
writes a credential anywhere, and `test_the_google_modules_never_persist_a_credential` fails the
build if that module gains a file write or a database import. That is the answer to #938: a token
file cannot be left behind by code that never writes one.

The scopes are `openid email profile`, listed in `AUTH_SCOPES` in `backend/google_login.py`.
Widening them is a visible edit to that tuple and needs an issue that asks for it.

There is no `GOOGLE_REFRESH_TOKEN` and no consent step: #1488 deleted the `gmail.readonly` /
`calendar.readonly` grant along with the readers it fed, so the only redirect URI the Web client
needs is `GOOGLE_AUTH_REDIRECT_URI`. Leaving both variables unset is safe — the boot succeeds and
`/healthz` stays green; only the sign-in is closed, and it says what to set.

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
`RAILWAY_TOKEN` pattern and agents cannot mint one. Empty closes the sign-in — `/oauth/authorize`
answers 501 naming each missing setting, and no JWT is issued or accepted — and never stops the
boot. **Empty `ALLOWED_EMAILS` admits nobody.**

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
   check this; when it is wrong the callback answers 502 naming `redirect_uri_mismatch`. That one
   redirect URI is the only entry the client needs — #1488 retired the loopback `http://127.0.0.1:18765/`
   that the deleted Calendar and Gmail grant used, and a leftover entry may be removed.
3. Add the claude.ai connector for `https://<host>/mcp` with **no** bearer token. It discovers the
   server, registers itself, opens Google sign-in, and the allowlisted account completes it.
4. Open `https://<host>/`, sign in with the allowlisted account, and confirm the tree loads. The
   password that used to stand beside the cookie is gone (#1471), and nothing outside a browser
   needs a way in.

## Scheduled passes

The proactive half (#1413) is three saved prompts under `prompts/scheduled/` — `resolution-pass.md`,
`learning-pass.md`, `morning-conversation.md`, in that order — each the text of a claude.ai
scheduled task with the Reli connector attached: the same `/mcp` an interactive session uses,
through the same Google sign-in. The resolution pass and the morning conversation also carry the
user's own Calendar and Gmail connectors: a check-in is settled by the session reading the
confirmation itself (#1487). The learning pass reads only the journal and the graph, so it needs
neither. Nothing runs on a schedule inside Reli, and nothing here may be turned into a background
task in the service.
[`prompts/scheduled/README.md`](prompts/scheduled/README.md) describes what the passes leave in the
graph.

**Agents cannot create the scheduled tasks, or verify that claude.ai scheduled tasks run reliably
unattended.** Those are human steps, in the same class as the Google consent step and
`RAILWAY_TOKEN`; do not claim either is done. A human:

1. creates three claude.ai scheduled tasks, each pasting one file's text — the resolution pass
   overnight, the learning pass at least half an hour later, the morning conversation in waking
   hours — each with the Reli connector, and the resolution pass and the morning conversation also
   with the user's Calendar and Gmail connectors;
2. watches the first night. Reliability is *observed*, not assumed, and there is no external
   check: the owner is what makes running the trial in production safe.

**The failure signal.** Each task owns one active Thing tagged `#ScheduledTask` (titled
`Resolution pass`, `Learning pass`, `Morning conversation`) and ends every run by setting its
`checkin_date` to tomorrow. A run that did not complete leaves the Thing due, so a missed run is a
due Thing that every session sees: the next resolution pass notes it in the briefing, the morning
conversation says so in its first line, and `daily-planning` lists it. That is the whole signal —
#1484 removed the GitHub Actions watchdog that used to read the heartbeats from outside, and nothing
replaced it. The heartbeats must never be archived, because an archived Thing leaves the tree and
stops surfacing in `due_for_checkin`, so archiving one hides a missed run instead of reporting it.

**The fallback, documented and not built.** If claude.ai scheduled tasks prove unreliable — the
owner notices a night the passes left no trace — the overnight two move to a host cron running
headless Claude Code: `claude -p "$(cat prompts/scheduled/resolution-pass.md)"` with an
`--mcp-config` naming the same `/mcp` URL, the shape the owner's overnight development
tooling already uses outside this repository. Same files, same heartbeats. The morning conversation
is a conversation and can only be a claude.ai session.

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
- MCP: `backend/mcp_server.py` — the twenty tools wrapping `service.py`, `queries.py` and
  `prompts.py`, behind the OAuth JWT the Google sign-in mints; every
  writing tool takes a required `actor`, and hard delete is not exposed.
  `get_initial_instructions` is the one tool that touches no data: it returns the default
  behaviour, and the server's `instructions` tell a session to call it first.
  `journal_since` is the one cross-Thing journal read, filtered by actor, for the learning pass.
  The four user-model tools are `record_preference`, `add_preference_evidence`, `reject_preference` and
  `get_user_model`; the same model is also served as the `reli://user-model` resource
- Scheduled passes: `prompts/scheduled/` — the three saved prompts for the claude.ai scheduled
  tasks, plain files rather than MCP prompts, with the default voice and the conventions from
  `backend/prompts.py` pasted verbatim and `backend/tests/test_scheduled_prompts.py` holding them
  to it
- Prompts: `backend/prompts.py` — the text of the four MCP prompts `capture`, `daily-planning`,
  `project-planning` and `review`, registered in `mcp_server.py`, and `initial_instructions`,
  what `get_initial_instructions` returns: `capture` derived at call time plus a paragraph naming
  the three hats, never a second copy. Every prompt carries `DEFAULT_VOICE`, the
  preference-capture convention and the check-in semantics, held as constants there so a test can
  prove it — the voice states how the assistant sounds and, in the same constant, that confidence
  of manner is never confidence of fact (#1492) — and names the two preference scopes it loads:
  the one for its mode and `voice` beside it, which is how the user moves the assistant off that
  default (#1493). Those five scope labels (`capture`, `scheduling`, `planning`, `review`,
  `voice`) are the scope vocabulary — reuse them rather than coin new ones. `voice` is the one
  scope the learning pass never records under: the journal holds mutations, not conversation
- Google sign-in: `backend/google_login.py` — the only code that reaches Google at all, and the
  only one that reads the credential: the authorization URL, the code exchange and the id-token
  claims; persists nothing
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
- Web view API: `backend/api.py` — the five `/api` routes, their response models, the session
  middleware and the SPA mount. Read-only apart from
  `POST /api/preferences/{id}/reject`, the only place `Actor.USER` is used
- Frontend: `frontend/` — Vite + React + TypeScript. Three views and the sign-in view in
  `frontend/src/views/`, the `/api` types mirrored in `frontend/src/api.ts`, screenshot tests in
  `frontend/e2e/`
- Docker service name: `reli` (not `app`)
