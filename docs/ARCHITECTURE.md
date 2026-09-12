# Reli: System Architecture

What the shipped v4 system is, derived from the code. The *why* is in [vision.md](vision.md); this
document does not restate it.

## 1. Overview

Reli is a deterministic data service: storage, indexed queries and an append-only journal, with no
model inside it. Every judgement happens in Claude, reached over MCP. One FastAPI container serves
three surfaces (`backend/main.py`):

```
Claude session (claude.ai, interactive or scheduled)
        │  MCP over streamable HTTP, Authorization: Bearer <OAuth JWT>
        ▼
   /mcp ──────────────┐
                      │        ┌──────────────┐
Browser               │        │              │──── Postgres (things, relationships, journal)
        │  reli_session cookie or Basic       │
        ▼             ├───────▶│   FastAPI    │
   /  and  /api ──────┘        │   (reli)     │──── GET only ──▶ Gmail API, Calendar API
                               │              │                  (the three Google tools)
Deploy pipeline ──▶ /healthz ─▶│              │
   (unauthenticated)           └──────────────┘
```

`/mcp` is the only path that writes. `/` and `/api` read, with one exception (§8). `/healthz`
answers `{"status": "ok", "service": "reli"}` to anyone.

## 2. Data model

Three tables, defined in `backend/db_models.py` and created by the single migration
`backend/alembic/versions/v4_baseline_things_relationships_journal.py`.

**`things`** — the universal unit. `id` (UUID), `title`, `description`, `notes` (JSONB, slug →
markdown), `tags` (JSONB list), `urls` (JSONB, name → URL), `checkin_date`, `priority` (float,
higher sorts first), `active`, `created_at`, `updated_at`. There is no type column and no
`parent_id`: what a Thing *is* lives in its tags and its edges.

**`relationships`** — a directed edge: `source_thing_id`, `target_thing_id`, `relationship_type`,
`context`, `created_at`. The type is one of the five `RelationshipType` values, enforced by a
`CHECK` constraint, and each type declares its own reading of source and target:

| Type | Direction |
|---|---|
| `ChildOf` | source is the **parent**, target the child — hierarchy is this edge and nothing else |
| `Blocks` | source is the **blocked** Thing, target is what blocks it |
| `EvidenceFor` | source is the evidence, target is what it supports |
| `RelatedTo` | unpinned, except that `user_model` reads anchor → preference (§5) |
| `References` | unpinned; no query depends on it |

**`journal`** — one row per mutation of the other two tables: `occurred_at`, `actor`, `operation`,
`entity_type`, `entity_id`, `before`, `after`. `actor` is `user`, `claude_interactive` or
`claude_scheduled` (`Actor`); `operation` is `create`, `update`, `delete`, `relate` or `unrelate`
(`Operation`). The `journal_no_mutate` and `journal_no_truncate` triggers in the migration reject
`UPDATE`, `DELETE` and `TRUNCATE`, which is why `lifespan` in `backend/main.py` runs
`alembic upgrade head` at startup with no `create_all` fallback — a schema built from ORM metadata
would be a silently mutable journal.

Indexes: btree on `things.title`, `checkin_date`, `active` and `updated_at`; GIN on `things.tags`;
btree on both relationship endpoints and the type; btree on `journal.occurred_at` and `entity_id`.

## 3. Write path

`backend/service.py` is the only module that constructs or mutates a `ThingRecord` or
`RelationshipRecord`; `backend/tests/test_architecture.py` fails the build if anything else does.
Every public function writes its row and its journal entry in one transaction:

- `create_thing`, `update_thing` — one `create` / `update` entry with before and after snapshots.
- `delete_thing` — the foreign keys are `ON DELETE RESTRICT`, so each edge is unrelated first: a
  Thing with N edges produces N `unrelate` entries and then the `delete`. Not exposed over MCP.
- `relate`, `unrelate` — journalled against the relationship, not the Things it joins.
- `get_or_create_user_anchor`, `record_preference`, `add_preference_evidence`,
  `reject_preference` — the user model (§5), built from the same primitives.

