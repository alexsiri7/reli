# Reli: Setup & Deployment

## Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/)
- **Docker and Docker Compose** — for the local Postgres, the test suite (which starts a throwaway
  Postgres via testcontainers) and production
- **Node 22** — only for frontend development; the Docker image builds the bundle itself

There is no LLM key to provision and no OAuth login. Reli has one user and no accounts.

## Local development

```bash
git clone https://github.com/alexsiri7/reli.git
cd reli
uv sync --frozen
cp .env.example .env
docker compose --profile localdb up -d postgres
```

`.env.example` already points `DATABASE_URL` at the `localdb` Postgres:

```
DATABASE_URL=postgresql://reli:reli@localhost:5432/reli
```

Then run the backend, and the web view if you want it:

```bash
uvicorn backend.main:app --reload --port 8000
npm --prefix frontend install && npm --prefix frontend run dev   # Vite on :5173, proxying /api to :8000
```

Startup runs `alembic upgrade head`; a migration failure fails the boot. `curl localhost:8000/healthz`
answers `{"status":"ok","service":"reli"}`.

`/mcp` answers 401 to every request until `MCP_API_TOKEN` is set, and `/` and `/api` answer 401
until `WEB_UI_PASSWORD` is set. There is no dev-mode bypass — set both in `.env` to use them
locally.

## Connecting Claude

`/mcp` is an MCP streamable-HTTP endpoint. Every request needs
`Authorization: Bearer $MCP_API_TOKEN`; put the same value in the claude.ai connector for
`https://<your-host>/mcp`. The tools, prompts and resources it serves are listed in
[mcp-design.md](mcp-design.md).

## Google (optional)

The three Google tools (`find_correspondence`, `find_events`, `check_occurred`) read Gmail and
Calendar with the `gmail.readonly` and `calendar.readonly` scopes. They need `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN`. A human obtains the refresh token once — the
consent step needs a person signed in to the Google account:

```bash
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
uv run python scripts/google_oauth_grant.py
```

It prints a refresh token and stores nothing. Leaving all three unset is safe: the boot succeeds,
`/healthz` stays green, the graph tools work, and only the three Google tools fail, with a message
naming what to set. When they start raising `GoogleAuthFailed`, the grant has expired or been
revoked — re-run the consent and replace `GOOGLE_REFRESH_TOKEN`.

## Docker production deployment

```bash
docker compose up -d
```

The image builds the frontend bundle in a node stage and serves it from the same container; the
health check is at `http://localhost:8000/healthz`, the MCP endpoint at `/mcp` and the web view at
`/`. Data lives in Postgres, not on the container filesystem.

After merging code changes, rebuild:

```bash
git pull
docker compose build && docker compose up -d
```

**One-time step before the first v4 deploy** against a database that still holds a pre-v4 Alembic
revision. The v4 baseline has no `down_revision`, so Alembic cannot resolve the recorded one:

```bash
psql "$DATABASE_URL" -c 'DROP TABLE IF EXISTS alembic_version'
```

Staging runs on the same host from `docker-compose.staging.yml` (port 8001, its own Postgres):

```bash
docker compose -f docker-compose.staging.yml up -d
```

## Environment variables

These are the fields of `Settings` in `backend/config.py`, and nothing else is read by the app.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | **Required.** Postgres connection string. No default: the boot fails without it rather than serving an empty database. |
| `MCP_API_TOKEN` | empty | Bearer token for `/mcp`. Human-provisioned. Empty closes the endpoint (401 to everything) and logs a warning; it never opens it. |
| `WEB_UI_PASSWORD` | empty | HTTP Basic password for `/` and `/api`; any username. Human-provisioned. Empty closes the view (401), never opens it. |
| `GOOGLE_CLIENT_ID` | empty | Google OAuth client, see above. Empty disables only the three Google tools. |
| `GOOGLE_CLIENT_SECRET` | empty | As above. |
| `GOOGLE_REFRESH_TOKEN` | empty | As above; printed by `scripts/google_oauth_grant.py`. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `SENTRY_DSN` | empty | Empty disables Sentry. |
| `SENTRY_ENVIRONMENT` | `production` | Environment tag on Sentry events. |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.2` | Sentry tracing sample rate. |

Read by the host or the image, not by the app:

- `PORT` — the Dockerfile's `CMD` and healthcheck, and Railway; default 8000.
- `RELI_IMAGE_TAG` — which `ghcr.io/alexsiri7/reli` tag both compose files run; default `latest`.
- `STAGING_DATABASE_URL`, `STAGING_POSTGRES_PASSWORD` — `docker-compose.staging.yml`, kept distinct
  from production's so staging never points at production data.
- `CLOUDFLARE_TUNNEL_TOKEN` — the Cloudflare Tunnel on the host, pointed at `http://reli:8000`.
- `RELI_TEST_DATABASE_URL` — `backend/tests/conftest.py`: run the suite against an existing
  database instead of a testcontainers one.

## Data safety

Postgres holds production data. Every migration from the v4 baseline is additive (`ALTER TABLE`,
`CREATE TABLE IF NOT EXISTS`); destructive DDL needs a data migration plan and the
`# reli:allow-destructive-ddl` opt-in comment in the migration file, which
`backend/alembic/safety.py` checks at startup and `backend/tests/test_ddl_safety.py` covers. Test a
migration against a copy first, never against the live database. Connection strings come from the
environment — never hard-code one.

## CI/CD

`.github/workflows/ci.yml` runs four jobs on every push and pull request, each a stage of
`scripts/gates.sh`:

1. **Lint & Typecheck** — `ruff check`, `ruff format --check`, `mypy`
2. **Test** — pytest with coverage ≥ 70%, against a testcontainers Postgres
3. **Frontend** — `npm run lint`, `typecheck`, `build` and the Playwright screenshot tests, inside
   the pinned Playwright container the snapshots were generated in
4. **Build Docker image** — on `main`, pushed to GHCR as `:<sha>` and `:latest`, keeping the last
   three SHA tags

A green run on `main` triggers `staging-pipeline.yml`: deploy to Railway staging, wait for
`/healthz`, then deploy the same image to production. The secrets it needs are listed in
[DEPLOYMENT_SECRETS.md](../DEPLOYMENT_SECRETS.md); rolling back is [ROLLBACK.md](ROLLBACK.md).
