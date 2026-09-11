# Reli

Reli is the memory and the obligations layer that lets Claude act as a complete personal assistant. It stores knowledge as "Things" in a knowledge graph, tracks what needs checking and when, and learns how you actually operate — so that any Claude session, interactive or scheduled, starts already knowing.

The goal is a PA that says "bring a change of clothes today, you have that event tonight" or "it's Saturday morning — your energy contract expires next month, want me to find a better deal?" — one that understands your life context, your schedule, your routines, and the right moment to act.

Reli is being rebuilt. The data layer, the MCP tools over it, the user model, the read-only web view and the prompts for the scheduled passes are what exists today.

## How it works

Everything you tell Reli — tasks, notes, ideas, people, projects — becomes a **Thing** in your personal knowledge graph. Things are tagged, linked by typed relationships, and enriched over time. Each Thing can carry a check-in date, which is Reli's record that something needs verifying by then.

Reli also learns *how you operate*. Preferences like "avoids morning meetings" or "does venue-before-budget when planning events" are tracked as first-class Things, each linked to the specific evidence that produced it.

Reli does no reasoning of its own. Every judgement call happens in Claude — interactively over MCP, or in a scheduled session — and Reli stores the result, journalling every mutation with the actor that made it.

## Vision

Reli is a service, not a product: MCP + claude.ai + scheduled tasks together should cover the whole job of a PA. See the [vision document](docs/vision.md) for the full picture — the layers, the user model, what check-ins mean, and what is deliberately not being built.

For how Reli compares to related projects, see [comparisons](docs/comparisons.md).

## Tech Stack

**Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic, SQLModel
**Frontend:** React + TypeScript, built with Vite and served by the same container — a read-only view over the graph, with rejecting a preference as its only write
**Storage:** Postgres
**Interface:** MCP — every write goes through an MCP client, except rejecting a preference; the `/api` routes the web view reads are read-only
**Integrations:** Google Calendar and Gmail, read-only — `backend/google_client.py` and `backend/google_readers.py`; `reference/oauth/` holds the pre-rebuild code, not reused
**Infrastructure:** Docker, Cloudflare Tunnel, GitHub Actions CI, Railway (staging + production deploy)

Today the service is the data layer, the MCP tools over it at `/mcp` — including the read-only Calendar and Gmail readers and the user model — the read-only web view at `/` with the `/api` routes behind it, and a health check. The scheduled passes are prompt files under `prompts/scheduled/`, run as Claude scheduled tasks against that same `/mcp`.

## Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose — for the database, the test suite and production

### 1. Clone and install dependencies

```bash
git clone https://github.com/alexsiri7/reli.git
cd reli
uv sync --frozen
```

### 2. Start a database and point the app at it

`DATABASE_URL` is required and has no default — the service refuses to start without it rather than
silently using an empty database.

`/mcp` and the web view's `/api` are both guarded by what a Google sign-in mints — `SECRET_KEY`,
`ALLOWED_EMAILS`, `GOOGLE_AUTH_REDIRECT_URI` and the Google client, with the human steps in
CLAUDE.md's *Google sign-in* section: `/mcp` takes only the JWTs its OAuth 2.1 authorization
server issues, so a claude.ai connector authorises without holding a shared secret, and the web
view at `/` presents Google sign-in and holds the session in a cookie. `WEB_UI_PASSWORD` is the
HTTP Basic password the `/api` routes behind the web view still accept beside the cookie; leaving
it empty does not open what it guards. `/mcp` answers 401 to every request while `SECRET_KEY` is
empty; `/api` answers 401 while neither the sign-in nor `WEB_UI_PASSWORD` is set. `/healthz` stays
open either way, so a missing secret cannot roll a deploy back.

```bash
cp .env.example .env
docker compose --profile localdb up -d postgres
```

Then set in `.env`:

```
DATABASE_URL=postgresql://reli:reli@localhost:5432/reli
```

Optional: `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `LOG_LEVEL`.

### 3. Run in development

```bash
uvicorn backend.main:app --reload --port 8000
npm --prefix frontend install && npm --prefix frontend run dev   # the web view, proxying /api to :8000
```

Startup applies `alembic upgrade head`; a migration failure fails the boot. The backend serves the
web view only when `frontend/dist` exists, which the Docker build produces; in development Vite
serves it and proxies `/api`.

### 4. Run with Docker (production)

```bash
docker compose up -d
```

The health check is at `http://localhost:8000/healthz`, the MCP endpoint at
`http://localhost:8000/mcp`, which requires an `Authorization: Bearer` of the OAuth JWT its
authorization server mints, and the web view
at `http://localhost:8000/`, which presents Google sign-in (`curl -u ":$WEB_UI_PASSWORD"` still
reads `/api` directly). The image builds the frontend bundle in a node stage and serves it from the
same container. Data lives in Postgres, not on the container filesystem.

## Testing

```bash
./scripts/gates.sh              # setup, lint, typecheck, test, build
./scripts/gates.sh test         # pytest, with coverage
./scripts/gates.sh lint         # ruff check + ruff format --check
./scripts/gates.sh typecheck    # mypy
./scripts/gates.sh frontend     # npm lint, typecheck, build and the Playwright screenshot tests
```

The suite starts a throwaway `postgres:16-alpine` via testcontainers and runs the baseline migration
against it, so it needs a working Docker daemon. Set `RELI_TEST_DATABASE_URL` to use an existing
database instead.

`frontend` is not in the no-arg default: it needs node and a browser. CI runs it as its own job
inside the pinned Playwright container, and so must anyone regenerating the screenshots — see the
Screenshot Tests section of `CLAUDE.md`.

## Project Structure

```
backend/
  main.py              # FastAPI app — /healthz, the /api router, the MCP app at /mcp, the frontend bundle
  api.py               # the read-only /api routes the web view reads, plus the reject write and the Basic check
  mcp_server.py        # the MCP tools; every write takes an actor, no hard delete
  db_models.py         # things, relationships, journal, and the enums
  service.py           # the only write path; every mutation is journalled
  queries.py           # the indexed queries: due_for_checkin, stale, by_tag, blocked, needs_input, related, children, find_things, user_model
  config.py            # settings from the environment
  db_engine.py         # the Postgres engine and session factory
  alembic/versions/    # the v4 baseline migration
  tests/
frontend/              # the read-only web view — Vite + React + TypeScript
  src/views/           # Tree, ThingDetail, UserModel
  e2e/                 # Playwright screenshot tests, with every /api response stubbed
reference/oauth/       # pre-rebuild Google OAuth/Calendar/Gmail code — not built, not shipped
docs/                  # Vision, architecture, and design documents
docker-compose.yml     # Production deployment, plus a localdb profile for development
Dockerfile             # node stage builds frontend/dist, python stage serves it alongside the API
scripts/gates.sh       # Quality gate runner
```
