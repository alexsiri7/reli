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

There is no frontend to build. The read-only view described in `docs/vision.md` lands in a later
issue; update this section when it does.

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

**Gone.** #1408 deleted `frontend/` and its screenshot suite. There is no visual regression gate,
and nothing to update snapshots for. Rewrite this section — and the coverage strategy behind it —
when the read-only view lands.

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
- Reads: `backend/queries.py` — the indexed queries
- Retained reference, not built or shipped: `reference/oauth/` (see its README)
- MCP: `backend/mcp_server.py` — the thirteen tools wrapping `service.py` and `queries.py`; every
  writing tool takes a required `actor`, and hard delete is not exposed
- HTTP: `backend/main.py` serves `/healthz` and mounts the MCP streamable-HTTP app at `/mcp`
- Docker service name: `reli` (not `app`)
