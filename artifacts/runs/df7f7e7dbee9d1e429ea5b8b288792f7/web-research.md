# Web Research: fix #759

**Researched**: 2026-04-29T22:35:00Z
**Workflow ID**: df7f7e7dbee9d1e429ea5b8b288792f7
**Issue**: [#759 — Deploy down: https://reli.interstellarai.net returning HTTP 000000](https://github.com/alexsiri7/reli/issues/759)

---

## Summary

#759 reports an `HTTP 000000` deploy-health-check failure at 2026-04-29 03:00:34 UTC. `HTTP 000` is **not** a real status code — it is curl's sentinel for "no HTTP response received at all" (DNS / TCP / TLS / timeout failure). The same monitor alert fired exactly 24h earlier as #758 with a byte-identical title and a structurally identical body (same template, only the detected timestamp differs), which is already being addressed by PR #760 (FastAPI lifespan + MCP session-manager startup hardening). Production was verified UP at investigation time (3/3 `/healthz` returning `200 OK` in ~500 ms). The web research below confirms (a) the HTTP-000 interpretation, (b) the FastAPI-MCP nested-lifespan startup-hang failure mode that PR #760 is targeting, and (c) the canonical `AsyncExitStack` pattern for fixing it correctly.

---

## Findings

### 1. HTTP 000 is curl's "no response" sentinel, not a server status

**Source**: [everything.curl.dev — Exit code](https://everything.curl.dev/cmdline/exitcode.html), [curl mailing list — `HTTP_CODE 000`](https://curl.se/mail/archive-2000-07/0013.html), [libcurl error codes](https://curl.se/libcurl/c/libcurl-errors.html)
**Authority**: Official curl project documentation and maintainer reply on the curl mailing list.
**Relevant to**: Interpreting the alert payload (`HTTP status: 000000`).

**Key Information**:

- A printed `http_code` of `000` means curl **never received an HTTP status line** — the response was never produced. Common causes:
  - DNS resolution failure (curl exit 6)
  - Connection refused (curl exit 7)
  - Connection / read timeout (curl exit 28)
  - TLS handshake failure (curl exit 35 / 60)
  - Proxy auth failure on HTTPS (`%{http_code}` shows `000` instead of `407`)
- The Railway / Cloudflare edge can also surface `000` if the upstream container drops the connection mid-handshake during a restart.
- Best practice from the curl docs: **check the curl exit code separately from `%{http_code}`**, because exit 0 + non-2xx is very different from non-zero exit + `000`.

**Implication for #759**: The "000000" repetition (six zeros) suggests the monitor concatenated the `http_code` from multiple retries — i.e. *all* retries failed at the connection layer. This is consistent with a momentary container restart or an unfinished startup, not an application 5xx.

---

### 2. Nested FastAPI + MCP lifespans cause silent startup hangs

**Source**: [modelcontextprotocol/python-sdk #713 — multi streamable HTTP server lifespan](https://github.com/modelcontextprotocol/python-sdk/issues/713), [modelcontextprotocol/python-sdk #1367 — Mounting Streamable HTTP MCP on FastAPI](https://github.com/modelcontextprotocol/python-sdk/issues/1367), [modelcontextprotocol/python-sdk #1220 — Task Group initialization error on lifespan](https://github.com/modelcontextprotocol/python-sdk/issues/1220), [tadata-org/fastapi_mcp #256 — lifespan not triggered when using `mount_http()`](https://github.com/tadata-org/fastapi_mcp/issues/256)
**Authority**: Official MCP Python SDK and `fastapi-mcp` issue trackers (multiple independent reports against current versions).
**Relevant to**: The actual root cause that PR #760 is trying to address.

**Key Information**:

- When an MCP `streamable_http_app()` is **mounted as a sub-app** of a FastAPI app, **Starlette does not propagate lifespan events into mounted sub-apps**. The MCP `StreamableHTTPSessionManager` is therefore never started, and its `_task_group` stays `None`.
- Symptoms reported by other users on the same library:
  - `RuntimeError: Task group is not initialized. Make sure to use run().`
  - `RuntimeError: Received request before initialization was complete` returning empty SSE responses.
  - Nothing happens for 30+ seconds at startup (matches a Railway healthcheck miss).
- The session manager's `run()` is a **one-shot** async context manager — once it has started, calling it again on the same instance fails. (This matches the workaround already in `backend/main.py:120-128` that resets `sm._has_started = False` and recreates `_run_lock`.)

**Implication for #759 / #758**: The hypothesis behind PR #760 (the lifespan/MCP-session-manager startup is the failure mode) is well-corroborated by upstream issues. It is a real, known class of failure, not a guess.

---

### 3. The canonical fix is `AsyncExitStack` around `session_manager.run()` inside the parent lifespan

**Source**: [modelcontextprotocol/python-sdk #713 (closing comment with code sample)](https://github.com/modelcontextprotocol/python-sdk/issues/713), [FastAPI discussion #9397 — multiple lifespans](https://github.com/fastapi/fastapi/discussions/9397), [FastAPI discussion #10083 — multiple lifespan contexts](https://github.com/fastapi/fastapi/discussions/10083)
**Authority**: MCP SDK maintainers and FastAPI maintainer-blessed discussion threads.
**Relevant to**: How PR #760 *should* be structured (and a benchmark for the existing `backend/main.py` lifespan).

**Key Information**:

The recommended pattern, when the parent FastAPI app owns the lifespan and mounts MCP sub-apps:

```python
import contextlib
from fastapi import FastAPI

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(echo.mcp.session_manager.run())
        await stack.enter_async_context(math.mcp.session_manager.run())
        yield
    # AsyncExitStack guarantees reverse-order shutdown even on exception

app = FastAPI(lifespan=lifespan)
app.mount("/echo", echo.mcp.streamable_http_app())
app.mount("/math", math.mcp.streamable_http_app())
```

Notes:

- `AsyncExitStack` is preferable to nested `async with` blocks because (a) it composes N managers, (b) shutdown ordering is deterministic, and (c) an exception during one `enter_async_context` doesn't strand the others mid-startup.
- The current `backend/main.py:103-130` uses a single `async with _mcp_server.session_manager.run():` *inside* a separate `async with httpx.AsyncClient(...)` — this works for one MCP server but does not generalize, and the `_has_started` reset workaround indicates the lifecycle is being torn down and re-entered in a way the SDK doesn't natively support.

---

### 4. Railway healthchecks: 300 s default timeout, must serve `200` quickly

**Source**: [Railway Docs — Healthchecks](https://docs.railway.com/reference/healthchecks), [Railway Docs — Healthchecks and Restarts](https://docs.railway.com/guides/healthchecks-and-restarts), [Railway Help Station — Intermittent deployment health check failures and 502s](https://station.railway.com/questions/intermittent-deployment-health-check-fai-02457844), [Railway Help Station — Container terminates after successful healthcheck](https://station.railway.com/questions/container-terminates-after-successful-he-67400aaf)
**Authority**: Official Railway documentation + active Railway support forum threads.
**Relevant to**: Why a slow lifespan startup turns into a 503/000 at the edge.

**Key Information**:

- On every new deployment, Railway polls the configured healthcheck endpoint and only swaps traffic to the new container after it returns `200`. Default timeout is **300 s**.
- Railway forum reports of "intermittent ~50% deploy failures" describe exactly the same pattern as #758/#759: build succeeds, container starts, but the healthcheck sees `connection refused` for the entire window because the lifespan hasn't yielded yet.
- A January 2026 Railway forum thread reports a Flask container that "starts successfully and passes healthcheck, but terminates after 3-6 seconds" — this is the inverse failure (container crash after startup) and is worth ruling out for #758/#759 by checking Railway's deployment logs for OOM / SIGKILL.
- Common Railway-side fix: ensure the app binds to `$PORT` (not a hard-coded port) — already the case in this repo per the existing Dockerfile (uvicorn on `0.0.0.0:$PORT`).

---

### 5. Lifespan timeout / cancellation pitfalls

**Source**: [FastAPI discussion #6526 — Stuck on "Waiting for application startup"](https://github.com/fastapi/fastapi/discussions/6526), [FastAPI discussion #13346 — Application cannot be terminated before yielding in lifespan](https://github.com/fastapi/fastapi/discussions/13346), [Sentry — Long-running tasks time out in FastAPI](https://sentry.io/answers/make-long-running-tasks-time-out-in-fastapi/)
**Authority**: FastAPI core discussions + Sentry's engineering content.
**Relevant to**: Defensive coding around the lifespan to make startup hangs visible (and recoverable) rather than silent.

**Key Information**:

- If a `lifespan` coroutine blocks before `yield`, **SIGTERM does not interrupt it** — the process must be SIGKILL'd. This is the FastAPI/Starlette equivalent of an undertested startup.
- The defensive pattern is to wrap any "slow or external dependency" startup steps in `asyncio.wait_for(..., timeout=N)` so that a hang surfaces as an exception instead of an indefinite "Waiting for application startup."
- Don't put long-running loops inside lifespan startup — kick them off as background tasks (or use a scheduler like APScheduler, which `backend/sweep_scheduler.py` already does for sweeps).

---

### 6. Alert deduplication via the Upptime model

**Source**: [Upptime — GitHub Actions uptime monitor](https://github.com/upptime/upptime), [GitHub Actions Scheduled Workflows: Complete Guide (CronJobPro)](https://cronjobpro.com/blog/github-actions-scheduled-workflows), [GitHub Community — Unexpected delay in scheduled GitHub Actions workflows](https://github.com/orgs/community/discussions/156282)
**Authority**: Upptime is the canonical OSS prior art for this exact use case (cron-based uptime monitor that opens GitHub issues on failure).
**Relevant to**: The out-of-scope follow-up flagged in the existing investigation comment — "the 03:00 UTC monitor opens a new issue per failure rather than commenting on the existing one."

**Key Information**:

- **Upptime's design**: open *one* issue when a check first fails, post follow-up *comments* (not new issues) on subsequent failures of the same target, and **auto-close** the issue when the check recovers. This is the dedup pattern this repo's monitor is currently missing.
- GitHub Actions cron schedules are best-effort: a "5-minute" schedule can drift by several minutes under load and may even be skipped — *don't* rely on cron timing for SLA-grade alerting.
- Scheduled workflows auto-disable after **60 days of repository inactivity**; a daily uptime workflow effectively keeps itself alive, but it's still worth knowing.

---

## Code Examples

### Recommended FastAPI + MCP lifespan pattern (from MCP SDK issue #713)

```python
# From https://github.com/modelcontextprotocol/python-sdk/issues/713
import contextlib
from fastapi import FastAPI

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_server.session_manager.run())
        # ... other long-lived resources ...
        yield

app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp_server.streamable_http_app())
```

### Defensive timeout around lifespan startup (from FastAPI discussion #6526 + Sentry)

```python
# From https://sentry.io/answers/make-long-running-tasks-time-out-in-fastapi/
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.wait_for(_start_mcp_session_manager(app), timeout=20.0)
    except asyncio.TimeoutError:
        logger.exception("MCP session manager startup exceeded 20s — failing fast")
        raise   # let supervisor restart, rather than hang Railway healthcheck
    yield
    await _stop_mcp_session_manager(app)
```

---

## Gaps and Conflicts

- **Could not directly confirm whether Railway uses the `/healthz` or `/api/health` endpoint for #758/#759.** The investigation comment shows `/healthz` returns `{"status":"ok","service":"reli"}`, and the existing repo has both a `/healthz` route and `/api/health` per `backend/main.py`. Worth verifying Railway's `railway.toml` / dashboard config.
- **No upstream confirmation that `_has_started` reset on the MCP `StreamableHTTPSessionManager` is endorsed.** The current `backend/main.py:120-128` uses private attributes (`sm._has_started`, `sm._run_lock`) — this is a workaround rather than a documented API and may break across MCP SDK versions. PR #760's body claims it "improved robustness using `getattr`" — that's still touching private internals.
- **Cannot tell from public sources whether the production failure on 2026-04-28/29 03:00 UTC was actually caused by the MCP lifespan path or by some other transient (Railway edge, Cloudflare, container restart, OOM).** The hypothesis is plausible and matches upstream symptoms, but #760 lands without a *captured stack trace or log line* proving it. Recommend grepping Railway deploy logs for `Task group` / `RuntimeError` / `Waiting for application startup` before accepting #760 as the canonical fix.
- **No source found for whether Railway's healthcheck retry budget is configurable per-service** in the way that matters for slow startups; the docs only mention the 300 s overall timeout.

---

## Recommendations

For the **current bead (#759)** — keep it administrative, don't write code:

1. **Close #759 as a duplicate of #758.** The investigation already established this. Production is UP, the alert title is byte-identical and the body structurally identical (same template, only the detected timestamp differs) to #758 from 24h earlier, and PR #760 is the canonical fix. Per CLAUDE.md Polecat Scope Discipline, do not also try to fix the underlying lifespan in this bead — that work belongs to PR #760.

For the **PR #760 review** (out of scope for this bead, but informs follow-up):

2. **Adopt the `AsyncExitStack` pattern from MCP SDK issue #713** instead of the current ad-hoc `_has_started` reset. The reset hack relies on private attributes and will rot when the MCP SDK changes its internals.
3. **Wrap MCP startup in `asyncio.wait_for(..., timeout=20)`** so that a hung session manager fails the deploy *immediately* rather than chewing up Railway's 300 s healthcheck budget and producing the `HTTP 000` symptom.
4. **Clean up the +117k log-file additions** before #760 can merge (already flagged in the existing investigation).

For the **monitoring layer** (out of scope, route to mayor):

5. **Switch the daily monitor to the Upptime pattern** — comment on an existing open `Deploy down` issue rather than opening a new one, and auto-close on recovery. This eliminates the #758/#759 duplicate-pair problem at the source.
6. **Capture the curl exit code alongside `%{http_code}`** in the monitor payload so future "000" alerts come with a real diagnosis (DNS vs TCP vs TLS vs timeout) rather than just six zeros.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | everything.curl.dev — Exit code | https://everything.curl.dev/cmdline/exitcode.html | Authoritative meaning of curl exit codes |
| 2 | curl mailing list — HTTP_CODE 000 | https://curl.se/mail/archive-2000-07/0013.html | Maintainer reply: 000 = no response received |
| 3 | libcurl error codes | https://curl.se/libcurl/c/libcurl-errors.html | Full curl error code reference |
| 4 | MCP SDK #713 — multi streamable HTTP lifespan | https://github.com/modelcontextprotocol/python-sdk/issues/713 | Canonical AsyncExitStack pattern |
| 5 | MCP SDK #1367 — Mounting on FastAPI | https://github.com/modelcontextprotocol/python-sdk/issues/1367 | Confirms nested-lifespan failure mode |
| 6 | MCP SDK #1220 — Task Group init error | https://github.com/modelcontextprotocol/python-sdk/issues/1220 | Symptom: `Task group is not initialized` |
| 7 | fastapi-mcp #256 — lifespan not triggered | https://github.com/tadata-org/fastapi_mcp/issues/256 | Same root cause via fastapi-mcp |
| 8 | MCP SDK #737 — RuntimeError before init complete | https://github.com/modelcontextprotocol/python-sdk/issues/737 | Empty SSE responses when lifespan misordered |
| 9 | FastAPI Lifespan Events | https://fastapi.tiangolo.com/advanced/events/ | Official lifespan API docs |
| 10 | FastAPI #9397 — multi-lifespan idea | https://github.com/fastapi/fastapi/discussions/9397 | AsyncExitStack composition pattern |
| 11 | FastAPI #10083 — multiple lifespan contexts | https://github.com/fastapi/fastapi/discussions/10083 | Same pattern, more examples |
| 12 | FastAPI #6526 — stuck on "Waiting for application startup" | https://github.com/fastapi/fastapi/discussions/6526 | SIGTERM cannot interrupt pre-yield hang |
| 13 | FastAPI #13346 — cannot terminate before yield | https://github.com/fastapi/fastapi/discussions/13346 | Same pitfall, more recent thread |
| 14 | Sentry — Long-running tasks timeout in FastAPI | https://sentry.io/answers/make-long-running-tasks-time-out-in-fastapi/ | `asyncio.wait_for` pattern for startup |
| 15 | Railway Docs — Healthchecks | https://docs.railway.com/reference/healthchecks | 300 s default timeout, 200 required to swap traffic |
| 16 | Railway Docs — Healthchecks and Restarts | https://docs.railway.com/guides/healthchecks-and-restarts | Restart-policy interaction |
| 17 | Railway Help — Intermittent deploy 502s | https://station.railway.com/questions/intermittent-deployment-health-check-fai-02457844 | Real-world report of identical symptom |
| 18 | Railway Help — Container terminates after healthcheck | https://station.railway.com/questions/container-terminates-after-successful-he-67400aaf | Inverse failure to rule out (post-startup crash) |
| 19 | Upptime | https://github.com/upptime/upptime | Canonical OSS dedup pattern for GitHub-Actions uptime monitors |
| 20 | GitHub Community — cron workflow delay | https://github.com/orgs/community/discussions/156282 | GitHub Actions cron is best-effort |
