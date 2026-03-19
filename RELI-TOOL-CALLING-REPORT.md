# Reli Tool Calling Failure Report

**Date:** 2026-03-17
**Investigator:** Mayor (automated analysis)
**Container versions:** google-adk 1.27.1, litellm 1.82.3

---

## Executive Summary

Tool calling is **completely broken** for the reasoning agent. The root cause is a
Gemini API `thought_signature` requirement that LiteLLM 1.82.3 + ADK 1.27.1 do not
handle when routing through the Requesty OpenAI-compatible proxy. Every chat message
that triggers a tool call (create_thing, update_thing, create_relationship, etc.)
will fail with a 400 error. Additionally, there are two other runtime errors
degrading the service.

---

## Error 1: thought_signature Missing on Tool Calls [CRITICAL]

**Severity:** CRITICAL -- blocks ALL tool calling, core feature is non-functional

**Error message:**
```
openai.BadRequestError: Error code: 400 - {'error': {'origin': 'provider',
  'message': 'Function call is missing a thought_signature in functionCall parts.
  This is required for tools to work correctly, and missing thought_signature may
  lead to degraded model performance. Additional data, function call
  `default_api:create_relationship`, position 2. Please refer to
  https://ai.google.dev/gemini-api/docs/thought-signatures for more details.'}}
```

**Call chain:**
```
backend/routers/chat.py:375 (event_generator)
  -> backend/pipeline.py:685 (run_stream)
  -> backend/reasoning_agent.py:799 (run_reasoning_agent)
  -> backend/context_agent.py:100 (_run_agent_for_text)
  -> google.adk.runners -> google.adk.flows.llm_flows.base_llm_flow
  -> google.adk.models.lite_llm:2341 (generate_content_async)
  -> litellm.main:620 (acompletion)
  -> openai SDK -> Requesty -> Gemini API -> 400
```

**Analysis:**

The reasoning agent uses model `google/gemini-3-flash-preview` (a thinking model).
Gemini thinking models require "thought signatures" in tool call responses -- this
is a protocol-level requirement where the model's internal chain-of-thought must be
echoed back in subsequent requests that contain tool call results.

The problem is in the model routing path:
1. `_make_litellm_model()` in `context_agent.py` prepends `openai/` to the model
   name, creating `openai/google/gemini-3-flash-preview`
2. This routes through LiteLLM's OpenAI provider to Requesty's OpenAI-compatible API
3. Requesty forwards to the Gemini API
4. When the Gemini thinking model returns a tool call, its response includes thought
   content that must be echoed back
5. ADK's LiteLLM connector (or LiteLLM itself) strips the thought_signature when
   constructing the follow-up request with the tool result
6. Gemini rejects the request with a 400

**The model `google/gemini-3-flash-preview` is a "thinking" model.** Thinking models
require thought_signature handling that the current LiteLLM 1.82.3 + ADK 1.27.1
stack does not support when routing through an OpenAI-compatible proxy.

**Suggested fixes (in order of preference):**

1. **Switch reasoning model to a non-thinking Gemini model.** Change
   `config.yaml` reasoning model from `google/gemini-3-flash-preview` to
   `google/gemini-2.5-flash` or another model that does not require thought
   signatures. This is the fastest fix.

2. **Upgrade LiteLLM.** Check if newer LiteLLM versions (1.83+) handle
   thought_signature forwarding for Gemini models routed through OpenAI-compatible
   providers. If so, update `pyproject.toml` and rebuild.

3. **Use Gemini native provider instead of OpenAI proxy.** Instead of routing
   `openai/google/gemini-3-flash-preview` through Requesty, use LiteLLM's native
   `gemini/` prefix which handles Gemini-specific protocol features. This would
   require changing `_make_litellm_model()` in `context_agent.py` to detect
   Gemini models and route them natively rather than through `openai/` prefix.

4. **Upgrade ADK.** Check if newer google-adk versions have fixed LiteLLM thought
   signature passthrough. ADK 1.27.1 may predate the thought_signature requirement.

**Files to modify:**
- `/home/asiri/gt/reli/mayor/rig/config.yaml` (model name)
- `/home/asiri/gt/reli/mayor/rig/backend/context_agent.py` (`_make_litellm_model`)
- `/home/asiri/gt/reli/mayor/rig/pyproject.toml` (dependency versions)

---

## Error 2: ChromaDB Broken (Permission + Rust Bindings) [HIGH]

**Severity:** HIGH -- vector search is completely non-functional, falls back to
SQL LIKE queries which are much less accurate

**Error messages:**
```
2026-03-17 10:11:36,053 ERROR [backend.vector_store] ChromaDB count failed:
  Permission denied (os error 13)

2026-03-17 10:11:36,058 ERROR [backend.vector_store] ChromaDB vector_search failed:
  'RustBindingsAPI' object has no attribute 'bindings'
```

**Analysis:**

Two separate ChromaDB failures:

1. **Permission denied:** The ChromaDB persistent storage directory
   (`backend/chroma_db/`) has incorrect filesystem permissions inside the Docker
   container. The process cannot read from it.

