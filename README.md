# Reli

Reli is the memory and the obligations layer that lets Claude act as a complete personal assistant. It stores knowledge as "Things" in a knowledge graph, tracks what needs checking and when, and learns how you actually operate — so that any Claude session, interactive or scheduled, starts already knowing.

The goal is a PA that says "bring a change of clothes today, you have that event tonight" or "it's Saturday morning — your energy contract expires next month, want me to find a better deal?" — one that understands your life context, your schedule, your routines, and the right moment to act.

Reli is being rebuilt. The data layer, the MCP tools over it and the user model are what exists today; the read-only view is still ahead.

## How it works

Everything you tell Reli — tasks, notes, ideas, people, projects — becomes a **Thing** in your personal knowledge graph. Things are tagged, linked by typed relationships, and enriched over time. Each Thing can carry a check-in date, which is Reli's record that something needs verifying by then.

Reli also learns *how you operate*. Preferences like "avoids morning meetings" or "does venue-before-budget when planning events" are tracked as first-class Things, each linked to the specific evidence that produced it.

Reli does no reasoning of its own. Every judgement call happens in Claude — interactively over MCP, or in a scheduled session — and Reli stores the result, journalling every mutation with the actor that made it.

## Vision

Reli is a service, not a product: MCP + claude.ai + scheduled tasks together should cover the whole job of a PA. See the [vision document](docs/vision.md) for the full picture — the layers, the user model, what check-ins mean, and what is deliberately not being built.

For how Reli compares to related projects, see [comparisons](docs/comparisons.md).

## Tech Stack

**Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic, SQLModel
**Frontend:** a read-only view over the graph — not yet built
**Storage:** Postgres
**Interface:** MCP — every write goes through an MCP client; there is no public API
**Integrations:** Google Calendar and Gmail, read-only — `backend/google_client.py` and `backend/google_readers.py`; `reference/oauth/` holds the pre-rebuild code, not reused
**Infrastructure:** Docker, Cloudflare Tunnel, GitHub Actions CI, Railway (staging + production deploy)

Today the service is the data layer, the MCP tools over it at `/mcp` — including the read-only Calendar and Gmail readers and the user model — and a health check. The scheduled passes and the read-only view are the next issues.

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

`MCP_API_TOKEN` is the bearer token for `/mcp`. Leaving it empty does not open the endpoint: every
request gets a 401 until it is set.

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
```

Startup applies `alembic upgrade head`; a migration failure fails the boot.

### 4. Run with Docker (production)

```bash
docker compose up -d
```

The health check is at `http://localhost:8000/healthz` and the MCP endpoint at
`http://localhost:8000/mcp`, which requires `Authorization: Bearer $MCP_API_TOKEN`. Data lives in
Postgres, not on the container filesystem.

## Testing

```bash
./scripts/gates.sh              # All gates
./scripts/gates.sh test         # pytest, with coverage
./scripts/gates.sh lint         # ruff check + ruff format --check
./scripts/gates.sh typecheck    # mypy
```

The suite starts a throwaway `postgres:16-alpine` via testcontainers and runs the baseline migration
against it, so it needs a working Docker daemon. Set `RELI_TEST_DATABASE_URL` to use an existing
database instead.

## Project Structure

```
backend/
  main.py              # FastAPI app — /healthz, and the MCP app mounted at /mcp
  mcp_server.py        # the MCP tools; every write takes an actor, no hard delete
  db_models.py         # things, relationships, journal, and the enums
  service.py           # the only write path; every mutation is journalled
  queries.py           # the indexed queries: due_for_checkin, stale, by_tag, blocked, related, children, find_things, user_model
  config.py            # settings from the environment
  db_engine.py         # the Postgres engine and session factory
  alembic/versions/    # the v4 baseline migration
  tests/
reference/oauth/       # pre-rebuild Google OAuth/Calendar/Gmail code — not built, not shipped
docs/                  # Vision, architecture, and design documents
docker-compose.yml     # Production deployment, plus a localdb profile for development
Dockerfile             # Python image
scripts/gates.sh       # Quality gate runner
```
