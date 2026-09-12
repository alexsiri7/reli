# Reli MCP Server: Technical Design

## 1. Overview

`/mcp` is the only way into the graph. `backend/mcp_server.py` registers twenty tools, four
prompts and two resources, each a thin wrapper over `backend/service.py` (writes),
`backend/queries.py` (graph reads) or `backend/prompts.py` (the behaviour). No
judgement happens in that module and no model is called from it: the tools hand Claude the graph
and Claude decides what it means. Rationale: [vision.md §4.2](vision.md#42-mcp--the-only-way-in).

The server's `instructions` string tells a connected session to call `get_initial_instructions`
before anything else, then the shape of the graph (Things,
tags instead of a type column, `ChildOf` for hierarchy), which tools read and which write, the two
actor values and why they must be honest, that nothing is hard-deleted, how the user model is
structured, and that Reli holds no Calendar or Gmail integration of its own — a check-in is
settled through the connectors attached to the session (#1488).

## 2. Transport

Streamable HTTP only; there is no stdio transport. `backend/main.py` mounts the app at `/mcp` with
`streamable_http_path="/"`, because the SDK's own default of `/mcp` would serve `/mcp/mcp`. The
server is `stateless_http=True`: every tool carries its actor per call and holds no session state,
so there is nothing for a session to remember and a container restart mid-conversation is
harmless. The session manager is started in `main.lifespan`, because a mounted Starlette app's own
lifespan never runs.

DNS-rebinding protection is disabled. The SDK's default host allowlist is `127.0.0.1`/`localhost`,
which answers 421 to any request carrying a real `Host` header — and Reli is served through a
Cloudflare tunnel. This is safe only because the bearer check below makes an `Authorization`
header mandatory, which a cross-origin page cannot set; the two decisions are coupled.

## 3. Authentication

`_BearerTokenMiddleware` requires an `Authorization: Bearer` on every request and accepts one
credential: an `aud="mcp"` JWT signed with `SECRET_KEY`, read from settings per request, and minted
by the OAuth 2.1 authorization server in `backend/mcp_oauth.py` after a Google sign-in —
`/.well-known/*`, `/oauth/register`, `/oauth/authorize`, `/oauth/token`, with the callback in
`backend/auth.py`. A 401 carries an RFC 9728 `resource_metadata` pointer when a base URL is
configured, which is how a claude.ai connector finds the authorization server, and its body names
the remedy. An empty `SECRET_KEY` closes the endpoint — 401 to everything, and a warning at
startup — rather than opening it, because `/mcp` is the only write path into the graph and it is
publicly reachable. There is no dev mode. The static `MCP_API_TOKEN` that stood beside the JWT
until the owner confirmed the sign-in against a real connector was retired in #1461.

Every writing tool takes `actor: McpActor` as a required first argument, where
`McpActor = Literal[Actor.CLAUDE_INTERACTIVE, Actor.CLAUDE_SCHEDULED]`: `claude_interactive` when a
person is in the conversation, `claude_scheduled` for an unattended scheduled task. A call that
omits it fails argument validation before any tool body runs. `Actor.USER` is deliberately absent:
over MCP, `reject_preference` records the Claude session that relayed the rejection, and widening
the literal would let any MCP caller stamp a mutation as a user decision — the distinction is the
learning pass's only signal for "the user decided" against "Claude did". The one rejection
attributed to `Actor.USER` is the web view's `POST /api/preferences/{id}/reject`.

## 4. Tool catalogue

Writes — every one takes `actor`, every one is journalled by `backend/service.py`:

| Tool | Does |
|---|---|
| `create_thing` | Creates a Thing: `title`, `description`, `notes`, `tags`, `urls`, `checkin_date`, `priority`. |
| `update_thing` | Replaces the fields given — a `tags` or `notes` argument replaces the whole value, nothing is merged, and an unset field is untouched. |
| `archive_thing` | Sets `active=False`, journalled as an update. The Thing and its edges stay readable; it drops out of `due_for_checkin`, `stale`, `blocked`, `needs_input` and the default `find_things`. There is no hard delete over MCP and nothing un-archives. |
| `relate` | Links two Things with one of the five `RelationshipType` values (`ChildOf` source is the parent; `Blocks` source is the blocked Thing; `EvidenceFor` source is the evidence) and an optional `context`. |
| `unrelate` | Removes an edge by id; both Things stay. |

Reads — no `actor`:

| Tool | Does |
|---|---|
| `get_thing` | One Thing and every edge touching it, each with the id `unrelate` takes. |
| `find_things` | Things matching every filter given — `tags` (`match` any/all), `active`, a check-in window, a priority range, `limit`. A filter, not a search: there is no text matching anywhere in Reli. |
| `get_related` | The neighbourhood of a Thing within `depth` hops, following edges in both directions, optionally restricted to some `types`. |
| `due_for_checkin` | Active Things whose check-in date has arrived, as of today or `as_of`. |
| `stale` | Active Things untouched for at least `days` (default 30). |
| `blocked` | Things whose `Blocks` target is still active. |
| `needs_input` | Active Things tagged `#NeedsInput` — what only the user can settle — most important first, capped at `limit` (default 100) with `total` and `truncated`. The tag is what the prompts apply to a Thing that cannot be resolved from Calendar, Gmail or the graph. |
| `children` | The targets of a Thing's `ChildOf` edges. |
| `get_thing_history` | The Thing's newest `limit` journal entries, oldest first, with `total` and `truncated`. Edge changes are journalled against the relationship, so they do not appear here. |
| `journal_since` | Every journal entry with an id above `after_id`, across all Things and relationships, oldest first and capped at `limit`, optionally only those made by `actors`. `total` and `truncated` count under the same filters, so a caller pages by passing the last id back. The learning pass's input. |

User model — see [vision.md §5](vision.md#5-the-user-model):

| Tool | Does |
|---|---|
| `record_preference` (`actor`) | Records a preference as its own `#Preference` Thing with a `scope` and at least one evidence Thing id. Cite a `#Observation` Thing for a journal entry. |
| `add_preference_evidence` (`actor`) | Adds one more `EvidenceFor` edge; a repeat changes nothing. |
| `reject_preference` (`actor`) | Tags the preference `#Rejected` and journals it; it stays readable and is not re-derived. |
| `get_user_model` | Preferences with their evidence and `evidence_count`, optionally for one `scope`, optionally `include_rejected`. There is no confidence score. |

Behaviour — no `actor`, and it reads nothing from the graph:

| Tool | Does |
|---|---|
| `get_initial_instructions` | Returns the `capture` behaviour plus a paragraph naming the three hats as prompts to load. A prompt reaches a session only when the user picks one, so this is how the default behaviour reaches every session (#1466); the server's `instructions` tell a session to call it first. Derived from the same text as the `capture` prompt at call time, so there is no second copy to drift. |

## 5. Prompts

Four prompts, their text in `backend/prompts.py`: `capture` (the default behaviour — what is
worth a Thing, how to title and tag it, when to set a check-in date, when to relate rather than
create) and the three hats `daily-planning`, `project-planning` and `review`. Every prompt names
the two preference scopes it loads — the one for its mode, `capture`, `scheduling`, `planning` or
`review`, and `voice` beside it (#1493) — and those five labels are the scope vocabulary: a
preference is recorded under the same label a prompt loads, because `queries.user_model` matches
scope exactly. All four carry the default voice (warm, direct, unhurried — and that confidence of
manner is never confidence of fact, #1492; a `voice` preference is what moves it), the
preference-capture convention (record a preference the moment you notice it, with evidence) and
the check-in semantics (`checkin_date` is Claude's obligation to verify, not the user's
deadline), held as constants so `backend/tests/test_mcp_tools.py` can prove it.

## 6. Resources

`reli://user-model` and `reli://user-model/{scope}` serve the same JSON payload as
`get_user_model`, so a session can load its preferences as context without a tool call. Rejected
preferences are left out of both: a resource is ambient context, and what the user refused is not
what they prefer. `get_user_model(include_rejected=true)` is where they are visible.

## 7. Journal

Every write above reaches the journal through `backend/service.py` with the actor, the operation
and the before/after snapshots, in the same transaction as the row it changes. `get_thing_history`
reads it per Thing; `journal_since` reads it across Things from an id onward, by actor, which is
how the learning pass keeps `claude_scheduled` edits out of what it learns about the user.

## 8. Design principles

- **The client does the reasoning.** Reli returns data; a tool never decides what it means.
- **One write path.** Every tool that changes state calls `backend/service.py`, which journals.
- **Honest actor.** The journal's attribution is what the learning pass learns from, so a write
  cannot be attributed by default and `Actor.USER` cannot be claimed over MCP.
- **No hard delete.** `archive_thing` retires; `get_thing_history` explains.
- **No confidence anywhere.** A preference's strength is the count of its evidence.
