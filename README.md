# Reli

A conversation-driven personal information manager that learns about you through
chat. Reli stores knowledge as **Things** — a flexible entity model covering
tasks, notes, projects, ideas, goals, people, places, and more — with typed
relationships that form a personal knowledge graph.

## Key Features

- **Natural language chat** — talk to Reli like a personal assistant; it creates,
  updates, and completes Things automatically
- **Universal Thing model** — tasks, notes, projects, ideas, goals, journal
  entries, people, places, events, concepts, and references all share one schema
- **Knowledge graph** — typed relationships between Things with an interactive
  graph visualization
- **Multi-agent pipeline** — each message flows through Context → Reasoning →
  Validator → Response stages for accurate, grounded replies
- **Google integrations** — Gmail (read-only) and Google Calendar via OAuth2
- **Daily briefing** — surfaces Things with upcoming check-in dates and nightly
  sweep findings
- **Web search** — queries the web when you ask about external information
- **Vector search** — ChromaDB embeddings for semantic retrieval of relevant Things
- **Proactive surfaces** — nudges you about time-sensitive items
- **LLM flexibility** — uses [Requesty](https://requesty.ai) as an
  OpenAI-compatible gateway (any supported model), with optional local
  [Ollama](https://ollama.com) for the context agent

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Frontend | React 19, Vite, Tailwind CSS, TypeScript |
| Database | SQLite (WAL mode) |
| Vector store | ChromaDB |
| LLM gateway | Requesty (OpenAI-compatible API) |
| Auth | Google OAuth2, JWT sessions |
| Deployment | Docker (multi-stage build) |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A [Requesty](https://requesty.ai) API key (or any OpenAI-compatible provider)
- (Optional) Google OAuth credentials for login, Gmail, and Calendar

### 1. Clone and configure

```bash
git clone https://github.com/alexsiri7/reli.git
cd reli
cp .env.example .env   # if available, otherwise create .env manually
```

Create a `.env` file with at minimum:

```env
REQUESTY_API_KEY=your-requesty-api-key

# Optional: override the default model (google/gemini-2.0-flash-exp)
# MODEL_NAME=google/gemini-2.0-flash-exp

# Optional: Google OAuth (required for multi-user auth)
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...
# SECRET_KEY=a-random-secret-for-jwt-signing

# Optional: Google Calendar / Gmail
# GOOGLE_REDIRECT_URI=http://localhost:8000/api/calendar/callback
# GOOGLE_AUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# Optional: web search
# GOOGLE_SEARCH_API_KEY=...
# GOOGLE_SEARCH_CX=...

# Optional: local LLM via Ollama
# OLLAMA_MODEL=llama3
# OLLAMA_BASE_URL=http://localhost:11434
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

Reli will be available at **http://localhost:8000**. The frontend is served from
the same port — no separate dev server needed.

Data is persisted in a `./data` volume mount (SQLite database + ChromaDB
vectors).

### 3. Local development (without Docker)

```bash
# Backend
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000

# Frontend (in a separate terminal)
cd frontend
npm install --legacy-peer-deps
npm run dev
```

The frontend dev server runs on port 5173 and proxies API calls to port 8000.

## Architecture

```
User ──▶ React SPA ──▶ FastAPI ──▶ Multi-Agent Pipeline ──▶ SQLite + ChromaDB
                          │
                          ├── /api/chat      (chat pipeline)
                          ├── /api/things    (CRUD)
                          ├── /api/briefing  (daily summary)
                          ├── /api/gmail     (Gmail integration)
                          ├── /api/calendar  (Calendar integration)
                          └── /api/auth      (Google OAuth2)
```

### Chat Pipeline

Each user message passes through four stages:

1. **Context Agent** — analyzes the message and generates search parameters to
   find relevant Things, determine if web/Gmail/Calendar context is needed
2. **Reasoning Agent** — given the user's request and retrieved context, decides
   what storage changes to make (create, update, delete Things and relationships)
3. **Validator** — applies the reasoning agent's decisions to SQLite and ChromaDB
4. **Response Agent** — generates a friendly, personality-driven reply based on
   what actually changed

### Data Model

**Things** are the universal entity:

| Field | Description |
|-------|-------------|
| `title` | Display name |
| `type_hint` | Category: task, note, project, idea, goal, journal, person, place, event, concept, reference |
| `priority` | 1 (highest) to 5 (lowest) |
| `checkin_date` | When to surface in the daily briefing |
| `active` | `true` = live, `false` = completed/archived |
| `surface` | Whether to show in default views (entities default to hidden) |
| `data` | Arbitrary JSON (notes, metadata, contact info, etc.) |
| `open_questions` | Knowledge gaps the AI wants to fill |

**Relationships** connect Things with typed edges (parent-of, depends-on,
related-to, involves, etc.), forming a queryable knowledge graph.

## Project Structure

```
reli/
├── backend/
│   ├── main.py              # FastAPI app, middleware, SPA serving
│   ├── agents.py            # Multi-agent chat pipeline (Context/Reasoning/Response)
│   ├── database.py          # SQLite setup, migrations, connection management
│   ├── models.py            # Pydantic request/response schemas
│   ├── vector_store.py      # ChromaDB vector embeddings
│   ├── auth.py              # Google OAuth2 + JWT session management
│   ├── sweep.py             # Nightly sweep logic
│   ├── sweep_scheduler.py   # Background scheduler for sweeps
│   ├── web_search.py        # Google Custom Search integration
│   ├── google_calendar.py   # Calendar API client
│   └── routers/             # API route handlers
│       ├── auth.py          # Login, logout, profile
│       ├── chat.py          # Chat pipeline endpoint
│       ├── things.py        # Thing CRUD + graph
│       ├── thing_types.py   # Custom type management
│       ├── briefing.py      # Daily briefing
│       ├── gmail.py         # Gmail OAuth + messages
│       ├── calendar.py      # Calendar OAuth + events
│       ├── proactive.py     # Proactive surface suggestions
│       ├── settings.py      # Model configuration
│       └── sweep.py         # Sweep findings API
├── frontend/
│   └── src/
│       ├── App.tsx           # Main app shell
│       ├── api.ts            # API client
│       └── components/
│           ├── ChatPanel.tsx     # Chat interface
│           ├── Sidebar.tsx       # Thing list + navigation
│           ├── DetailPanel.tsx   # Thing detail view
│           ├── GraphView.tsx     # Knowledge graph visualization
│           ├── GmailPanel.tsx    # Gmail integration UI
│           ├── CalendarSection.tsx
│           ├── SettingsPanel.tsx
│           └── LoginPage.tsx
├── config.yaml              # LLM model configuration
├── docker-compose.yml
├── Dockerfile               # Multi-stage build (Node + Python)
└── pyproject.toml           # Ruff, mypy, pytest config
```

## Configuration

### LLM Models

Edit `config.yaml` to change which models power each pipeline stage:

```yaml
llm:
  base_url: https://router.requesty.ai/v1
  models:
    context: google/gemini-2.5-flash-lite     # Fast, cheap — search parameter generation
    reasoning: google/gemini-3-flash-preview   # Smarter — decides what to create/update
    response: google/gemini-2.5-flash-lite     # Fast — generates user-facing replies
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REQUESTY_API_KEY` | Yes | API key for the LLM gateway |
| `MODEL_NAME` | No | Override default model |
| `SECRET_KEY` | For auth | JWT signing secret |
| `GOOGLE_CLIENT_ID` | For auth | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | For auth | Google OAuth client secret |
| `GOOGLE_SEARCH_API_KEY` | No | Enables web search |
| `GOOGLE_SEARCH_CX` | No | Custom search engine ID |
| `OLLAMA_MODEL` | No | Local model name (e.g. `llama3`) |
| `DATA_DIR` | No | Database directory (default: `backend/`) |
| `LOG_LEVEL` | No | Logging verbosity (default: `INFO`) |

## API Documentation

With the server running, visit **http://localhost:8000/docs** for the interactive
OpenAPI (Swagger) documentation.

## License

Private repository.
