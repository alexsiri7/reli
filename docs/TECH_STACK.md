# Reli Tech Stack

## Architecture Overview

Reli is a multi-agent AI Personal Assistant with a React SPA frontend, FastAPI
backend, and cost-optimized LLM routing through Requesty.

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  React SPA      │────▶│  FastAPI Backend  │────▶│  Requesty       │
│  (Vite + TS)    │     │  (Python 3.12)   │     │  (LLM Gateway)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                              │    │
                    ┌─────────┘    └─────────┐
                    ▼                        ▼
              ┌──────────┐           ┌──────────────┐
              │  SQLite  │           │  ChromaDB    │
              │  (data)  │           │  (vectors)   │
              └──────────┘           └──────────────┘
```

## Backend

| Component | Technology | Details |
|-----------|-----------|---------|
| Framework | FastAPI 0.111+ | Async Python web framework |
| Runtime | Python 3.12 | Docker base: `python:3.12-slim` |
| Web Server | Uvicorn | ASGI server |
| Database | SQLite | WAL mode, at `/app/data/reli.db` (volume-mounted) |
| Vector Store | ChromaDB 0.5+ | Persistent, at `backend/chroma_db/` |
| Embeddings | text-embedding-3-small | Via Requesty; fallback: Ollama nomic-embed-text |
| Validation | Pydantic 2.7+ | Request/response models |
| HTTP Client | httpx 0.27+ | Async HTTP |
| Google APIs | google-api-python-client 2.127+ | Calendar, Gmail |
| OAuth | google-auth-oauthlib 1.2+ | Google OAuth2 flow |

### Multi-Agent Chat Pipeline

Reli uses a 4-stage agent pipeline, each stage using a different model
optimized for its task:

| Stage | Agent | Model | Purpose |
|-------|-------|-------|---------|
| 1 | Context | gpt-4o-mini | Fast query generation for search |
| 2 | Reasoning | gpt-4o | Structured JSON decision-making |
| 3 | Validator | (code) | Apply changes to SQLite |
| 4 | Response | claude-sonnet-4 | Natural language response |

All LLM calls route through **Requesty** (`router.requesty.ai/v1`), an
OpenAI-compatible gateway that handles model routing and cost tracking.

## Frontend

| Component | Technology | Details |
|-----------|-----------|---------|
| Framework | React 19.2 | Latest React |
| Language | TypeScript 5.9 | Strict mode |
| Build Tool | Vite 8.0 | ESM-based, proxies `/api` to backend |
| State | Zustand 5.0 | Lightweight observable store |
| Styling | Tailwind CSS 4.2 | Via Vite plugin |
| Date Utils | date-fns 4.1 | Date formatting |

### Testing

| Tool | Purpose |
|------|---------|
| Vitest 4.1 | Unit tests (jsdom environment) |
| Testing Library | React component testing |
| Playwright 1.58 | E2E visual regression tests |
| ESLint 9.39 | Code quality with React hooks plugin |

## Infrastructure

### Containerization
- **Docker** — Single service via Docker Compose
- **Base image**: `python:3.12-slim`
- **Volumes**: `./data:/app/data` (SQLite persists across rebuilds)
- **Restart policy**: `unless-stopped`
- **Port**: `127.0.0.1:8000` (local only, tunneled via Cloudflare)

### CI/CD (GitHub Actions)
- **Backend tests**: pytest on Python 3.11
- **Frontend tests**: Vitest + build on Node 20
- **Deploy**: Tailscale VPN → SSH → git pull + rebuild
- **Branch protection**: main requires Backend + Frontend checks

### Networking
- **Cloudflare Tunnel** — Public access via `CLOUDFLARE_TUNNEL_TOKEN`
- **Tailscale VPN** — CI deploy access to `100.120.193.82`

### Planned: Docker Registry Deploy (re-noc)
- Build image in CI → push to ghcr.io → pull on server
- Tagged with commit SHA for instant rollback
- Server never builds — what CI tests is what deploys

## External Services

| Service | Purpose | Auth |
|---------|---------|------|
| Requesty | LLM gateway (multi-model routing) | API key |
| Google Calendar | Read + write calendar access (create/update events) | OAuth2 (calendar.events) |
| Gmail | Read-only email access | OAuth2 (gmail.readonly) |
| Google Search | Web search capability | API key + Custom Search CX |
| Cloudflare | Tunnel for public access | Tunnel token |
| Tailscale | VPN for CI deploy | Auth key |

## Database Schema

### things
Core entity table — everything is a Thing (tasks, notes, projects, people).
```
id, title, type_hint, parent_id, checkin_date, priority, active, data, created_at, updated_at
```

### chat_history
Conversation persistence with applied changes and cost tracking.
```
id, session_id, role, content, applied_changes, cost_usd, prompt_tokens, completion_tokens, model, timestamp
```

### chat_sessions
Named chat sessions; each session is a container for messages in `chat_history`. The `origin` field tags sessions seeded from a briefing (`'morning_briefing'`, `'weekly_review'`, or `null` for ad-hoc).
```
id, user_id, title, origin, created_at, last_active_at
```

### google_tokens
OAuth token storage (single-row table).
```
id, access_token, refresh_token, token_uri, client_id, client_secret, expiry, scopes
```

## Backup Strategy

- **Local**: Every 6 hours to `/mnt/steam-fast/backups/reli/` (7-day rotation)
- **Cloud**: Synced to Google Drive via rclone (`gdrive:backups/gas-town/reli/`)
- **Script**: `/home/asiri/gt/mayor/scripts/backup-dbs.sh`