2. **RustBindingsAPI missing 'bindings':** This is a known ChromaDB version
   incompatibility issue. The Rust-based ChromaDB backend fails to initialize
   properly, likely due to a version mismatch between the chromadb Python package
   and its compiled Rust extensions, or a corrupted installation.

**Impact:** All semantic vector search is disabled. The pipeline falls back to
SQL `LIKE` queries on thing titles, producing zero results for most queries
(as seen in logs: "SQL LIKE query matched 0 rows"). Context retrieval is severely
degraded -- the reasoning agent sees fewer relevant Things.

**Suggested fixes:**
1. Fix Docker volume permissions for `/app/backend/chroma_db/` directory
2. Rebuild the Docker image to ensure chromadb Rust bindings compile correctly
3. Check `pyproject.toml` for chromadb version pinning issues

**File:** `/home/asiri/gt/reli/mayor/rig/backend/vector_store.py`

---

## Error 3: Google Calendar API Not Enabled [MEDIUM]

**Severity:** MEDIUM -- calendar integration broken, but not a core feature

**Error message:**
```
googleapiclient.errors.HttpError: <HttpError 403 when requesting
  https://www.googleapis.com/calendar/v3/calendars/primary/events...
  returned "Google Calendar API has not been used in project 102584585211
  before or it is disabled.">
```

**Analysis:**

The Google Calendar API is not enabled in the GCP project (102584585211). The
calendar endpoint (`/api/calendar/events`) returns 500 instead of gracefully
handling this. The `fetch_upcoming_events()` function in `google_calendar.py:218`
does not catch `HttpError` exceptions -- it only checks if credentials exist but
does not handle API-level errors.

**Impact:** The `/api/calendar/events` endpoint returns 500 errors. This cascades
as an unhandled ASGI exception. However, the briefing and main chat pipeline appear
to handle calendar unavailability gracefully (the pipeline still completes).

**Suggested fixes:**
1. Enable Google Calendar API in GCP project 102584585211
2. Add try/except around the `.execute()` call in `fetch_upcoming_events()` to
   return empty list on API errors instead of crashing
3. The calendar router at `routers/calendar.py:72` should also have error handling

**Files:**
- `/home/asiri/gt/reli/mayor/rig/backend/google_calendar.py` (line 218)
- `/home/asiri/gt/reli/mayor/rig/backend/routers/calendar.py` (line 72)

---

## Error 4: Context Agent JSON Parsing Failure [LOW]

**Severity:** LOW -- has a working fallback

**Warning message:**
```
2026-03-17 10:11:35,906 WARNING [backend.context_agent] Context agent returned
  invalid JSON, falling back to message as query: ```json
```

**Analysis:**

The context agent (using `google/gemini-2.5-flash-lite`) wraps its JSON response
in markdown code fences (` ```json ... ``` `). The `run_context_agent()` function
in `context_agent.py:209` tries `json.loads(raw)` which fails because of the
backtick wrapping. It falls back to using the raw user message as the search query.

Despite `generate_content_config` requesting `response_mime_type="application/json"`,
the model (routed through `openai/` prefix to Requesty) may not honor this
constraint, or Requesty/LiteLLM may not pass the mime type hint to the provider
correctly.

**Impact:** Context retrieval uses the raw user message as search query instead of
the model's optimized search parameters. This reduces retrieval quality but does
not break the pipeline.

**Suggested fixes:**
1. Add JSON extraction logic in `context_agent.py` before `json.loads()` to strip
   markdown code fences: `raw = raw.strip().removeprefix("```json").removesuffix("```").strip()`
2. Verify that `response_mime_type` is passed through correctly by the
   `openai/` LiteLLM provider to Requesty

**File:** `/home/asiri/gt/reli/mayor/rig/backend/context_agent.py` (line 209-225)

---

## Summary Table

| # | Error | Severity | Impact | Quick Fix Available |
|---|-------|----------|--------|-------------------|
| 1 | thought_signature missing | CRITICAL | All tool calls fail, no Things created/updated | Change model in config.yaml |
| 2 | ChromaDB broken | HIGH | No vector search, degraded retrieval | Fix Docker permissions + rebuild |
| 3 | Calendar API disabled | MEDIUM | Calendar 500 errors | Enable API in GCP console |
| 4 | Context agent JSON parse | LOW | Suboptimal search queries | Strip markdown fences |

---

## Recommended Action Plan

**Immediate (fix tool calling now):**
1. Change `config.yaml` reasoning model from `google/gemini-3-flash-preview` to
   `google/gemini-2.5-flash` (non-thinking model that supports tool calling without
   thought signatures)
2. Rebuild and redeploy

**Short-term (file as beads):**
3. Fix ChromaDB permissions and Rust bindings in Docker image
4. Add JSON fence-stripping to context agent
5. Add error handling to calendar endpoint

**Medium-term:**
6. Investigate upgrading LiteLLM + ADK to versions that support Gemini thought
   signatures, enabling use of thinking models for reasoning
7. Consider using LiteLLM's native `gemini/` provider instead of `openai/` proxy
   for Gemini models
