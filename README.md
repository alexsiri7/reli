# Reli

Reli is the memory and the obligations layer that lets Claude act as a complete personal assistant. It stores knowledge as "Things" in a knowledge graph, tracks what needs checking and when, and learns how you actually operate — so that any Claude session, interactive or scheduled, starts already knowing.

The goal is a PA that says "bring a change of clothes today, you have that event tonight" or "it's Saturday morning — your energy contract expires next month, want me to find a better deal?" — one that understands your life context, your schedule, your routines, and the right moment to act.

## How it works

Everything you tell Reli — tasks, notes, ideas, people, projects — becomes a **Thing** in your personal knowledge graph. Things are tagged, linked by typed relationships, and enriched over time. Each Thing can carry a check-in date, which is Reli's record that something needs verifying by then.

Reli also learns *how you operate*. Preferences like "avoids morning meetings" or "does venue-before-budget when planning events" are tracked as first-class Things, each linked to the specific evidence that produced it.

Reli does no reasoning of its own. Every judgement call happens in Claude — interactively over MCP, or in a scheduled session — and Reli stores the result, journalling every mutation with the actor that made it.

## Vision

Reli is a service, not a product: MCP + claude.ai + scheduled tasks together should cover the whole job of a PA. See the [vision document](docs/vision.md) for the full picture — the layers, the user model, what check-ins mean, and what is deliberately not being built.

For how Reli compares to related projects, see [comparisons](docs/comparisons.md).

## Tech Stack

**Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic
**Frontend:** React 19, TypeScript, Vite, Tailwind CSS — a read-only view over the graph
**Storage:** Postgres
**Interface:** MCP — every write goes through an MCP client; there is no public API
**Integrations:** Google Calendar, Gmail
**Infrastructure:** Docker, Cloudflare Tunnel, GitHub Actions CI, Railway (staging + production deploy)

The rebuild is in progress: the sections below still document the application currently in this tree.

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker and Docker Compose (for production)

### 1. Clone and install dependencies

```bash
git clone https://github.com/alexsiri7/reli.git
cd reli

# Backend
pip install -r backend/requirements.txt

# Frontend
cd frontend && npm ci --legacy-peer-deps && cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `REQUESTY_API_KEY` — Get from [requesty.ai](https://requesty.ai)
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — For Google OAuth login
- `GOOGLE_SEARCH_API_KEY` / `GOOGLE_SEARCH_CX` — Enable web search in chat
- `SECRET_KEY` — JWT signing key

Optional:
- `OLLAMA_MODEL` — Use a local LLM for the context agent (reduces API costs)
- `CLOUDFLARE_TUNNEL_TOKEN` — Expose the app publicly via Cloudflare Tunnel

### 3. Run in development

```bash
# Start the backend
uvicorn backend.main:app --reload --port 8000

# In another terminal, start the frontend dev server
cd frontend && npm run dev
```

### 4. Run with Docker (production)

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`. Data persists in `./data/` via a Docker volume mount.

## Configuration

`config.yaml` controls model selection for each pipeline stage:

```yaml
llm:
  base_url: https://router.requesty.ai/v1
  models:
    context: google/gemini-2.5-flash-lite
    reasoning: google/gemini-3-flash-preview
    response: google/gemini-2.5-flash-lite

embedding:
  model: text-embedding-3-small
```

Models can also be overridden via environment variables (`REQUESTY_MODEL`, `REQUESTY_REASONING_MODEL`, `REQUESTY_RESPONSE_MODEL`).

## Testing

```bash
./scripts/gates.sh              # All gates
./scripts/gates.sh test          # Backend (pytest) + Frontend (vitest)
./scripts/gates.sh lint          # Backend (ruff) + Frontend (eslint)
./scripts/gates.sh typecheck     # Backend (mypy) + Frontend (tsc)
```

## Project Structure

The layout below is the repository as it stands today, mid-rebuild; `docs/vision.md` describes the shape it is moving to.

```
backend/
  main.py              # FastAPI app, static file serving
  agents.py            # Agent pipeline (superseded by the rebuild)
  database.py          # SQLite schema, migrations, queries
  vector_store.py      # ChromaDB embeddings
  models.py            # Pydantic models
  config.py            # Settings from env + config.yaml
  routers/             # API route modules
    chat.py            # /api/chat — main conversation endpoint
    things.py          # /api/things — CRUD for Things
    auth.py            # /api/auth — Google OAuth
    calendar.py        # /api/calendar — Google Calendar
    gmail.py           # /api/gmail — Gmail integration
    settings.py        # /api/settings
    sweep.py           # /api/sweep — nightly analysis
frontend/
  src/                 # React app (TypeScript)
docs/                  # Vision, architecture, and design documents
config.yaml            # Model configuration
docker-compose.yml     # Production deployment
Dockerfile             # Multi-stage build (Node + Python)
scripts/gates.sh       # Quality gate runner
```
