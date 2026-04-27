# Reli

Reli is a personal AI assistant that builds a structured model of who you are and uses it to be genuinely helpful. It stores knowledge as "Things" in a knowledge graph, learns your preferences and patterns over time, and proactively surfaces what matters — not just when you ask, but when you need it.

The goal is a PA that says "bring a change of clothes today, you have that event tonight" or "it's Saturday morning — your energy contract expires next month, want me to find a better deal?" — one that understands your life context, your schedule, your routines, and the right moment to act.

## How it works

Everything you tell Reli — tasks, notes, ideas, people, projects — becomes a **Thing** in your personal knowledge graph. Things are typed, linked by relationships, and enriched over time. Ask Reli to remember something, and it figures out what to create, update, or connect. Ask it a question, and it searches your graph to answer.

Reli also learns *how you operate*. Preferences like "avoids morning meetings" or "does venue-before-budget when planning events" are tracked as first-class Things with confidence levels that strengthen or decay based on your behavior.

Every message flows through a multi-stage agent pipeline:

```
User Message
    |
    v
+------------------+
| Context Agent    |  Searches your knowledge graph for relevant Things
+--------+---------+
         v
+------------------+
| Reasoning Agent  |  Decides what to create/update/link, extracts preferences
+--------+---------+
         v
+------------------+
| Validator        |  Applies changes to the database
+--------+---------+
         v
+------------------+
| Response Agent   |  Responds naturally, shaped by your learned preferences
+------------------+
```

## Vision

Reli aims to be a true personal assistant — one that models you, manages your **concerns**, and gets better over time. See the [vision document](docs/vision.md) for the full picture, including:

- **Concerns** — modular domains of life (health, finance, travel) that Reli monitors on your behalf
- **The learning flywheel** — how every interaction makes Reli smarter about you
- **The nightly sweep** — Reli's planning session: gap detection, pattern aggregation, briefings
- **MCP** — Reli as an intelligence service that any AI tool can tap into
- **Multi-channel delivery** — Telegram, Claude Code, email — the intelligence isn't tied to one UI

For how Reli compares to related projects, see [comparisons](docs/comparisons.md).

## Tech Stack

**Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic
**Frontend:** React 19, TypeScript, Vite, Tailwind CSS, Zustand
**Storage:** SQLite (data), ChromaDB (vector embeddings)
**LLM Gateway:** Requesty (OpenAI-compatible, routes to multiple providers)
**Integrations:** Google Calendar, Gmail, Google Search (all optional)
**Infrastructure:** Docker, Cloudflare Tunnel, GitHub Actions CI, Railway (staging + production deploy)

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
cd frontend && npm install --legacy-peer-deps && cd ..
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
    context: google/gemini-3.1-flash-lite-preview
    reasoning: google/gemini-3-flash-preview
    response: google/gemini-3.1-flash-lite-preview

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

```
backend/
  main.py              # FastAPI app, static file serving
  agents.py            # Multi-stage agent pipeline
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
