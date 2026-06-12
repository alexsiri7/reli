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
| DELETE | `/api/things/merge-history/{record_id}` | Delete a merge history record |
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
| POST | `/api/chat/sessions` | Create a named chat session |
| GET | `/api/chat/sessions` | List chat sessions (most-recent first) |
| GET | `/api/chat/history/{session_id}` | Get paginated chat history |
| DELETE | `/api/chat/history/{session_id}` | Clear chat history for a session |
| POST | `/api/chat/migrate-session` | Move history to a new session ID |
| POST | `/api/chat/append-message` | Manually append a message to history |
| GET | `/api/chat/stats/today` | Today's usage stats (tokens, cost) |

**`POST /api/chat/sessions` request:**
```json
{
  "title": "string (default: 'New chat', max 500 chars)",
  "origin": "string | null (max 100 chars, e.g. 'morning_briefing', 'weekly_review')"
}
```

**`POST /api/chat/sessions` / `GET /api/chat/sessions` item shape:**
```json
{
  "id": "string",
  "title": "string",
  "origin": "string | null",
  "created_at": "ISO datetime",
  "last_active_at": "ISO datetime"
}
```

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

**`SweepFinding` shape:**

| Field | Type | Values |
|-------|------|--------|
| `id` | string | UUID |
| `thing_id` | string \| null | Related Thing ID, if any |
| `finding_type` | string | `"llm_insight"` (default); operator-suppressed types (`lifestyle_wellness`, `location_suggestion`, `unverified_context`) are excluded from the response by default |
| `message` | string | Human-readable finding text |
| `priority` | int | 0=critical … 3=low |
| `dismissed` | bool | Whether the user dismissed it |
| `dismissed_reason` | string \| null | Why it was auto-dismissed: `"linked_thing_inactive"`, `"expired"`, `"context_changed"`, or null if dismissed by the user |
| `expires_at` | string \| null | ISO timestamp or null |

**`LearnedPreference` shape:**

| Field | Type | Values |
|-------|------|--------|
| `id` | string | Thing ID |
| `title` | string | Preference description |
| `confidence_label` | string | `"emerging"`, `"moderate"`, `"strong"` |

**`GET /api/briefing/morning` response shape (`MorningBriefingContent`):**

| Field | Type | Description |
|-------|------|-------------|
| `summary` | string | Narrative summary for the day |
| `priorities` | MorningBriefingItem[] | High-priority items |
| `overdue` | MorningBriefingItem[] | Overdue items |
| `blockers` | MorningBriefingItem[] | Blocking items |
| `findings` | MorningBriefingFinding[] | Active sweep findings |
| `actions_taken` | SweepAction[] | Autonomous actions taken by the sweep in the past 24 hours |
| `stats` | object | Per-type counts |

**`SweepAction` shape:**

| Field | Type | Values |
|-------|------|--------|
| `id` | string | Prefixed UUID (`sa-…`) |
| `action_type` | string | `"merge"`, `"close"`, `"dismiss"` |
| `description` | string | Human-readable e.g. "Merged 'Buy milk' into 'Groceries'" |
| `confidence` | float | 0.0–1.0; displayed as Emerging / Moderate / Strong |
| `thing_id` | string \| null | Primary Thing involved |
| `secondary_thing_id` | string \| null | Secondary Thing (e.g. removed item in a merge) |
| `created_at` | string | ISO 8601 UTC timestamp |

---

## Google Calendar (`/api/calendar`)

Read + write calendar integration. Events can be created and updated via the
reasoning agent tools (`calendar_create_event`, `calendar_update_event`); the
REST endpoints below cover status, OAuth, and event listing only.

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
| POST | `/api/sweep/dependencies` | Detect implicit dependencies between Things via LLM |
| POST | `/api/sweep/research` | Proactive research: fetch external data for Things with open questions |

**`POST /api/sweep/research` response:**
```json
{
  "things_researched": 3,
  "findings_created": 3,
  "lookups_executed": 3,
  "findings": [
    {
      "id": "sf-abc12345",
      "thing_id": "t-...",
      "thing_title": "Book flights to Tokyo",
      "action": "web_search",
      "query": "Tokyo flight prices April 2026",
      "results_count": 5,
      "message": "Research for 'Book flights to Tokyo': ..."
    }
  ],
  "usage": { "input_tokens": 120, "output_tokens": 45 }
}
```

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
  "context_model": "google/gemini-2.5-flash-lite",
  "reasoning_model": "google/gemini-3-flash-preview",
  "response_model": "google/gemini-2.5-flash-lite"
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

## GDPR (`/api/gdpr`)

Data portability and right-to-erasure endpoints.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/gdpr/export` | Export all user data as structured JSON |
| DELETE | `/api/gdpr/delete-all` | Permanently delete all user data and clear session |

### `GET /api/gdpr/export`

Returns a JSON object with all data stored for the authenticated user. Sensitive fields are
replaced with `"[REDACTED]"`:
- `settings[].value` where `key` is `requesty_api_key` or `openai_api_key`
- `google_tokens[].access_token`, `.refresh_token`, `.client_secret`
- `mcp_refresh_tokens[].refresh_token` (omitted entirely — it's a secret)
- `mcp_auth_codes[].auth_code` and `.code_challenge` (omitted — secrets)
- `gmail_oauth_state.state` (omitted — CSRF secret)
- `embeddings` omits raw vector bytes (only `thing_id`, `content`, `updated_at` included)

**Response top-level keys:** `user`, `things`, `relationships`, `embeddings`, `chat_sessions`,
`chat_history`, `conversation_summaries`, `settings`, `google_tokens`, `sweep_findings`,
`sweep_runs`, `sweep_actions`, `usage_log`, `morning_briefings`, `weekly_briefings`,
`connection_suggestions`, `nudge_dismissals`, `nudge_suppressions`, `merge_history`,
`thing_types`, `scheduled_tasks`, `mcp_refresh_tokens`, `mcp_auth_codes`, `gmail_oauth_state`

### `DELETE /api/gdpr/delete-all`

**Irreversible.** Permanently deletes all data owned by the authenticated user across every
table listed above, plus the user record itself. Also clears the `reli_session` cookie, ending
the session immediately. Returns `200 OK` on success.

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
