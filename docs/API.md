# Reli `/api` Reference — the web view's read surface

`/api` exists for the frontend. It mirrors the query layer and nothing more: every write into the
graph goes over MCP ([mcp-design.md](mcp-design.md)), with the single exception listed below.
Every route admits a request by the `reli_session` cookie the Google sign-in sets or by HTTP Basic
with `WEB_UI_PASSWORD` as the password and any username; with neither presented the answer is a
401 whose body names both, and with neither configured every request is a 401. The one exception
is `/api/auth/`, the sign-in itself — `GET /api/auth/google`, Google's callback for both the web
view and the MCP connector, `GET /api/auth/me` and `POST /api/auth/logout` — which lives in
`backend/auth.py` (see [mcp-design.md](mcp-design.md) §3 and CLAUDE.md's *Google sign-in*) and is
listed below only so its exemption is on record. The routes and their response models are in
`backend/api.py`, the TypeScript mirror is `frontend/src/api.ts`, and the contract is proven by
`backend/tests/test_api.py`.

## Routes

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/things?parent=` | `TreeLevel` | One level of the `ChildOf` tree: the children of `parent`, or the top level when omitted. The top level is the active Things nothing claims as a child, minus the user-model tags (`#User`, `#Preference`, `#Observation`). Most important first; `has_children` says whether expanding a row shows anything. |
| GET | `/api/things/{thing_id}` | `ThingDetail` | One Thing and every edge touching it. 404 when absent. `direction` is resolved relative to the requested Thing. |
| GET | `/api/things/{thing_id}/history?limit=` | `HistoryOut` | The newest `limit` journal entries (1–1000, default 200), oldest first within that window. Only entries recorded against the Thing itself — relating and unrelating are journalled against the relationship, so edge changes do not appear. An unknown id answers an empty history, not a 404. |
| GET | `/api/user-model?scope=` | `UserModelOut` | Every preference with its evidence. Rejected preferences are **always** included, so the view can make a wrong one spottable. A preference with no evidence or a blank scope never appears. |
| POST | `/api/preferences/{preference_id}/reject` | `PreferenceOut` | **The only write.** Tags the preference `#Rejected` and journals it as `Actor.USER`. Rejecting twice is a 200 that changes nothing. 404 for a missing id or a Thing that is not tagged `#Preference`. |
| GET | `/api/auth/google` | `{auth_url}` | Where the sign-in view sends the browser. 501 naming each empty sign-in setting. Public. |
| GET | `/api/auth/google/callback` | redirect | Where Google sends the browser back, for the web view and the MCP connector alike; public because it lands in a browser with no session yet. A web sign-in answers a 302 to `/` with the `reli_session` cookie, or to `/?error=invite_only` / `/?error=cancelled`; an MCP sign-in a 302 to the connector. 400 for an unknown `state`, 502 naming the human step when Google refuses the exchange. |
| GET | `/api/auth/me` | `{email}` | The view's "am I signed in" probe: the cookie's email, or 401 whose detail says whether to sign in or which setting is missing. Public. |
| POST | `/api/auth/logout` | 204 | Deletes the cookie. There is no revocation list. Public. |
| any | `/api/{anything else}` | — | 404 JSON, never the SPA fallback. |

`GET /healthz` is unauthenticated and answers `{"status": "ok", "service": "reli"}`.

## Response models

```jsonc
// NeighbourOut — the far end of an edge, or a piece of evidence
{ "id": "uuid", "title": "string", "tags": ["string"] }

// ThingSummary — one row of the tree
{
  "id": "uuid", "title": "string", "tags": ["string"], "priority": 0.0,
  "active": true, "checkin_date": "2026-09-11" | null, "has_children": false
}

// TreeLevel
{ "things": [ThingSummary] }

// ThingOut — a whole Thing
{
  "id": "uuid", "title": "string", "description": "string" | null,
  "notes": { "slug": "markdown" }, "tags": ["string"], "urls": { "name": "url" },
  "checkin_date": "2026-09-11" | null, "priority": 0.0, "active": true,
  "created_at": "datetime", "updated_at": "datetime"
}

// RelationshipOut — one edge, with its direction relative to the requested Thing
{
  "id": "uuid", "relationship_type": "ChildOf" | "Blocks" | "RelatedTo" | "EvidenceFor" | "References",
  "direction": "outgoing" | "incoming", "context": "string" | null,
  "created_at": "datetime", "other": NeighbourOut
}

// ThingDetail
{ "thing": ThingOut, "relationships": [RelationshipOut] }

// JournalEntryOut — one journalled mutation
{
  "id": 1, "occurred_at": "datetime",
  "actor": "user" | "claude_interactive" | "claude_scheduled",
  "operation": "create" | "update" | "delete" | "relate" | "unrelate",
  "entity_type": "thing" | "relationship", "entity_id": "uuid",
  "before": { ... } | null, "after": { ... } | null
}

// HistoryOut — `total` is how many entries exist; `truncated` is true when older ones were left out
{ "entries": [JournalEntryOut], "total": 0, "truncated": false }

// PreferenceOut — `evidence_count` is the strength; there is no score
{
  "thing": ThingOut, "scope": "string" | null, "rejected": false,
  "evidence": [NeighbourOut], "evidence_count": 0
}

// UserModelOut
{ "scope": "string" | null, "preferences": [PreferenceOut] }
```

The models are stated explicitly in `backend/api.py` rather than returning the database records, so
a new column is not silently a new API field.
