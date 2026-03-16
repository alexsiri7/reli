# Reli — Agent Instructions

## Polecat Scope Discipline

**Fix only what your assigned bead describes.**

If you discover a bug, improvement, or issue outside your bead's scope:
1. Send a mail to mayor: `gt mail send mayor/ --subject "Found: <brief title>" --body "<details>"`
2. Continue your original task — do NOT fix the out-of-scope issue

**Why:** Out-of-scope changes break unrelated tests, cause MR rejections, and waste cycles.

## Deployment

The app runs in Docker. After merging code changes, the container must be rebuilt:

```bash
cd /home/asiri/gt/reli/mayor/rig
git pull
npm --prefix frontend install --legacy-peer-deps
npm --prefix frontend run build
docker compose build && docker compose up -d
```

Frontend has a peer dependency conflict — always use `--legacy-peer-deps` with npm.

## Database Safety Policy

Reli stores user data in two places — both contain production data that must be protected.

### SQLite (`data/reli.db`)

1. **NEVER delete or recreate the database file.** The Docker volume mounts `./data:/app/data` — the DB persists across container rebuilds.
2. **Schema changes must use additive SQL migrations** (`ALTER TABLE`, `CREATE TABLE IF NOT EXISTS`). See `backend/database.py` for the existing migration pattern. Never use destructive DDL (`DROP TABLE`, `DROP COLUMN`) without a data migration plan.
3. **Test migrations on a copy first** — copy `reli.db` and run your migration against the copy before committing.
4. **Never hard-code a different DB path** — the path is set by `DATA_DIR` env var (defaults to `backend/`). Production uses `/app/data` inside the container.

### ChromaDB (`backend/chroma_db/`)

1. **NEVER delete the `chroma_db/` directory.** It contains vector embeddings for user data.
2. Collection deletions require explicit justification and should preserve the data elsewhere first.

### What's safe

- The Dockerfile does NOT touch the database on startup (it only runs uvicorn).
- `docker compose build` is safe — it rebuilds the image without affecting the mounted `data/` volume.
- `init_db()` in `database.py` uses `IF NOT EXISTS` — safe to call repeatedly.

## GitHub Issue Linking

PRs MUST reference the GitHub issue they contribute to. This is how we track feature progress.

When creating a PR (or when `gt done` creates one), include in the PR body:
- `Fixes #N` — if the PR fully completes the feature/issue
- `Part of #N` — if the PR is partial progress toward the feature

Current feature issues: https://github.com/alexsiri7/reli/issues

If your bead description mentions a GitHub issue number, use it. If not, check the
issues list to see if your work maps to an existing feature issue.

## Key paths

- Backend: `backend/` (FastAPI, Python)
- Frontend: `frontend/` (React, Vite, Tailwind)
- API routes: `backend/routers/` — all mounted under `/api` prefix
- Docker service name: `reli` (not `app`)
