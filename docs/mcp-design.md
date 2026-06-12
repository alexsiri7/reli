# Reli MCP Server: Technical Design

## 1. Overview

Reli exposes its personal knowledge graph via the Model Context Protocol (MCP). The MCP server provides shared knowledge and PA intelligence as a service to any MCP-capable client (Claude Desktop, IDE extensions, custom agents).

The core architecture decision is **client does the reasoning**: the MCP server provides tools and prompt resources, but the calling agent decides what to invoke, when, and how to combine results. Reli's MCP layer is a thin wrapper over the same shared tool implementations used by the internal reasoning agent.

## 2. Transports

### Streamable HTTP (primary)

The production transport. Mounted at `/mcp` inside the FastAPI app via `create_mcp_asgi_app()`.

```python
from backend.mcp_server import create_mcp_asgi_app
app.mount("/mcp", create_mcp_asgi_app(settings.MCP_API_TOKEN))
```

The server sets `streamable_http_path="/"` because FastAPI handles the `/mcp` prefix at the mount level.

### stdio (legacy)

For local clients that connect over standard input/output:

```bash
python -m backend.mcp_server
```

Useful for development and clients that do not support HTTP transport.

## 3. Authentication

The `_TokenAuthMiddleware` ASGI middleware enforces authentication on all `/mcp` requests. It supports two token forms:

### Static API token

Set the `MCP_API_TOKEN` environment variable. Clients send it as a Bearer token. Compared using `secrets.compare_digest` to prevent timing attacks. The resolved user ID comes from `_resolve_api_token_user()`.

### JWT (OAuth flow)

Tokens issued by the OAuth 2.1 flow (see section 10). Validated via `jwt.decode(provided, SECRET_KEY, algorithms=["HS256"], audience="mcp")`. The token must include `aud: "mcp"`. The `sub` claim is extracted as the user ID.

### Dev mode

If neither `MCP_API_TOKEN` nor `SECRET_KEY` is configured, all requests pass without authentication. This allows local development without token setup.

### User ID propagation

The authenticated user ID is stored in a `contextvars.ContextVar` named `_current_user_id`, set by the middleware and read by each tool function via `_user_id()`. This ensures all tool calls operate on the correct user's data.

## 4. DNS Rebinding Protection

Enabled via `TransportSecuritySettings(enable_dns_rebinding_protection=True)`.

Allowed hosts:

| Pattern | Purpose |
|---------|---------|
| `127.0.0.1:*` | Local development |
| `localhost:*` | Local development |
| `[::1]:*` | IPv6 loopback |
| `_RELI_HOST` | Production host (derived from `RELI_BASE_URL` or `GOOGLE_AUTH_REDIRECT_URI`) |

The production host is derived at module load time: first from `RELI_BASE_URL` (stripped of scheme), falling back to the host portion of `GOOGLE_AUTH_REDIRECT_URI`.

## 5. Tool Catalog

All tools are thin wrappers over `backend/tools.py` (the shared tool layer). Pattern: `@mcp.tool()` function calls `shared_tools.foo(..., user_id=_user_id())`.

### Context and Search

| Tool | Description |
|------|-------------|
| `fetch_context` | Multi-query vector similarity search with optional ID fetching and type filtering |
| `get_thing` | Get a single Thing by ID with all relationships |
| `search_things` | Keyword search (SQL LIKE) across titles, types, data, and relationships |

### CRUD

| Tool | Description |
|------|-------------|
| `create_thing` | Create a new Thing with title, type, data, importance, checkin date |
| `update_thing` | Partial update of any Thing fields (only provided fields change) |
| `delete_thing` | Soft-delete: sets `active=false` (data is preserved) |
| `merge_things` | Merge two Things into one, transferring relationships and data |

### Relationships

| Tool | Description |
|------|-------------|
| `list_relationships` | List all relationships where a Thing is source or target |
| `create_relationship` | Create a typed edge between two Things |
| `delete_relationship` | Delete a relationship by ID |

### Intelligence

