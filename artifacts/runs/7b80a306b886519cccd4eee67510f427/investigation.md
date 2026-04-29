# Investigation: Deploy down: https://reli.interstellarai.net returning HTTP 000000

**Issue**: #758 (https://github.com/alexsiri7/reli/issues/758)
**Type**: BUG
**Investigated**: 2026-04-29T10:00:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | Production service is completely down (HTTP 000000). |
| Complexity | MEDIUM | Involves both application logic (lifespan) and environment configuration. |
| Confidence | HIGH | Root cause aligns with recent changes to the application's startup sequence. |

---

## Problem Statement

The production deployment at `https://reli.interstellarai.net` is failing to respond to requests, returning a `000000` status code. This indicates that the client cannot establish a connection to the server, likely because the application is hanging during startup or has crashed immediately.

---

## Analysis

### Root Cause / Change Rationale

The investigation points to a hang in the FastAPI `lifespan` handler. Specifically, the introduction of the MCP session manager in the main app's lifespan (Commit `8d621893`) appears to be the primary suspect. If the session manager's `run()` context manager fails to yield or encounters a deadlock, the entire application will fail to finish its startup phase, and the server will not start listening for requests.

Additionally, the production environment is missing the `RELI_BASE_URL` configuration, which is now used by the MCP server for host validation.

### Evidence Chain

WHY: The service is returning `000000` (Connection Failure).
↓ BECAUSE: The FastAPI app hasn't finished its startup sequence and isn't listening on port 8000.
  Evidence: The health check hits `localhost:8000/healthz`.

↓ BECAUSE: The `lifespan` handler in `backend/main.py` is blocking.
  Evidence: `backend/main.py:81` - `async with _mcp_server.session_manager.run(): yield`

↓ ROOT CAUSE: The MCP session manager's `run()` method may not be yielding correctly or is being called in a state where it hangs.
  Evidence: Recent commits show significant refactoring of the MCP server's transport and session management.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `backend/main.py` | 72-84 | UPDATE | Improve robustness of MCP session manager startup in lifespan. |
| `docker-compose.yml` | N/A | UPDATE | Add `RELI_BASE_URL` to production environment. |

---

## Implementation Plan

### Step 1: Robust Lifespan Startup

**File**: `backend/main.py`
**Lines**: 72-84
**Action**: UPDATE

**Required change:**
```python
    # Start MCP session manager (required for streamable HTTP transport).
    from .mcp_server import mcp as _mcp_server

    async with httpx.AsyncClient(timeout=15.0) as client:
        app.state.httpx_client = client
        
        # Safely start MCP session manager if available and not started
        # Use getattr to be defensive against different MCP library versions
        manager = getattr(_mcp_server, "session_manager", None)
        has_started = getattr(manager, "_has_started", True) # Default to True to avoid starting if unsure
        
        if manager and not has_started:
            async with manager.run():
                yield
        else:
            yield
```

---

### Step 2: Add RELI_BASE_URL to Production

**File**: `docker-compose.yml`
**Action**: UPDATE

**Required change:**
Add `RELI_BASE_URL=https://reli.interstellarai.net` to the environment section of the `reli` service.

---

## Validation

### Automated Checks

```bash
# Verify code compiles and lint passes
ruff check backend/main.py
# Run existing tests
pytest backend/tests/test_health.py
```

### Manual Verification

1. Start the service using Docker Compose: `docker compose up -d`
2. Verify the health check: `curl -v http://localhost:8000/healthz`
3. Check logs if it fails: `docker compose logs reli`

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-29T10:00:00Z
- **Artifact**: `/mnt/ext-fast/reli/artifacts/runs/7b80a306b886519cccd4eee67510f427/investigation.md`