## 4. Queries

`backend/queries.py` answers questions with an index, never a search and never a model:

- `due_for_checkin` — active Things whose `checkin_date` has arrived, most important first.
- `stale` — active Things untouched since a given moment, longest untouched first.
- `by_tag` — Things carrying any (or all) of a set of tags.
- `blocked` — Things whose `Blocks` target is still active.
- `needs_input` — active Things tagged `#NeedsInput`, most important first, capped with a total so
  a decision cannot silently fall off the list.
- `related` — the neighbourhood of a Thing within N hops, following edges in both directions.
- `children` — the targets of a Thing's `ChildOf` edges.
- `tree_level` — one level of the `ChildOf` tree with a live child count per row, for the web view.
- `relationships_for`, `things_by_id` — the edges on a Thing and a batch of Things by id.
- `find_things` — Things matching every filter given: tags, active, check-in window, priority
  range. A filter, not a search: there is no text matching anywhere in Reli.
- `history` — the newest N journal entries for one entity, with the total so a capped answer cannot
  pass for a whole one.
- `user_model`, `evidence_for` — the preferences and the evidence behind each (§5).

## 5. The user model

A single Thing tagged `#User` at the fixed id `USER_ANCHOR_ID` anchors every preference. A
preference is its own Thing tagged `#Preference`, carrying `notes["scope"]`, reached by a
`RelatedTo` edge running anchor → preference. Its evidence is the set of `EvidenceFor` edges
pointing at it from other Things; strength is the count of those edges, and there is no confidence
value anywhere. Because an edge can only point at a Thing, a journal entry becomes evidence once a
Thing tagged `#Observation` carrying `notes["journal_entry_id"]` stands for it. Rejecting a
preference adds the `#Rejected` tag and journals it; the preference stays readable and is not
re-derived. `queries.user_model` drops any preference with no evidence or a blank scope, so an
evidence-less preference cannot pass for a recorded one.

