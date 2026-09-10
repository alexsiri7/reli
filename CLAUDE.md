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

These rules bind new work; the merged code has not been migrated to them yet. Hierarchy is stored today under the `parent-of`/`child-of` relationship literals (`backend/mcp_server.py`, `backend/routers/things.py`, the sweeps), so query the live schema by the names it actually uses. The existing Alembic history still carries the confidence floats the fourth rule forbids (`sweep_findings.confidence`, and the `confidence` columns in `backend/db_models.py`). Reconciling both with these rules is the Postgres schema work in #1408, not something to do by renaming things in passing.

## Deployment

The app runs in Docker. After merging code changes, the container must be rebuilt:

```bash
cd /home/asiri/gt/reli/mayor/rig
git pull
npm --prefix frontend ci --legacy-peer-deps
npm --prefix frontend run build
docker compose build && docker compose up -d
```

Frontend has a peer dependency conflict — always use `--legacy-peer-deps` with npm.

These commands still deploy the application currently in the tree. The rebuild replaces the frontend with a read-only view and the database with Postgres, so the frontend build step and the volume layout will change — update this section when that lands, not before. Do not guess at commands for a frontend that does not exist yet.

## Database Safety Policy

The legacy SQLite (`data/reli.db`) and ChromaDB (`backend/chroma_db/`) data are superseded. The owner holds an offline export of the legacy graph outside this repository — the repo is public, so the export is not here and must not be committed or recreated here.

The rebuild starts the Postgres schema from a clean baseline migration. That baseline is allowed to define the schema outright; it is not held to the additive-only rule, and it does not need to preserve or migrate the legacy tables. Clean baseline does not mean unstarted: the current Alembic history already runs against Postgres and carries pre-v4 debt, including the confidence-float columns, so the baseline has to drop that debt deliberately rather than inherit it.

From that baseline forward, the additive-only rule applies:

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

**Suspended.** The frontend is being rebuilt as the read-only view described in `docs/vision.md`, so the screens `frontend/e2e/visual.spec.ts` covers are going away. Do not update snapshots to make the suite pass, and do not treat its failures as a signal about your change.

Rewrite this section — and the coverage strategy behind it — once the read-only view exists.

## Railway Token Rotation

**Agents cannot rotate the Railway API token.** The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.

When CI fails with `RAILWAY_TOKEN is invalid or expired`:
1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
2. File a GitHub issue or send mail to mayor with the error details.
3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.

Creating documentation that claims success on an action you cannot perform is a Category 1 error.

## Key paths

- Backend: `backend/` (FastAPI, Python)
- Frontend: `frontend/` (React, Vite, Tailwind)
- API routes: `backend/routers/` — all mounted under `/api` prefix
- Docker service name: `reli` (not `app`)
