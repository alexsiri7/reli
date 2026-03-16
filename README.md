# Reli

A multi-agent AI personal assistant with conversation-driven knowledge management. Reli uses a universal "Thing" model to store and connect tasks, notes, projects, people, and any other entity through natural language chat.

## Tech Stack

**Backend:** Python 3.12, FastAPI, SQLite (WAL mode), ChromaDB (vector search), Requesty LLM gateway (OpenAI-compatible)

**Frontend:** React 19, TypeScript, Vite, Zustand, Tailwind CSS

**Infrastructure:** Docker, Docker Compose, Uvicorn

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
```

Required variables:

| Variable | Purpose |
|----------|---------|
| `REQUESTY_API_KEY` | LLM gateway API key |
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret |
| `SECRET_KEY` | JWT signing key (auto-generated if unset) |

Optional: `GOOGLE_SEARCH_API_KEY`/`GOOGLE_SEARCH_CX` (web search), `OLLAMA_MODEL` (local LLM to reduce API costs).

### 2. Run with Docker (recommended)

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`. Data persists in the `./data` volume (SQLite DB + ChromaDB embeddings).

### 3. Local development

```bash
make install   # Install Python + frontend dependencies
make dev       # Start backend (uvicorn) + frontend (vite) dev servers
```

### Quality gates

```bash
./scripts/gates.sh setup      # Install dependencies
./scripts/gates.sh typecheck   # mypy
./scripts/gates.sh lint        # ruff
./scripts/gates.sh test        # pytest + vitest
./scripts/gates.sh build       # Docker build
```

## Architecture

### Multi-Agent Chat Pipeline

Every chat message flows through a 4-stage pipeline defined in `backend/agents.py`:

1. **Context Agent** ("Librarian") — Generates search parameters for RAG retrieval. Decides what to look up in Things, Gmail, Calendar, and web search.

2. **Retrieval** — Executes vector search (ChromaDB) and SQL full-text search against the Things database. Optionally queries Gmail, Calendar, and web search.

3. **Reasoning Agent** ("Brain") — Analyzes retrieved context and decides what storage changes to make (create/update/delete Things, create relationships). Outputs structured JSON.

4. **Validator** — Applies the Reasoning Agent's changes to SQLite and updates ChromaDB embeddings. No LLM calls.

5. **Response Agent** ("Voice") — Generates the natural language reply based on what actually changed in the database.

Each agent's LLM model is independently configurable via per-user settings.

### Universal Thing Model

Everything is a **Thing**: tasks, notes, projects, people, places, ideas, events, concepts. Things have:

- `title`, `type_hint`, `priority`, `active` status
- `checkin_date` for proactive surfacing (birthdays, deadlines)
- `data` (JSON) for flexible structured content
- `parent_id` for hierarchical nesting
- `surface` level: tracked (sidebar) vs entity (graph only)

Things connect to each other through typed, directional **Relationships** stored in `thing_relationships`, forming a knowledge graph visualized in the frontend.

### Per-User Settings

Multi-user support via Google OAuth2. Each user can configure:

- Custom API keys (Requesty, OpenAI)
- LLM model selection per agent stage (context, reasoning, response)
- Embedding model and chat context window size

Settings are stored in the `user_settings` table (key-value per user).

## Project Structure

```
backend/
├── main.py              # FastAPI app, middleware, route registration
├── agents.py            # Multi-agent chat pipeline
├── database.py          # SQLite schema, migrations, init
├── config.py            # Pydantic Settings (env config)
├── vector_store.py      # ChromaDB integration
├── auth.py              # Google OAuth2, JWT sessions
├── models.py            # Pydantic request/response models
├── sweep.py             # Nightly sweep (stale items, insights)
└── routers/
    ├── auth.py          # Login/logout, user profile
    ├── things.py        # Thing CRUD, search, graph
    ├── thing_types.py   # Custom Thing Types
    ├── chat.py          # Chat endpoint, history
    ├── briefing.py      # Daily briefing
    ├── settings.py      # Per-user settings
    ├── gmail.py         # Gmail OAuth + search
    ├── calendar.py      # Calendar OAuth + events
    ├── proactive.py     # Time-relevant surfacing
    └── sweep.py         # Run nightly sweep
frontend/
├── App.tsx              # Root layout
├── store.ts             # Zustand global state
├── api.ts               # API client
└── components/
    ├── ChatPanel.tsx     # Chat interface
    ├── Sidebar.tsx       # Thing list, search, briefing
    ├── DetailPanel.tsx   # Thing details + edit
    ├── GraphView.tsx     # Knowledge graph visualization
    ├── SettingsPanel.tsx # User settings
    └── LoginPage.tsx     # OAuth login
```

## API Overview

All endpoints require authentication via JWT session cookie (`reli_session`) except `/api/auth/*`.

| Group | Prefix | Key Endpoints |
|-------|--------|---------------|
| Auth | `/api/auth` | Google OAuth2 login/logout, user profile |
| Things | `/api/things` | CRUD, full-text + vector search, graph query, relationships |
| Chat | `/api/chat` | Send message (multi-agent pipeline), history, usage stats |
| Briefing | `/api/briefing` | Daily briefing with checkin-due Things + sweep findings |
| Settings | `/api/settings` | Per-user config (API keys, models), available model list |
| Gmail | `/api/gmail` | OAuth connect, message search, thread view |
| Calendar | `/api/calendar` | OAuth connect, upcoming events |
| Proactive | `/api/proactive` | Things with approaching dates |
| Sweep | `/api/sweep` | Trigger nightly analysis |
| Health | `/healthz`, `/api/health` | Basic + detailed health checks |

## Database

SQLite with WAL mode at `$DATA_DIR/reli.db` (defaults to `backend/` locally, `/app/data` in Docker). Schema migrations are additive — see `backend/database.py`.

ChromaDB stores vector embeddings in `backend/chroma_db/`. Both are persistent and must not be deleted.
