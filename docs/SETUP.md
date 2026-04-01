# Reli: Setup & Deployment

## Prerequisites

- Python 3.11+ (3.12 recommended)
- Node.js 20+
- Docker & Docker Compose (for production)
- A [Requesty](https://requesty.ai) API key (for LLM calls)
- Google OAuth credentials (for login)

---

## Local Development

### 1. Clone and install dependencies

```bash
git clone https://github.com/alexsiri7/reli.git
cd reli

# Backend
pip install -r backend/requirements.txt

# Frontend (note: --legacy-peer-deps required due to peer dependency conflict)
npm --prefix frontend install --legacy-peer-deps
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Required: LLM gateway
REQUESTY_API_KEY=your_key_here
REQUESTY_BASE_URL=https://router.requesty.ai/v1

# Required: Google OAuth (for login)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Required: JWT signing key (any random secret)
SECRET_KEY=change-me-to-a-random-secret

# Optional: Local LLM (reduces API costs)
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434

# Optional: Web search in chat
GOOGLE_SEARCH_API_KEY=...
GOOGLE_SEARCH_CX=...

# Optional: Public tunnel
CLOUDFLARE_TUNNEL_TOKEN=...
```

### 3. Run the development servers

```bash
# Terminal 1: Backend (auto-reload on file changes)
uvicorn backend.main:app --reload --port 8000

# Terminal 2: Frontend (proxies /api to backend)
cd frontend && npm run dev
```

- Frontend: `http://localhost:5173`
- Backend/API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`

---

## Model Configuration

`config.yaml` controls which LLM model is used for each pipeline stage:

```yaml
llm:
  base_url: https://router.requesty.ai/v1
  models:
    context: google/gemini-3.1-flash-lite-preview    # Stage 1: query generation (fast/cheap)
    reasoning: google/gemini-3-flash-preview         # Stage 2: structured decisions
    response: google/gemini-3.1-flash-lite-preview    # Stage 4: natural language replies

embedding:
  model: text-embedding-3-small
```

Override per-environment via env vars:
- `REQUESTY_MODEL` — overrides all three model stages
- `REQUESTY_REASONING_MODEL` — overrides reasoning stage only
- `REQUESTY_RESPONSE_MODEL` — overrides response stage only

---

## Docker Production Deployment

### Quick start

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`. Data persists in `./data/` via a volume mount.

### What `docker compose` does

- Builds a multi-stage image: Node 22 builds the React frontend, then Python 3.12 runs the backend
- Mounts `./data:/app/data` so SQLite survives container rebuilds
- Runs as non-root user (`reli:reli`, uid 1000)
- Restarts `unless-stopped`

### Manual build and run

```bash
# Build image
docker build -t reli:latest .

# Run with required env vars
docker run -d \
  -p 127.0.0.1:8000:8000 \
  -v ./data:/app/data \
  -e REQUESTY_API_KEY=... \
  -e GOOGLE_CLIENT_ID=... \
  -e GOOGLE_CLIENT_SECRET=... \
  -e SECRET_KEY=... \
  --restart unless-stopped \
  reli:latest
```

### After code changes

The container must be rebuilt after merging code changes:

```bash
cd /path/to/reli
git pull
npm --prefix frontend install --legacy-peer-deps
npm --prefix frontend run build
docker compose build && docker compose up -d
```

---

## Data Safety

Both data stores contain production data. Handle with care.

### SQLite (`data/reli.db`)

- **Never delete or recreate the database file.** The `./data` directory is volume-mounted — the DB persists across container rebuilds.
- **Schema changes must be additive** (`ALTER TABLE`, `CREATE TABLE IF NOT EXISTS`). See `backend/database.py` for the migration pattern.
- **Never use destructive DDL** (`DROP TABLE`, `DROP COLUMN`) without a data migration plan.

### ChromaDB (`backend/chroma_db/`)

- **Never delete the `chroma_db/` directory.** It contains vector embeddings that are expensive to regenerate.
- To rebuild embeddings after deletion: `POST /api/things/reindex`

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REQUESTY_API_KEY` | Yes | — | Requesty LLM gateway key |
| `REQUESTY_BASE_URL` | No | `https://router.requesty.ai/v1` | LLM gateway base URL |
| `GOOGLE_CLIENT_ID` | Yes | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | — | Google OAuth client secret |
| `SECRET_KEY` | Yes | — | JWT signing secret |
| `DATA_DIR` | No | `backend/` | Directory for `reli.db` |
| `LOG_LEVEL` | No | `INFO` | Log verbosity: DEBUG, INFO, WARNING |
| `OLLAMA_MODEL` | No | — | Local model for context agent |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `GOOGLE_SEARCH_API_KEY` | No | — | Google Custom Search API key |
| `GOOGLE_SEARCH_CX` | No | — | Google Custom Search engine ID |
| `CLOUDFLARE_TUNNEL_TOKEN` | No | — | Cloudflare Tunnel token for public access |
| `REQUESTY_MODEL` | No | — | Override model for all pipeline stages |
| `REQUESTY_REASONING_MODEL` | No | — | Override model for reasoning stage |
| `REQUESTY_RESPONSE_MODEL` | No | — | Override model for response stage |

---

## CI/CD

GitHub Actions runs on every push:

1. **Backend tests** — pytest on Python 3.11, coverage ≥ 70%
2. **Frontend tests** — vitest + build on Node 20
3. **Type checking** — mypy (backend) + tsc (frontend)
4. **Deploy** — SSH to server via Tailscale VPN, `git pull + rebuild`

Branch protection on `main` requires all checks to pass.