The tags and the anchor id are constants in `backend/db_models.py`, read by both the write path
and the read path so the two cannot drift. Rationale: [vision.md §5](vision.md#5-the-user-model).

## 6. MCP surface

`backend/mcp_server.py` is the only way into the graph: twenty tools, four prompts and two
resources, each a thin wrapper over `service`, `queries` or `prompts`. Every writing tool
takes a required `actor` (`claude_interactive` or `claude_scheduled`); there is no hard delete;
the endpoint sits behind a JWT from the OAuth 2.1 authorization server in
`backend/mcp_oauth.py`. The catalogue is in [mcp-design.md](mcp-design.md).

## 7. No third-party data integration

Reli reaches Google to sign a user in and for nothing else. `backend/google_login.py` is the only
module that reads the Google credential (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) and the only
one that reaches Google at all; nothing it handles is persisted anywhere.

#1488 deleted the Calendar and Gmail readers that used to live here. A session connected to `/mcp`
already carries its own connectors, so a check-in is settled by that session looking at the user's
own calendar and mail and writing what it concluded into the graph — Reli holds no parallel
integration and no data-access credential.

## 8. The web view

`frontend/` is a Vite + React + TypeScript bundle with three views in `frontend/src/views/` —
`Tree`, `ThingDetail` and `UserModel` — consuming the `/api` routes in `backend/api.py`
([API.md](API.md)). It reads; the single write is `POST /api/preferences/{id}/reject`, attributed
to `Actor.USER` because the user performed it, which is the only place that actor is used. The
bundle is built in the Dockerfile's `frontend-build` stage and served by `api.mount_frontend`,
which `backend/main.py` calls **last** because its fallback answers every unmatched path. Without a
`frontend/dist` the API still serves and the view is simply absent.

## 9. Access control

- `/mcp` — `_BearerTokenMiddleware` in `backend/mcp_server.py` requires an `Authorization: Bearer`
  of an `aud="mcp"` JWT that the OAuth 2.1 authorization server in `backend/mcp_oauth.py` minted
  after a Google sign-in (`SECRET_KEY`, `ALLOWED_EMAILS`). Its discovery, registration and token
  endpoints (`/.well-known/*`, `/oauth/*`) and Google's callback (`/api/auth/google/callback`) are
  public by design: a client reaches them before it holds any credential.
- `/api` — `_WebViewAuthMiddleware` in `backend/api.py` requires the `reli_session` cookie: an
  `aud="web"` JWT the Google sign-in in `backend/auth.py` sets after the allowlist check, and the
  only credential, since #1471 retired the HTTP Basic password that used to sit beside it. One path
  is public: `/api/auth/` — the sign-in, its callback, `me` and `logout` — because it is how a
  browser gets a session. #1484 removed the unauthenticated `GET /api/heartbeats` that used to stand
  beside it, and the GitHub Actions watchdog it was there for.
- `/` — the bundle is public: it is the sign-in view, and static code from a public repository.
- `/healthz` — exempt from both.

An empty secret never opens its surface: `/mcp` without `SECRET_KEY`, and `/api` without the Google
sign-in, answer 401 to every request and log a warning at startup, while `/healthz` stays green so a
missing secret cannot roll a deploy back. There is no dev-mode
bypass. The MCP app's DNS-rebinding protection is off because the service is reached through a
Cloudflare tunnel; that is safe only because the bearer header is mandatory and a cross-origin page
cannot set one; the two decisions are coupled.

## 10. Scheduled Claude

Nothing runs on a schedule inside Reli. The resolution pass, the learning pass and the morning
conversation are Claude scheduled tasks on the same MCP connection as an interactive session,
distinguished only by the `claude_scheduled` actor in the journal. Their prompts are the three
files under [`prompts/scheduled/`](../prompts/scheduled/README.md) (#1413). Each task keeps one
`#ScheduledTask` Thing whose `checkin_date` it pushes to tomorrow at the end of every run, so a
missed run is a due Thing every session sees; the resolution pass hands the morning conversation a
`#Briefing` Thing; the learning pass reads the journal through `journal_since`, filtered to the
actors a person was present for. Nothing outside a session watches the passes: #1484 removed the
GitHub Actions watchdog, because a public-repo runner may not read the graph. Design:
[vision.md §4.3](vision.md#43-scheduled-claude--the-proactive-half).

## 11. Infrastructure

| Piece | Where | What |
|---|---|---|
| Image | `Dockerfile` | `node:22-slim` stage builds `frontend/dist`; `python:3.12-slim` stage runs `uv sync --frozen --no-dev`, drops to the non-root `reli` user, serves with uvicorn on `$PORT` (default 8000); healthcheck polls `/healthz` |
| Production compose | `docker-compose.yml` | service `reli` on `127.0.0.1:8000`; a `localdb` profile adds a `postgres:16-alpine` for development, never started in production |
| Staging compose | `docker-compose.staging.yml` | `reli-staging` on port 8001 with its own Postgres, configured by `STAGING_DATABASE_URL` and `STAGING_POSTGRES_PASSWORD` |
| CI | `.github/workflows/ci.yml` | Lint & Typecheck, Test, Frontend (inside the pinned Playwright container), Build Docker image — pushed to GHCR on `main`, keeping the last three SHA tags |
| Deploy | `.github/workflows/staging-pipeline.yml` | on a green `main` CI run: Railway staging → health wait → Railway production |
| Public access | Cloudflare Tunnel | host infrastructure, pointed at `http://reli:8000`; not read by the app |
| Errors | `backend/sentry.py` | optional; an empty `SENTRY_DSN` disables it |

Runbooks: [ROLLBACK.md](ROLLBACK.md), [RAILWAY_TOKEN_ROTATION_742.md](RAILWAY_TOKEN_ROTATION_742.md),
[DEPLOYMENT_SECRETS.md](../DEPLOYMENT_SECRETS.md).
