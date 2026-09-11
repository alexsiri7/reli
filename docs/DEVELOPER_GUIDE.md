# Reli: Developer Guide

The project layout is in the [README](../README.md) and the rules every change must hold are in
[`CLAUDE.md`](../CLAUDE.md); neither is repeated here. This guide holds the recipes.

## Running the gates

`scripts/gates.sh` is the single source of truth for quality gates, and CI runs the same script:

```bash
./scripts/gates.sh                        # setup, lint, typecheck, test, build
./scripts/gates.sh lint typecheck test    # the stages a docs or backend change needs
./scripts/gates.sh frontend               # npm lint, typecheck, build and the Playwright screenshots
```

`test` starts a throwaway `postgres:16-alpine` via testcontainers and runs the baseline migration
against it, so it needs a Docker daemon; set `RELI_TEST_DATABASE_URL` to use an existing database
instead. `frontend` is not in the no-arg default because it needs node and a browser. Screenshot
snapshots are only valid from the pinned Playwright container — the regeneration command is in
the Screenshot Tests section of `CLAUDE.md`.

## Adding an MCP tool

1. Put the behaviour in `backend/service.py` if it writes (and journal it — every public function
   there writes its row and its journal entry in one transaction) or in `backend/queries.py` if it
   reads. `backend/tests/test_architecture.py` fails the build if any other module constructs a
   `ThingRecord` or `RelationshipRecord`.
2. Add a `@reli_mcp.tool()` wrapper in `backend/mcp_server.py`. A writing tool takes
   `actor: McpActor` as its first argument, with no default. Convert records for output with the
   `_thing_dict` / `_relationship_dict` helpers so tool output and the journal agree.
3. Test it in `backend/tests/test_mcp_tools.py` (tools) and `backend/tests/test_queries.py` or
   `backend/tests/test_service.py` (the layer underneath).

`RelationshipType` in `backend/db_models.py` is the closed set of edge types. Adding one is a
schema change with its own issue, not a side effect of a tool.

## Adding an `/api` route

`/api` is read-only, with rejecting a preference as its single exception. A new route is a thin
wrapper over `backend/queries.py` with an explicit response model in `backend/api.py` — stated
rather than returning the record, so a new column is not silently a new API field. Mirror the
model in `frontend/src/api.ts`, prove the route in `backend/tests/test_api.py`, and stub its
response in `frontend/e2e/fixtures.ts` for the screenshot tests.

## Writing a migration

Migrations live under `backend/alembic/versions/` and are additive only. A new one chains from the
baseline's revision id, which is `v4_baseline` (declared in
`v4_baseline_things_relationships_journal.py`, not its filename):

```bash
uv run alembic revision -m "add ..."
```

Set `down_revision = "v4_baseline"` (or the current head). `DROP TABLE` / `DROP COLUMN` need a data
migration plan and the `# reli:allow-destructive-ddl` comment at the top of the file;
`backend/alembic/safety.py` refuses to run a destructive migration without it, and
`backend/tests/test_ddl_safety.py` covers the check. Test against a copy of the database, never the
live one. Startup runs `alembic upgrade head`; a failing migration fails the boot.

## Inspecting a running instance

```bash
psql "$DATABASE_URL"
```

The `journal` table is the audit trail — how any Thing got to its current state:

```sql
SELECT id, occurred_at, actor, operation, before, after
FROM journal WHERE entity_id = '<uuid>' ORDER BY id;
```

`LOG_LEVEL=DEBUG` turns up the application logs.

## GitHub issue linking

PRs must reference the GitHub issue they contribute to. Include in the PR body:

- `Fixes #N` — if the PR fully completes the issue
- `Part of #N` — if the PR is partial progress

Current feature issues: https://github.com/alexsiri7/reli/issues
