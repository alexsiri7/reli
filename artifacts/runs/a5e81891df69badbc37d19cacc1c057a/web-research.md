---
name: Web research for issue #758
description: External research on the deploy-down failure mode (FastAPI lifespan + MCP streamable HTTP, Cloudflare/curl 000, Railway health checks)
type: research
---

# Web Research: fix #758 — "Deploy down: https://reli.interstellarai.net returning HTTP 000000"

**Researched**: 2026-05-01T09:15:00Z
**Workflow ID**: a5e81891df69badbc37d19cacc1c057a

---

## Summary

Three causes are consistent with the symptom (`HTTP 000000` from the health probe at `https://reli.interstellarai.net`): (1) curl could not establish a TCP/TLS connection at all (DNS / CDN / firewall / origin-down) — `000` is curl's sentinel for "no HTTP response received"; (2) the FastAPI `lifespan` is hanging or crashing inside the MCP `session_manager.run()` block, causing the container to never become ready (Docker `HEALTHCHECK` then keeps it unhealthy and Cloudflare returns nothing to the probe); (3) no recent successful Railway deploy because `RAILWAY_TOKEN` has been expiring repeatedly — the most recent ~20 commits on `main` are RAILWAY_TOKEN expiration investigations, so production may simply not have been re-deployed. The strongest code-level finding is that the existing lifespan at `backend/main.py:113-128` reaches into private MCP SDK state (`_session_manager`, `_has_started`, `_run_lock`) — this is a known fragile pattern caused by mounting the streamable HTTP MCP app as a sub-app of FastAPI; the documented fix is to combine the MCP server's own lifespan with the FastAPI lifespan rather than poke private attributes.

---

## Findings

### 1. `curl` / probe HTTP code `000` means *no HTTP response*, not an HTTP error

