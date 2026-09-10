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

`MCP_API_TOKEN` is the bearer token for `/mcp`. It is human-provisioned: agents cannot mint it. An
empty value is not a dev-mode bypass — `/mcp` answers 401 to every request and logs a warning at
startup, while `/healthz` stays green so a missing secret cannot roll a deploy back.

The container runs `alembic upgrade head` on startup. A migration failure now fails the boot: there
is no `create_all` fallback, because a schema built from ORM metadata would omit the journal's
append-only trigger.

**One-time step before the first v4 deploy.** The v4 baseline has no `down_revision`, so Alembic
cannot resolve a pre-v4 revision recorded in the database:

```bash
psql "$DATABASE_URL" -c 'DROP TABLE IF EXISTS alembic_version'
```

`WEB_UI_PASSWORD` is the HTTP Basic password for the web view at `/` and the `/api` routes behind
it. Human-provisioned like `MCP_API_TOKEN`: agents cannot mint it, and an empty value is not a
dev-mode bypass — `/` and `/api` answer 401 to every request and log a warning at startup, while
`/healthz` stays green so a missing secret cannot roll a deploy back. `/mcp` is exempt from this
check; its own bearer check still decides.

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
the same class as `MCP_API_TOKEN` and `RAILWAY_TOKEN`. Do not claim a credential is provisioned.

Runbook — when the Google tools start raising `GoogleAuthFailed`, the grant has been revoked or has
expired, and a human re-runs the one-time consent:

```bash
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
uv run python scripts/google_oauth_grant.py
```

It prints a refresh token and stores nothing. Replace `GOOGLE_REFRESH_TOKEN` with it and restart.
Leaving all three unset is safe: the boot succeeds, `/healthz` stays green, the graph tools work,
and only the three Google tools fail — with a message naming what to set.

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
  `google_readers.py`; every writing tool takes a required `actor`, and hard delete is not exposed.
  The three Google tools take no `actor` and journal nothing, because they mutate nothing. The four
  user-model tools are `record_preference`, `add_preference_evidence`, `reject_preference` and
  `get_user_model`; the same model is also served as the `reli://user-model` resource
- Google reads: `backend/google_readers.py` — `find_correspondence`, `find_events`,
  `check_occurred`; read-only and summarising, and they return evidence rather than a verdict
- Google credentials and transport: `backend/google_client.py` — the only module that reads the
  credential and the only one that reaches a Google API, always with a `GET`
- HTTP: `backend/main.py` serves `/healthz`, includes the `/api` router, mounts the MCP
  streamable-HTTP app at `/mcp`, and mounts the frontend bundle **last** — its catch-all answers
  every unmatched path, so anything mounted after it would be dead
- Web view API: `backend/api.py` — the five `/api` routes, their response models, the Basic-auth
  middleware and the SPA mount. Read-only apart from `POST /api/preferences/{id}/reject`, the only
  place `Actor.USER` is used
- Frontend: `frontend/` — Vite + React + TypeScript. Three views in `frontend/src/views/`, the
  `/api` types mirrored in `frontend/src/api.ts`, screenshot tests in `frontend/e2e/`
- Docker service name: `reli` (not `app`)
