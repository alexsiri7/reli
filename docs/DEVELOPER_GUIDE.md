# Reli: Developer Guide

## Project Structure

```
reli/
├── backend/
│   ├── main.py              # FastAPI app entry point, middleware, static serving
│   ├── pipeline.py          # 4-stage agent pipeline orchestration
│   ├── context_agent.py     # Stage 1: context retrieval
│   ├── reasoning_agent.py   # Stage 2: structured decision-making
│   ├── response_agent.py    # Stage 4: natural language generation
│   ├── agents.py            # Model configuration and routing
│   ├── database.py          # SQLite schema, migrations, query helpers
│   ├── models.py            # Pydantic request/response models
│   ├── config.py            # Settings from env vars + config.yaml
│   ├── llm.py               # LiteLLM wrapper for Requesty gateway
│   ├── auth.py              # Google OAuth, JWT session management
│   ├── vector_store.py      # ChromaDB integration
│   ├── sweep.py             # Nightly sweep logic
│   ├── sweep_scheduler.py   # APScheduler background jobs
│   ├── routers/             # API route modules (one per feature)
│   └── tests/               # pytest test suite
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Root component, auth check, initial data load
│   │   ├── main.tsx         # React entry point
│   │   ├── api.ts           # apiFetch wrapper
│   │   ├── store.ts         # Zustand global state
│   │   ├── schemas.ts       # Zod validation schemas
│   │   ├── components/      # React components
│   │   ├── hooks/           # Custom React hooks
│   │   ├── offline/         # IndexedDB caching + sync engine
│   │   └── __tests__/       # Vitest test suite
│   ├── e2e/                 # Playwright visual regression tests
│   ├── package.json
│   └── vite.config.ts
├── config.yaml              # LLM model selection
├── docker-compose.yml
├── Dockerfile
└── scripts/gates.sh         # Quality gate runner
```

---

## Running Tests

### All quality gates

```bash
./scripts/gates.sh
```

This runs setup → lint → typecheck → test → build in sequence.

### Individual stages

```bash
./scripts/gates.sh test       # pytest + vitest
./scripts/gates.sh lint       # ruff (Python) + eslint (JS)
./scripts/gates.sh typecheck  # mypy (Python) + tsc (TypeScript)
```

### Backend tests only

```bash
cd backend && pytest tests/ -v
# With coverage report
pytest tests/ --cov=backend --cov-report=term-missing
```

### Frontend tests only

```bash
cd frontend && npm run test -- --run
```

### Visual regression tests (Playwright)

Screenshot tests ensure UI quality across breakpoints. Run after any UI change:

```bash
cd frontend
npm run test:screenshots           # Run tests
npm run test:screenshots:update    # Update snapshots after intentional UI changes
```

After updating snapshots, **visually inspect every updated PNG** in `frontend/e2e/visual.spec.ts-snapshots/` before committing.

---

## Adding a New API Endpoint

1. Create (or update) a router in `backend/routers/{feature}.py`:

```python
from fastapi import APIRouter, Depends
from ..auth import require_user

router = APIRouter(prefix="/my-feature", tags=["my-feature"])

@router.get("", summary="List my features")
def list_my_features(user_id: str = Depends(require_user)) -> list[dict]:
    # user_id is the Google sub ID — use it to scope all DB queries
    return []
```

2. Register the router in `backend/main.py`:

```python
from .routers import my_feature
# ...
app.include_router(my_feature.router, prefix="/api", dependencies=_api_deps)
```

3. Define Pydantic models in `backend/models.py` for request/response types.

4. Add tests in `backend/tests/test_my_feature.py`.

---

## Adding a New Frontend Component

1. Create `frontend/src/components/MyComponent.tsx`

2. Use the Zustand store for shared state:

```typescript
import { useStore } from '../store'

function MyComponent() {
  const things = useStore(s => s.things)
  // ...
}
```

3. Call the API via `apiFetch`:

```typescript
import { apiFetch } from '../api'

const data = await apiFetch('/api/my-feature')
```

4. Validate API responses with Zod schemas from `schemas.ts`:

```typescript
import { ThingSchema } from '../schemas'

const thing = ThingSchema.parse(raw)
```

5. Add tests in `frontend/src/__tests__/MyComponent.test.tsx`.

---

## Database Migrations

All schema changes must be additive. The migration pattern lives in `backend/database.py`.

1. Add a migration function:

```python
def _migrate_add_my_column(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(things)")}
    if "my_column" not in cols:
        conn.execute("ALTER TABLE things ADD COLUMN my_column TEXT")
```

2. Call it in `init_db()`:

```python
def init_db() -> None:
    with db() as conn:
        # existing migrations...
        _migrate_add_my_column(conn)
```

3. **Test on a copy first:** `cp data/reli.db /tmp/reli-test.db` and run the migration against the copy.

**Never use** `DROP TABLE` or `DROP COLUMN` without a data migration plan.

---

## Modifying the Agent Pipeline

The pipeline is orchestrated in `backend/pipeline.py`. Each stage is implemented in its own file:

| File | Stage | What to change |
|------|-------|---------------|
| `context_agent.py` | Stage 1 | How Things are retrieved (queries, filters) |
| `reasoning_agent.py` | Stage 2 | What changes the agent can make, the JSON schema |
| `response_agent.py` | Stage 4 | How changes are explained to the user |

After changing pipeline logic, run the backend test suite:

```bash
cd backend && pytest tests/ -v -k "pipeline or chat"
```

Monitor costs after changes: `GET /api/chat/stats/today`

---

## LLM Model Selection

Models are configured in `config.yaml`. To test a different model:

```bash
REQUESTY_REASONING_MODEL=anthropic/claude-3-5-sonnet uvicorn backend.main:app --reload
```

To make it permanent, update `config.yaml`. To allow per-user override, use `PUT /api/settings`.

To add pricing for a new model, update the pricing dict in `backend/agents.py`.

---

## Debugging

### Backend verbose logging

```bash
LOG_LEVEL=DEBUG uvicorn backend.main:app --reload
```

### Inspect the database

```bash
sqlite3 backend/reli.db
.schema things
SELECT * FROM things LIMIT 5;
```

### Inspect the vector store

```bash
python -c "
from backend.vector_store import get_chroma_client
c = get_chroma_client()
col = c.get_or_create_collection('things')
print('Count:', col.count())
"
```

### Monitor API requests

Open browser DevTools → Network tab → filter by `/api/`.

The Zustand store state is in `window.localStorage` under `reli-store`.

---

## GitHub Issue Linking

PRs must reference the GitHub issue they contribute to. Include in the PR body:

- `Fixes #N` — if the PR fully completes the issue
- `Part of #N` — if the PR is partial progress

Current feature issues: https://github.com/alexsiri7/reli/issues

---

## Common Tasks

### Re-index vector embeddings after model change

```bash
curl -X POST http://localhost:8000/api/things/reindex \
  -H "Cookie: reli_session=<your-session>"
```

### Add a new user setting

1. Add the key to `VALID_KEYS` in `backend/routers/settings.py`
2. Read it with `GET /api/settings/user?key=<key>`
3. Write it with `PUT /api/settings/user { "key": "...", "value": "..." }`

### Trigger a sweep run manually

```bash
curl -X POST http://localhost:8000/api/sweep/run \
  -H "Cookie: reli_session=<your-session>"
```
