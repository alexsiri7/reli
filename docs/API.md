# Reli `/api` Reference — the web view's read surface

`/api` exists for the frontend. It mirrors the query layer and nothing more: every write into the
graph goes over MCP ([mcp-design.md](mcp-design.md)), with the single exception listed below.
Every route sits behind HTTP Basic with `WEB_UI_PASSWORD` as the password and any username; an
unset password answers 401 to everything. The one exception is `/api/auth/`, Google's sign-in
redirect for the MCP connector, which is not part of this surface (it lives in `backend/auth.py`,
see [mcp-design.md](mcp-design.md) §3) and is listed below only so its exemption is on record. The
routes and their response models are in `backend/api.py`, the TypeScript mirror is
`frontend/src/api.ts`, and the contract is proven by `backend/tests/test_api.py`.

## Routes

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/api/things?parent=` | `TreeLevel` | One level of the `ChildOf` tree: the children of `parent`, or the top level when omitted. The top level is the active Things nothing claims as a child, minus the user-model tags (`#User`, `#Preference`, `#Observation`). Most important first; `has_children` says whether expanding a row shows anything. |
| GET | `/api/things/{thing_id}` | `ThingDetail` | One Thing and every edge touching it. 404 when absent. `direction` is resolved relative to the requested Thing. |
| GET | `/api/things/{thing_id}/history?limit=` | `HistoryOut` | The newest `limit` journal entries (1–1000, default 200), oldest first within that window. Only entries recorded against the Thing itself — relating and unrelating are journalled against the relationship, so edge changes do not appear. An unknown id answers an empty history, not a 404. |
| GET | `/api/user-model?scope=` | `UserModelOut` | Every preference with its evidence. Rejected preferences are **always** included, so the view can make a wrong one spottable. A preference with no evidence or a blank scope never appears. |
| POST | `/api/preferences/{preference_id}/reject` | `PreferenceOut` | **The only write.** Tags the preference `#Rejected` and journals it as `Actor.USER`. Rejecting twice is a 200 that changes nothing. 404 for a missing id or a Thing that is not tagged `#Preference`. |
| GET | `/api/auth/google/callback` | redirect | **Not the web view's.** Where Google sends the browser after the MCP connector's sign-in; exempt from Basic because it lands in a fresh browser. Answers a 302 to the connector, or 400 for an unknown `state`. |
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
