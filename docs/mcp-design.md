# MCP Server Design

## Principle

Reli's MCP server exposes the knowledge graph and PA behavior as tools, resources, and prompts. The calling agent does its own reasoning — Reli provides the data, schema, and instructions, not an extra LLM call.

## Transport

Stdio for local use (Claude Code), Streamable HTTP for remote clients (Telegram bot, other agents). Both served from the same FastAPI app.

## Authentication

Token-based. A single user generates an API token in the Reli web UI. The MCP server validates it per-request. Multi-user (RLS, Supabase) is deferred — this is single-user for now.

## Tools

### Thing operations

```
search_things(query, type_hint?, active_only?, limit?)
  → Vector + text search. Returns matching Things with relationships.
  Uses the existing hybrid search (SQLite LIKE + ChromaDB vector).

get_thing(id)
  → Fetch a single Thing by ID, including its relationships.

create_thing(title, type_hint?, data?, priority?, parent_id?, open_questions?)
  → Create a new Thing. Returns the created Thing.

update_thing(id, title?, type_hint?, data?, priority?, active?, open_questions?)
  → Partial update. Only provided fields change. Returns updated Thing.

delete_thing(id)
  → Soft delete (set active=false) rather than hard delete, for safety.
  MCP clients should not be able to permanently destroy data.

merge_things(keep_id, remove_id)
  → Merge two Things. Transfers relationships, merges data, records history.
```

### Relationship operations

```
list_relationships(thing_id)
  → All relationships where the Thing is source or target.

create_relationship(from_thing_id, to_thing_id, relationship_type, metadata?)
  → Link two Things with a typed relationship.

delete_relationship(id)
  → Remove a relationship link.
```

### User profile

```
get_user_profile()
  → The user's anchor Thing with all relationships. This is "who am I"
  for the calling agent — always load this at session start.
```

### Sweep / briefing

```
get_briefing()
  → Latest sweep output: approaching dates, stale Things, open questions,
  pattern observations. Structured JSON, not prose.

get_open_questions(limit?)
  → Things that have unresolved open_questions. Useful for proactive
  question-asking by the calling agent.
```

### Preferences

```
get_preferences()
  → All Things with type_hint='preference'. The calling agent uses
  these to shape its behavior (communication style, proactivity, etc).

update_preference(id, patterns)
  → Update confidence levels, add observations to a preference Thing.
```

## Prompts

MCP prompt resources that teach the calling agent how to be a PA. These are static templates loaded at session start.

### `pa-behavior`

The core PA prompt. Covers:
- When a user mentions people/places/events, check if they exist as Things — create if not, link relationships
- When updating Things, preserve existing data — don't overwrite fields the user didn't mention
- Proactively surface relevant Things when context matches
- How to interpret type_hints, relationship types, and the Things data model
- How to read and apply preference Things to shape communication style

### `thing-schema`

Reference for the Thing data model:
- Field descriptions and valid values
- Type hints and what they mean (task, person, project, preference, event, etc.)
- Relationship types and conventions
- How open_questions work
- How preference confidence tracking works (emerging → moderate → strong)

### `concerns-guide`

How concerns work:
- What a concern is (a domain of life Reli monitors)
- How to check in on a concern's Things
- When to create new Things vs update existing ones for a concern
- How to surface concern-related questions naturally in conversation

## Resources

MCP resources for dynamic data the client might want to read.

### `reli://things/recent`
Recently updated Things (last 7 days). Useful for warm-start context.

### `reli://briefing/latest`
The latest sweep briefing as structured JSON.

### `reli://preferences`
All active preference Things. The client loads these at session start.

## Implementation notes

### Wrapping the existing API

The MCP server is a thin layer over the existing FastAPI routes. Each MCP tool calls the same functions that the REST API uses — `_row_to_thing()`, the search logic, the merge logic, etc. No duplicate business logic.

### Soft delete for safety

MCP `delete_thing` sets `active=false` rather than deleting the row. The web UI can still hard-delete. This protects against MCP clients (especially lesser models) accidentally destroying data.

### Mutations journal (future)

Every MCP write operation (create, update, delete, merge, create_relationship) should log to an append-only journal with: timestamp, client_id, operation, thing_id, before/after snapshot. The sweep can then audit and flag suspicious patterns. Not in v1, but the tool signatures should be designed to make this easy to add.

## Phases

### Phase 1: Core tools (CRUD + search)
- MCP server scaffold (stdio transport)
- search_things, get_thing, create_thing, update_thing, delete_thing
- list_relationships, create_relationship, delete_relationship
- get_user_profile
- Token auth

### Phase 2: PA prompts
- pa-behavior prompt resource
- thing-schema prompt resource
- Test with Claude Code as calling agent

### Phase 3: Preferences + briefing
- get_preferences, update_preference tools
- get_briefing, get_open_questions tools
- reli://preferences and reli://briefing/latest resources

### Phase 4: Concerns + resources
- concerns-guide prompt resource
- reli://things/recent resource
- Streamable HTTP transport for remote clients

### Phase 5: Mutations journal
- Append-only log for all write operations
- Sweep audit phase for MCP mutations
