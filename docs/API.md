# Reli API Reference

All endpoints are prefixed with `/api`. Authentication is via `reli_session` JWT cookie (set by the OAuth flow). All endpoints except `/api/auth/*` require a valid session.

Interactive docs available at `http://localhost:8000/docs` (Swagger UI) when running locally.

---

## Authentication (`/api/auth`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/auth/google` | Redirect to Google OAuth consent screen |
| GET | `/api/auth/google/callback` | Handle OAuth callback, set `reli_session` cookie |
| GET | `/api/auth/me` | Return current user profile |
| POST | `/api/auth/logout` | Clear session cookie |

**`GET /api/auth/me` response:**
```json
{
  "id": "google-sub-id",
  "email": "user@example.com",
  "name": "Display Name",
  "picture": "https://..."
}
```

---

## Things (`/api/things`)

The core resource. Everything in Reli is a Thing.

### Listing & Search

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/things` | List Things with optional filters |
| GET | `/api/things/search?q=...` | Full-text + vector search |
| GET | `/api/things/graph` | Things as graph (nodes + edges) |
| GET | `/api/things/me` | Current user's profile Thing |

**`GET /api/things` query params:**
- `active` (bool) — filter by active status
- `type_hint` (str) — filter by type (task, note, project, etc.)
- `parent_id` (str) — filter by parent

**`GET /api/things/search` query params:**
- `q` (str, required) — search query

### CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/things/{thing_id}` | Get a single Thing |
| POST | `/api/things` | Create a Thing |
| PATCH | `/api/things/{thing_id}` | Update a Thing (partial) |
| DELETE | `/api/things/{thing_id}` | Delete a Thing |
| POST | `/api/things/reindex` | Re-embed all Things (after embedding model change) |

**Thing schema:**
```json
{
  "id": "uuid",
  "title": "string",
  "type_hint": "task|note|project|person|idea|...",
  "parent_id": "uuid|null",
  "priority": 1,
  "checkin_date": "2026-01-01T00:00:00|null",
  "active": true,
  "data": {},
  "open_questions": "string|null",
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-01-01T00:00:00"
}
```

### Relationships

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/things/{thing_id}/relationships` | List relationships for a Thing |
| POST | `/api/things/relationships` | Create a relationship |
| DELETE | `/api/things/relationships/{rel_id}` | Delete a relationship |

**Create relationship body:**
```json
{
  "from_thing_id": "uuid",
  "to_thing_id": "uuid",
  "relationship_type": "blocks|part_of|related_to|..."
}
```

### Merge & Graph Maintenance

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/things/merge-suggestions` | Detect potential duplicate Things |
| POST | `/api/things/merge` | Merge two Things into one |
| GET | `/api/things/merge-history` | List past merges |
| GET | `/api/things/relationships/orphans` | Find relationships with deleted Things |
| POST | `/api/things/relationships/cleanup` | Delete all orphaned relationships |

---

## Thing Types (`/api/thing-types`)

Custom categories for Things.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/thing-types` | List all Thing Types |
| GET | `/api/thing-types/{type_id}` | Get a single Type |
| POST | `/api/thing-types` | Create a custom Type |
| PATCH | `/api/thing-types/{type_id}` | Update a Type |
| DELETE | `/api/thing-types/{type_id}` | Delete a Type |

**ThingType schema:**
```json
{
  "id": "string",
  "name": "string",
  "icon": "🎯",
  "color": "blue"
}
```

---

## Chat & Pipeline (`/api/chat`)

The primary interface to Reli's multi-agent pipeline.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message through the pipeline |
| POST | `/api/chat/stream` | Stream a response via SSE |
| GET | `/api/chat/history/{session_id}` | Get paginated chat history |
| DELETE | `/api/chat/history/{session_id}` | Clear chat history for a session |
| POST | `/api/chat/migrate-session` | Move history to a new session ID |
| POST | `/api/chat/append-message` | Manually append a message to history |
| GET | `/api/chat/stats/today` | Today's usage stats (tokens, cost) |

**`POST /api/chat` request:**
```json
{
  "session_id": "string",
  "message": "string (max 10,000 chars)",
  "mode": "normal|planning"
}
```

**`POST /api/chat` response:**
```json
{
  "reply": "string",
  "applied_changes": {
    "created": [...],
    "updated": [...],
    "deleted": [...]
  },
  "questions_for_user": ["string"],
  "usage": {
    "total_cost_usd": 0.001,
    "prompt_tokens": 1200,
    "completion_tokens": 300
  }
}
```

**`GET /api/chat/history/{session_id}` query params:**
- `limit` (int, default 50) — messages per page
- `before_id` (int) — cursor for pagination

---

## Briefing (`/api/briefing`)

Daily briefing: check-in due Things, sweep findings, and learned preferences.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/briefing` | Get today's briefing |
| GET | `/api/briefing/morning` | Pre-generated morning briefing |
| GET | `/api/briefing/preferences` | Get briefing preferences |
| PUT | `/api/briefing/preferences` | Update briefing preferences |
| POST | `/api/briefing/findings` | Create a sweep finding |
| PATCH | `/api/briefing/findings/{finding_id}/dismiss` | Dismiss a finding |
| POST | `/api/briefing/findings/{finding_id}/snooze` | Snooze a finding |

