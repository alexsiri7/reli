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

## Key paths

- Backend: `backend/` (FastAPI, Python)
- Frontend: `frontend/` (React, Vite, Tailwind)
- API routes: `backend/routers/` — all mounted under `/api` prefix
- Docker service name: `reli` (not `app`)