| Tool | Description |
|------|-------------|
| `get_briefing` | Daily briefing with checkin-due items and sweep findings |
| `get_open_questions` | Things with unresolved knowledge gaps, ordered by importance |
| `get_user_profile` | User's anchor Thing with resolved relationships |
| `get_preferences` | All active preference Things with pattern arrays |
| `update_preference` | Replace the patterns array on a preference Thing |
| `get_conflicts` | Detect blockers, schedule overlaps, and deadline conflicts |
| `get_mutations` | Query the mutations journal for audit/rollback |
| `schedule_task` | Schedule autonomous future work (remind, check, sweep_concern, custom) |
| `chat_history` | Search across conversation sessions |

### Reasoning-as-a-service

| Tool | Description |
|------|-------------|
| `reli_think` | Analyze natural language and return structured CRUD instructions |

## 6. Prompt Resources

Prompt resources expose full agent system prompts from `backend/prompts/*.md`. Clients can adopt these personas to operate as Reli agents.

| Name | Source File | Description |
|------|-------------|-------------|
| `context-agent` | `backend/prompts/context-agent.md` | Search for relevant Things given a user message (read-only) |
| `reasoning-agent` | `backend/prompts/reasoning-agent.md` | Decide what storage changes are needed |
| `response-agent` | `backend/prompts/response-agent.md` | Produce the final user-facing reply (no tools needed) |
| `context-refinement-agent` | `backend/prompts/context-refinement-agent.md` | Decide if more context searches are needed |
| `thing-schema` | `backend/prompts/thing-schema.md` | Complete data model reference for Things and Relationships |
| `pa-behavior` | `backend/prompts/pa-behavior.md` | Core PA behavior instructions for calling agents |

## 7. Shared Tools Pattern

MCP tools do not contain business logic. They delegate to `backend/tools.py`:

```python
@mcp.tool()
def create_thing(title: str, ...) -> dict[str, Any]:
    return shared_tools.create_thing(title=title, ..., user_id=_user_id())
```

This ensures identical behavior between MCP access and the internal reasoning agent.

Notable implementation details:

- `delete_thing` is a soft delete: calls `shared_tools.update_thing(thing_id=thing_id, active=False, user_id=_user_id())`
- `get_thing` enriches the response with relationships by calling both `shared_tools.get_thing` and `shared_tools.list_relationships`
- `reli_think` is the only async tool; it delegates to `backend.reasoning_agent.run_think_agent`
- JSON parameters (data, open_questions, patterns) are serialized to JSON strings before passing to shared tools

## 8. Mutations Journal

All MCP write operations are logged to the `McpMutationRecord` table as an append-only audit trail.

Each record captures:
- The operation performed (create, update, delete, merge)
- Before and after state snapshots
- The user who performed the mutation
- Timestamp

The journal is queryable via the `get_mutations` tool:

```python
get_mutations(thing_id=None, limit=50)
```

- Filter by `thing_id` to see changes to a specific Thing
- Returns entries newest-first, up to `limit` (max 200)

## 9. Key Design Principles

1. **Client does the reasoning** — the MCP server exposes tools and data; the calling agent decides what to do with them.
2. **Thin wrapper over shared tools** — no business logic in the MCP layer; `backend/tools.py` is the single source of truth.
3. **Soft delete via MCP** — `delete_thing` marks inactive rather than destroying data. MCP clients cannot permanently delete.
4. **Single user first** — token authentication resolves to a single user. No row-level security; multi-user deferred to post-Supabase migration.
5. **Mutations journal for audit/rollback** — every write is logged with before/after snapshots, enabling audit trails and future undo support.

## 10. OAuth 2.1

The OAuth 2.1 flow for MCP client authentication is implemented in `backend/routers/mcp_oauth.py`. It follows the MCP Authorization specification and implements:

| Endpoint | RFC | Purpose |
|----------|-----|---------|
| `GET /.well-known/oauth-protected-resource` | RFC 9728 | Protected resource metadata discovery |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 | Authorization server metadata |
| `GET /oauth/authorize` | — | Redirect to Google, then back with auth code |
| `POST /oauth/token` | — | Exchange auth code + PKCE verifier for JWT. Confidential clients (`token_endpoint_auth_method != "none"`) must include `client_secret`; public clients use PKCE only. |
| `POST /oauth/register` | RFC 7591 | Dynamic client registration |

The flow delegates authentication to Google (the existing auth provider) and issues JWTs that the MCP middleware validates on subsequent requests.