**`GET /api/briefing` response shape:**

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Briefing date (YYYY-MM-DD) |
| `the_one_thing` | BriefingItem \| null | Highest-priority item |
| `secondary` | BriefingItem[] | Secondary priority items |
| `parking_lot` | object[] | Deferred items |
| `findings` | SweepFinding[] | Active sweep findings |
| `learned_preferences` | LearnedPreference[] | Inferred preferences (≤5), shown in "I Noticed" section |
| `total` | int | Total item count |
| `stats` | object | Per-type counts |

**`LearnedPreference` shape:**

| Field | Type | Values |
|-------|------|--------|
| `id` | string | Thing ID |
| `title` | string | Preference description |
| `confidence_label` | string | `"emerging"`, `"moderate"`, `"strong"` |

---

## Google Calendar (`/api/calendar`)

Read-only calendar integration.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/calendar/status` | Check connection status |
| GET | `/api/calendar/auth` | Start OAuth flow |
| GET | `/api/calendar/callback` | Handle OAuth callback |
| GET | `/api/calendar/events` | Fetch upcoming events |
| DELETE | `/api/calendar/disconnect` | Revoke calendar access |

**`GET /api/calendar/events` query params:**
- `days_ahead` (int, default 7)
- `max_results` (int, default 20)

---

## Gmail (`/api/gmail`)

Read-only Gmail integration.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/gmail/status` | Check connection status |
| GET | `/api/gmail/auth-url` | Get OAuth authorization URL |
| GET | `/api/gmail/callback` | Handle OAuth callback |
| DELETE | `/api/gmail/disconnect` | Revoke Gmail access |
| GET | `/api/gmail/messages` | List recent messages |
| GET | `/api/gmail/messages/{message_id}` | Read a specific message |
| GET | `/api/gmail/threads/{thread_id}` | Read a thread |

**`GET /api/gmail/messages` query params:**
- `max_results` (int, default 20)

---

## Focus (`/api/focus`)

Prioritized recommendations based on urgency, deadlines, and context.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/focus` | Get focus recommendations |

---

## Proactive (`/api/proactive`)

Things with upcoming time-relevant dates that need attention.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/proactive` | Get proactive surfaces |

---

## Connections (`/api/connections`)

Suggestions for linking semantically related Things.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/connections` | List pending connection suggestions |
| POST | `/api/connections/{suggestion_id}/accept` | Accept a suggestion (creates relationship) |
| POST | `/api/connections/{suggestion_id}/dismiss` | Dismiss a suggestion |
| POST | `/api/connections/{suggestion_id}/defer` | Defer a suggestion |

---

## Conflicts (`/api/conflicts`)

Detect scheduling and resource conflicts between Things.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conflicts` | Get conflict alerts |

---

## Staleness (`/api/staleness`)

Report on stale and neglected Things.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/staleness` | Get staleness report |

---

## Sweep (`/api/sweep`)

Background cleanup and reflection runs.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/sweep/run` | Trigger a nightly sweep run |
| GET | `/api/sweep/runs` | List sweep run history |
| POST | `/api/sweep/connections` | Trigger connection sweep |

---

## Settings (`/api/settings`)

LLM model configuration and per-user preferences.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Get current model settings |
| PUT | `/api/settings` | Update model settings |
| GET | `/api/settings/models` | List available LLM models (from Requesty) |
| GET | `/api/settings/user` | Get per-user settings |
| PUT | `/api/settings/user` | Update per-user settings |

**`PUT /api/settings` body:**
```json
{
  "context_model": "google/gemini-3.1-flash-lite-preview",
  "reasoning_model": "google/gemini-3-flash-preview",
  "response_model": "google/gemini-3.1-flash-lite-preview"
}
```

---

## Think (`/api/think`)

Reasoning-as-a-service: analyze arbitrary text and return structured JSON.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/think` | Analyze text with the reasoning agent |

---

## Feedback (`/api/feedback`)

Submit user feedback (creates a GitHub issue).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/feedback` | Submit feedback |

---

## Health & Monitoring

| Method | Path | Auth required | Description |
|--------|------|--------------|-------------|
| GET | `/healthz` | No | Simple health check |
| GET | `/api/health` | Yes | Detailed health (DB, ChromaDB, metrics) |
| GET | `/metrics` | No | Prometheus metrics |

**`GET /api/health` response:**
```json
{
  "status": "ok",
  "database": "ok",
  "vector_store": "ok",
  "version": "string"
}
```
