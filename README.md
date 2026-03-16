# Reli

Reli is a personal AI information manager that learns about you through conversation. It stores knowledge as "Things" in a graph and uses a multi-agent pipeline to understand context, reason about changes, and respond naturally.

Everything you tell Reli — tasks, notes, ideas, people, projects — becomes a Thing in your personal knowledge graph. Ask Reli to remember something, and it figures out what to create or update. Ask it a question, and it searches your graph to answer.

## Architecture

Reli processes every message through a 4-stage agent pipeline:

```
User Message
    │
    ▼
┌─────────────────┐
│ Context Agent    │  Decides what to search (generates queries)
│ (The Librarian)  │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Reasoning Agent  │  Decides what to change (outputs structured JSON)
│ (The Brain)      │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Validator        │  Applies changes to the database
│ (Logic/Code)     │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Response Agent   │  Explains what happened in natural language
│ (The Voice)      │
└─────────────────┘
```

Each agent stage uses a model optimized for its task. All LLM calls route through [Requesty](https://requesty.ai), an OpenAI-compatible gateway that handles model routing and cost tracking. Models are configured in `config.yaml`.

## Tech Stack

**Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic
**Frontend:** React 19, TypeScript, Vite, Tailwind CSS, Zustand
**Storage:** SQLite (data), ChromaDB (vector embeddings)
**LLM Gateway:** Requesty (OpenAI-compatible, routes to multiple providers)
**Integrations:** Google Calendar, Gmail, Google Search (all optional)
**Infrastructure:** Docker, Cloudflare Tunnel, GitHub Actions CI

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
- `SECRET_KEY` — JWT signing key

Optional:
- `OLLAMA_MODEL` — Use a local LLM for the context agent (reduces API costs)
- `GOOGLE_SEARCH_API_KEY` / `GOOGLE_SEARCH_CX` — Enable web search in chat
- `CLOUDFLARE_TUNNEL_TOKEN` — Expose the app publicly via Cloudflare Tunnel

### 3. Run in development

```bash
# Start the backend (serves frontend from frontend/dist/ if built)
uvicorn backend.main:app --reload --port 8000

# In another terminal, start the frontend dev server
cd frontend && npm run dev
```

The frontend dev server proxies `/api` requests to the backend on port 8000.

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
    context: google/gemini-2.5-flash-lite    # Fast query generation
    reasoning: google/gemini-3-flash-preview  # Structured decision-making
    response: google/gemini-2.5-flash-lite    # Natural language replies

embedding:
  model: text-embedding-3-small  # Vector embeddings for search
```

Models can also be overridden via environment variables (`REQUESTY_MODEL`, `REQUESTY_REASONING_MODEL`, `REQUESTY_RESPONSE_MODEL`).

## Testing

```bash
# All gates (setup, lint, typecheck, test, build)
./scripts/gates.sh

# Individual stages
./scripts/gates.sh test          # Backend (pytest) + Frontend (vitest)
./scripts/gates.sh lint          # Backend (ruff) + Frontend (eslint)
./scripts/gates.sh typecheck     # Backend (mypy) + Frontend (tsc)
```

## Project Structure

```
backend/
  main.py              # FastAPI app, static file serving
  agents.py            # 4-stage agent pipeline
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
    sweep.py           # /api/sweep — nightly cleanup
frontend/
  src/                 # React app (TypeScript)
  package.json
config.yaml            # Model configuration
docker-compose.yml     # Production deployment
Dockerfile             # Multi-stage build (Node + Python)
scripts/gates.sh       # Quality gate runner
```