**Source**: [curl issue tracker / curl mailing list / IBM IT15643](https://www.ibm.com/support/pages/apar/IT15643)
**Authority**: Primary — curl maintainers and standard ops references.
**Relevant to**: Interpreting the issue body (`HTTP status: 000000`).

**Key information**:

- `000` from `curl --write-out '%{http_code}'` means curl never received an HTTP status — *not* a server-side error.
- Common causes: DNS resolution failure, connection refused, TCP timeout, TLS handshake failure, firewall drop.
- Recommendation from curl: also check the curl exit code (e.g. 6 = couldn't resolve host, 7 = couldn't connect, 28 = timeout, 35 = SSL connect error) instead of relying on the HTTP code alone.
- This means the Reli probe is failing *before* it gets a reply — the origin is down, blocked, or unreachable; it is **not** returning a 5xx that the app could log.

**Implication for #758**: The probe message gives no information about *why* the origin is unreachable. The investigation must come from Railway service logs / Cloudflare analytics, not from FastAPI logs alone.

---

### 2. The MCP Python SDK's `StreamableHTTPSessionManager.run()` is one-shot per instance, with a known race condition

**Sources**:
- [LiteLLM #13651 — `StreamableHTTPSessionManager.run() can only be called once per instance`](https://github.com/BerriAI/litellm/issues/13651)
- [LiteLLM PR #13666 — fix for the same](https://github.com/BerriAI/litellm/pull/13666)
- [modelcontextprotocol/python-sdk #1180 — FastMCP + Streamable HTTP session management](https://github.com/modelcontextprotocol/python-sdk/issues/1180)
- [modelcontextprotocol/python-sdk #2150 — Active Streamable HTTP sessions are not terminated during shutdown](https://github.com/modelcontextprotocol/python-sdk/issues/2150)

**Authority**: Upstream MCP SDK issue tracker (`modelcontextprotocol/python-sdk` is the SDK Reli uses via `from mcp.server.fastmcp import FastMCP`).
**Relevant to**: The hand-rolled reset code at `backend/main.py:115-128`.

**Key information**:

- `StreamableHTTPSessionManager.run()` raises if called twice on the same instance. The error string is literally `"StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again"`.
- A race condition exists: two coroutines that both enter the initialise-session-managers path concurrently can both flip `_has_started` to True and trip the guard. There is no lock around the guard in the SDK.
- Active sessions are not torn down cleanly during shutdown (issue #2150) — this can cause hangs on container shutdown that look like "lifespan never returns."

**Implication for #758**: The Reli code at `backend/main.py:115-128` resets `sm._has_started = False` and re-creates `sm._run_lock` to allow `run()` to be called again on the *same* SDK instance. This works in single-worker `uvicorn` mode but:
1. Reaches into private SDK state — any minor SDK upgrade can break it.
2. Does not protect against the race condition above. If two workers (or a worker + a hot-reload restart) hit the path concurrently, one will hang or crash.
3. If `run()` raises during startup, the FastAPI lifespan never `yield`s, the app never accepts traffic, the Docker `HEALTHCHECK` keeps the container unhealthy, and Cloudflare/Railway sees the origin as down → `HTTP 000000`.

---

### 3. Recommended pattern: combine the MCP server's lifespan with FastAPI's, don't poke private state

**Sources**:
- [modelcontextprotocol/python-sdk #713 — multi streamable HTTP server lifespan](https://github.com/modelcontextprotocol/python-sdk/issues/713)
- [modelcontextprotocol/python-sdk #1367 — Mounting Streamable HTTP MCP on existing FastAPI app](https://github.com/modelcontextprotocol/python-sdk/issues/1367)
- [FastMCP docs — FastAPI integration](https://gofastmcp.com/integrations/fastapi)
- [FastMCP docs — HTTP Deployment](https://gofastmcp.com/deployment/http)
- [jlowin/fastmcp #480 — make session_manager a property](https://github.com/jlowin/fastmcp/issues/480)
- [jlowin/fastmcp #1026 — provide custom lifespan to http_app()](https://github.com/jlowin/fastmcp/issues/1026)

**Authority**: Upstream SDK and the maintained third-party FastMCP documentation. Reli uses the upstream `mcp.server.fastmcp` package, not `jlowin/fastmcp` — the patterns are conceptually compatible but the API surface differs.

**Relevant to**: Replacing the `_has_started` reset hack in `backend/main.py:115-128` with a supported pattern.

**Key information**:

- Starlette / FastAPI sub-app `lifespan` does **not** propagate when the sub-app is `app.mount()`-ed. This is the root reason `session_manager.run()` has to be called from the parent app's lifespan.
- The supported pattern is to combine lifespans using `contextlib.AsyncExitStack`:

```python
from contextlib import AsyncExitStack, asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        # Existing Reli startup
        ...
        # MCP server — entered via its public session_manager.run()
        await stack.enter_async_context(_mcp_server.session_manager.run())
        yield
        # Cleanup runs in reverse order on AsyncExitStack exit
```

- For `jlowin/fastmcp` v2 the equivalent is `FastAPI(lifespan=mcp_app.lifespan)` or `combine_lifespans(app_lifespan, mcp_app.lifespan)` — Reli is on the upstream SDK, so the `AsyncExitStack` pattern is the correct one.
- Critically: `session_manager.run()` is one-shot per *instance*. If uvicorn restarts the worker (hot-reload, OOM, signal), a fresh process is created and the FastMCP global is re-imported — so the one-shot is not actually a problem under normal operation. The current reset hack is only needed because tests reuse the same module-level `mcp` object across runs. **Production does not need the reset hack.**

---

### 4. `RELI_BASE_URL` is missing from `docker-compose.yml`, which can cause MCP to reject requests with DNS-rebinding-protection errors

**Sources**:
- [MCP SDK source — TransportSecuritySettings + DNS rebinding protection](https://pypi.org/project/mcp/) (via the `enable_dns_rebinding_protection=True` flag in `backend/mcp_server.py:71`)
- Code inspection: `backend/mcp_server.py:42-50`, `docker-compose.yml:9-28`

**Authority**: Direct code inspection; SDK behaviour confirmed by SDK release notes referenced in PyPI listing.
**Relevant to**: Whether MCP requests would be 421-rejected even after the lifespan starts cleanly.

**Key information**:

- `backend/mcp_server.py:42` reads `RELI_BASE_URL` to derive the production hostname allowed by MCP's DNS-rebinding protection.
- `docker-compose.yml:22` declares the env var (`RELI_BASE_URL=${RELI_BASE_URL:-}`) but defaults it to empty.
- If the env var is not exported in production, `_RELI_HOST` falls back to whatever it can parse out of `GOOGLE_AUTH_REDIRECT_URI` — that may or may not match the real production hostname.
- Note this is **only** an MCP path (`/mcp/...`) issue; it does not explain `/healthz` returning `000`. So this is a side issue worth flagging in the fix, not the root cause of the deploy-down symptom.

---

### 5. Railway / Cloudflare path: `HTTP 000` from a public probe is consistent with origin not listening or CDN error 522/523

**Sources**:
- [Cloudflare Error 522 docs](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-522/)
- [Cloudflare Error 524 docs](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/)
- [Railway health-check failure thread (FastAPI)](https://station.railway.com/questions/health-check-failed-cd123ec3)
- [Railway `$PORT` shell-form CMD discussion](https://medium.com/@tomhag_17/debugging-a-railway-deployment-my-journey-through-port-variables-and-configuration-conflicts-eb49cfb19cb8)

**Authority**: Cloudflare official docs + Railway support / community.
**Relevant to**: Operational diagnosis of why a deploy can be "up" in CI but "000" externally.

**Key information**:

- A Cloudflare 522 means CF could not establish a TCP connection to origin within ~19s — usually because the origin process crashed, the host is overloaded, or a firewall is dropping CF IPs.
- A 524 means CF connected but origin took >100s to respond — consistent with a slow/hanging lifespan on a fresh container.
- If the probe is going through a stack like `domain → Cloudflare → Railway → container` and any link is broken, curl on the prober side reports `000` (because CF returns 522/524, the prober may also timeout before any HTTP response).
- Railway-specific common cause: shell-form CMD vs exec-form CMD around `${PORT}`. Reli's `Dockerfile:56` uses exec form with hardcoded `--port 8000` — that's fine on Railway only if the service is configured for static port 8000 (which Reli is, via `127.0.0.1:8000:8000` mapping in compose) but Railway typically expects `$PORT`.
- The Railway-side health probe path is `/healthz`. The Dockerfile `HEALTHCHECK` (line 52) also probes `/healthz` every 30s. If the lifespan never reaches `yield`, both fail and the container is killed/restarted.

---

### 6. Recent context: 20+ recent commits are RAILWAY_TOKEN rotation investigations

**Source**: `git log --oneline -20` on the worktree's `main`.
**Authority**: Direct repo state.
**Relevant to**: Whether a deploy has even happened recently.

**Key information**:

- The 20 most recent merged PRs (`#806` through `#838`) are all `docs: investigation for issue #N (Nth RAILWAY_TOKEN expiration)` commits.
- Per `CLAUDE.md` ("Railway Token Rotation"), agents cannot rotate the token; only the human can do it via railway.com.
- If `RAILWAY_TOKEN` is currently expired, the staging-pipeline workflow (`.github/workflows/staging-pipeline.yml:32-58`) fails at the validation step and never deploys a new image.
- Therefore: even if a code-level fix to the MCP lifespan is correct, **production won't pick it up until a human rotates the Railway token**. The runbook is at `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Code Examples

### Recommended replacement for `backend/main.py:108-130` (from upstream MCP SDK guidance)

From the pattern documented in [modelcontextprotocol/python-sdk #713](https://github.com/modelcontextprotocol/python-sdk/issues/713) and confirmed by [FastMCP integration docs](https://gofastmcp.com/integrations/fastapi):

```python
# Replace the _has_started / _run_lock reset hack with AsyncExitStack.
# This is the supported way to compose the MCP server's lifespan with FastAPI's.
from contextlib import AsyncExitStack

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_tracing()

    # ... (alembic migrations, scheduler start — unchanged) ...
    await start_scheduler()

    from .mcp_server import mcp as _mcp_server

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(httpx.AsyncClient(timeout=15.0))
        app.state.httpx_client = client

        # Only enter the MCP session manager once per process.
        # In production each worker is a fresh process so the SDK's one-shot
        # constraint is not an issue. Tests that reuse the module-level `mcp`
        # singleton should create a fresh FastMCP instance per test instead.
        await stack.enter_async_context(_mcp_server.session_manager.run())

        yield

    await stop_scheduler()
    shutdown_tracing()
```

Key differences from current code:

1. **No private attribute access** (`_session_manager`, `_has_started`, `_run_lock`) — uses only the public `session_manager` property and `run()` async context manager.
2. `AsyncExitStack` ensures all entered contexts (httpx client, MCP session) are torn down in reverse order on shutdown, including on the error path.
3. Removes the implicit reuse of one MCP instance across multiple lifespan starts — that workaround belongs in the test fixture, not in production code.

---

## Gaps and Conflicts

- **No definitive root cause of `HTTP 000000`**: the issue body gives only the curl status, not the curl exit code, not Railway logs, not Cloudflare analytics. We can list candidates but cannot pin one down without operator-side data. Recommend the implementation step include "fetch latest Railway deploy log and most recent Cloudflare error class for the domain" before changing code.
- **Disagreement between SDKs**: `jlowin/fastmcp` (v2) exposes `.lifespan` directly (`FastAPI(lifespan=mcp_app.lifespan)`), while upstream `mcp.server.fastmcp` requires manual `session_manager.run()` plumbing. The Reli codebase uses upstream — third-party FastMCP docs are *informative* but not directly applicable. `AsyncExitStack` is portable across both.
- **`session_manager` property visibility**: documented in upstream SDK as a property since the fix in `python-sdk` PR for issue #480-equivalent. Reli currently uses both `mcp.session_manager` (line 127) and the underscore-prefixed `_session_manager` (line 115) — these refer to the same object but the underscore form is private. Worth confirming the SDK version in `backend/requirements.txt` exposes `session_manager` as a property in the version Reli pins.
- **No data on whether the current production is actually crash-looping vs. simply not deployed**. If `RAILWAY_TOKEN` has been expired across most of the recent commit history, production may be running an *old* image that doesn't even have the MCP code at all. Verify Railway's "currently active deployment" SHA before assuming the bug is in the latest code.

---

## Recommendations

1. **Diagnose before changing code.** Pull the Railway deployment log for the active production image and check (a) the current deployed image SHA vs. `main` HEAD, (b) whether the container reached `Application startup complete.` in uvicorn, (c) whether the Docker `HEALTHCHECK` is passing. Without this you may "fix" code that the prod environment doesn't even run yet.
2. **Confirm `RAILWAY_TOKEN` validity first.** If it's expired (likely, given the recent commit history), no fix can ship to production until a human rotates it via the runbook in `docs/RAILWAY_TOKEN_ROTATION_742.md`. File a fresh GitHub issue tagged for the human if so — do not create a fake rotation doc (per `CLAUDE.md`).
3. **Replace the private-attribute reset with `AsyncExitStack`.** The existing `sm._has_started = False; sm._run_lock = anyio.Lock()` workaround is incorrect for production: it papers over a test-fixture concern, leaves a race window unprotected, and breaks on SDK upgrades. The supported pattern is one entry through `await stack.enter_async_context(mcp.session_manager.run())` from the parent lifespan.
4. **Add `RELI_BASE_URL=https://reli.interstellarai.net` to the production environment** so MCP's DNS-rebinding-protection allows the production host. Document this in `RAILWAY_SECRETS.md` or `DEPLOYMENT_SECRETS.md` so the env var is set on Railway, not just in compose.
5. **Tighten the Docker `HEALTHCHECK`** to give the lifespan more startup time. The current `--start-period=10s` is short — Alembic migrations + scheduler start + MCP `session_manager.run()` can plausibly exceed 10s on cold start, especially if the DB is also cold. `--start-period=60s` is more realistic for this stack.
6. **Avoid resurrecting bare `mcp.run()` calls** — they conflict with the mounted streamable-HTTP transport and are a documented source of double-init errors per upstream issues #1367 and #1180.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | curl HTTP code 000 (IBM IT15643) | https://www.ibm.com/support/pages/apar/IT15643 | Definition of HTTP `000` from curl |
| 2 | curl write-out 000 superuser thread | https://a.osmarks.net/content/superuser.com_en_all_2020-04/A/question/501690.html | Common causes for `000` |
| 3 | MCP SDK #713 — multi streamable HTTP lifespan | https://github.com/modelcontextprotocol/python-sdk/issues/713 | `AsyncExitStack` pattern for combining lifespans |
| 4 | MCP SDK #1367 — mounting streamable on FastAPI | https://github.com/modelcontextprotocol/python-sdk/issues/1367 | Sub-app lifespan does not propagate; need parent lifespan |
| 5 | MCP SDK #1180 — FastMCP + streamable HTTP session management | https://github.com/modelcontextprotocol/python-sdk/issues/1180 | Session manager initialisation issues |
| 6 | MCP SDK #2150 — sessions not terminated on shutdown | https://github.com/modelcontextprotocol/python-sdk/issues/2150 | Shutdown hang behaviour |
| 7 | LiteLLM #13651 — `run() can only be called once per instance` | https://github.com/BerriAI/litellm/issues/13651 | Confirms one-shot constraint and race |
| 8 | LiteLLM PR #13666 — fix for above | https://github.com/BerriAI/litellm/pull/13666 | Reference fix approach |
| 9 | jlowin/fastmcp #480 — session_manager as property | https://github.com/jlowin/fastmcp/issues/480 | Public API for session_manager |
| 10 | jlowin/fastmcp #1026 — custom lifespan to http_app | https://github.com/jlowin/fastmcp/issues/1026 | Lifespan composition |
| 11 | FastMCP docs — FastAPI integration | https://gofastmcp.com/integrations/fastapi | Recommended FastAPI integration patterns |
| 12 | FastMCP docs — HTTP Deployment | https://gofastmcp.com/deployment/http | Streamable HTTP deployment guidance |
| 13 | FastAPI docs — Lifespan Events | https://fastapi.tiangolo.com/advanced/events/ | Lifespan async context manager contract |
| 14 | Cloudflare Error 522 docs | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-522/ | Origin-unreachable behaviour |
| 15 | Cloudflare Error 524 docs | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/ | Origin-slow-response behaviour |
| 16 | Railway health-check failed thread | https://station.railway.com/questions/health-check-failed-cd123ec3 | Railway-specific deploy debugging |
| 17 | Railway PORT/CMD debugging post (Le, Medium) | https://medium.com/@tomhag_17/debugging-a-railway-deployment-my-journey-through-port-variables-and-configuration-conflicts-eb49cfb19cb8 | `$PORT` and shell-form CMD pitfalls |
| 18 | mcp PyPI page | https://pypi.org/project/mcp/1.9.1/ | Confirms upstream SDK API |
