# Security Audit — Reli Application

**Date**: 2026-03-15
**Scope**: Full review of FastAPI backend + React frontend
**Type**: Read-only audit (no fixes applied)

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2 |
| HIGH | 6 |
| MEDIUM | 10 |
| LOW | 4 |

---

## CRITICAL Findings

### C1: No Authentication or Authorization on Any API Endpoint

- **Severity**: CRITICAL
- **Location**: `backend/main.py:47-54`
- **Description**: All API endpoints are completely unprotected. There is no authentication middleware, no JWT validation, no API key checks, and no `Depends()` security on any router. Anyone with network access can:
  - Read/create/update/delete all Things and chat history
  - Access Gmail messages and Google Calendar events
  - Trigger expensive LLM operations (cost amplification)
  - Run the nightly sweep (`POST /api/sweep/run`)
- **Recommendation**: Implement authentication (JWT tokens or session-based auth with secure cookies). Add `Depends()` guards to all sensitive routes. Consider API key validation as a minimum interim measure.

### C2: Directory Traversal in SPA Fallback Route

- **Severity**: CRITICAL
- **Location**: `backend/main.py:66-72`
- **Description**: The catch-all SPA route constructs a file path from user input without validating it stays within the `_FRONTEND_DIST` directory:
  ```python
  static_file = _FRONTEND_DIST / full_path
  if full_path and static_file.is_file():
      return FileResponse(static_file)
  ```
  An attacker could request paths like `GET /../../app/data/reli.db` or `GET /../../app/data/gmail_token.json` to access the production database or OAuth tokens. While Starlette may normalize some path segments, the pattern is unsafe and must not rely on framework behavior for security.
- **Recommendation**: Add explicit path traversal protection:
  ```python
  resolved = static_file.resolve()
  if not resolved.is_relative_to(_FRONTEND_DIST.resolve()):
      return FileResponse(_FRONTEND_DIST / "index.html")
  ```

---

## HIGH Findings

### H1: OAuth Tokens Stored in Plaintext in SQLite

- **Severity**: HIGH
- **Location**: `backend/google_calendar.py:63-93`
- **Description**: Google Calendar OAuth credentials (access_token, refresh_token, client_id, client_secret) are stored as plaintext in the `google_tokens` table. If the SQLite database file is compromised (e.g., via the directory traversal in C2), an attacker gains full access to the user's Google Calendar.
- **Recommendation**: Encrypt tokens at rest using `cryptography.fernet.Fernet` with a key from a separate environment variable or secrets manager.

### H2: Gmail Credentials Stored as Plaintext JSON on Disk

- **Severity**: HIGH
- **Location**: `backend/routers/gmail.py:60-63`
- **Description**: Gmail OAuth2 credentials are written to `gmail_token.json` as plaintext without restrictive file permissions. The file contains the full credentials object including refresh_token.
- **Recommendation**: Encrypt the file before writing. Set file permissions to `0o600`. Consider migrating to the same DB-based storage as Google Calendar tokens.

### H3: Prompt Injection Risk in Chat Pipeline

- **Severity**: HIGH
- **Location**: `backend/agents.py:456`
- **Description**: User messages are directly interpolated into the reasoning agent prompt without delimiters or sanitization:
  ```python
  user_content = f"Today's date: {today}\n\nUser message: {message}\n\n..."
  ```
  An attacker could craft messages that inject new instructions, attempt to extract system prompts, or manipulate tool calls. The response agent (`agents.py:707`) similarly injects the reasoning summary (LLM output) directly into the next prompt, enabling multi-hop injection.
- **Recommendation**: Wrap user input in explicit delimiters (e.g., `<<<user_input>>>`). Add an instruction to treat user input as data, not instructions. Validate LLM output structure before passing to downstream agents.

### H4: No Rate Limiting on Any Endpoint

- **Severity**: HIGH
- **Location**: All routers in `backend/routers/`
- **Description**: No rate limiting is implemented. An attacker can:
  - Spam `/api/chat` to run up LLM API costs
  - Trigger `/api/sweep/run` repeatedly (expensive LLM operations)
  - Flood the database with requests
  - Brute-force session IDs or Thing IDs
- **Recommendation**: Add `slowapi` or similar rate limiting. Apply strict limits on `/api/chat` (e.g., 10/minute) and `/api/sweep/run` (e.g., 1/hour).

### H5: Sensitive Information Leaked in Error Responses

- **Severity**: HIGH
- **Location**: `backend/routers/gmail.py:263,274`, `backend/routers/calendar.py:50`
- **Description**: Raw exception messages are included in HTTP error responses (e.g., `detail=f"Message not found: {e}"`). The calendar callback reflects exceptions into redirect URLs (`url=f"/?calendar_error={exc}"`), exposing internal details in browser history and server logs.
- **Recommendation**: Log full exceptions server-side. Return generic error messages to clients.

### H6: Docker Container Runs as Root

- **Severity**: HIGH
- **Location**: `Dockerfile:10-28`
- **Description**: The Dockerfile does not specify a non-root `USER` directive. The container process runs as root, meaning a container escape or application compromise gives the attacker root privileges.
- **Recommendation**: Add before `CMD`:
  ```dockerfile
  RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
  USER appuser
  ```

---

## MEDIUM Findings

### M1: Overly Permissive CORS Configuration

- **Severity**: MEDIUM
- **Location**: `backend/main.py:39-45`
- **Description**: CORS allows `allow_methods=["*"]` and `allow_headers=["*"]` with `allow_credentials=True`. While origins are restricted to localhost (appropriate for development), the wildcard methods and headers are broader than necessary.
- **Recommendation**: Restrict to `allow_methods=["GET", "POST", "PATCH", "DELETE"]` and `allow_headers=["Content-Type", "Authorization"]`. Make origins configurable via environment variable for production.

### M2: No Security Headers (CSP, X-Frame-Options, HSTS)

- **Severity**: MEDIUM
- **Location**: `backend/main.py` (entire app)
- **Description**: No security headers are set: no Content-Security-Policy, no X-Frame-Options, no X-Content-Type-Options, no Strict-Transport-Security, no Referrer-Policy.
- **Recommendation**: Add middleware to set all standard security headers.

### M3: No CSRF Protection

- **Severity**: MEDIUM
- **Location**: All POST/PATCH/DELETE endpoints
- **Description**: No CSRF tokens are validated. The app relies solely on CORS origin checks, which only protect against cross-origin browser requests.
- **Recommendation**: Implement CSRF token validation using double-submit cookie pattern.

### M4: Dynamic SQL Column Names via f-strings

- **Severity**: MEDIUM
- **Location**: `backend/routers/things.py:270-272`, `backend/routers/thing_types.py:105`, `backend/agents.py:582`
- **Description**: SQL UPDATE statements build SET clauses dynamically using f-strings for column names (e.g., `f"UPDATE things SET {set_clause} WHERE id = ?"`). While column names currently come from validated Pydantic model fields (not direct user input), the pattern is fragile and could become exploitable if refactored carelessly.
- **Recommendation**: Validate column names against an explicit allowlist. Consider using an ORM or query builder.

### M5: No Input Size Limits on Chat Messages

- **Severity**: MEDIUM
- **Location**: `backend/models.py:107,131`
- **Description**: `ChatMessageCreate.content` and `ChatRequest.message` have `min_length=1` but no `max_length`. An attacker could send very large payloads, causing memory exhaustion or expensive LLM API calls.
- **Recommendation**: Add `max_length=100000` (or appropriate limit) to content fields.

### M6: No `session_id` Format Validation

- **Severity**: MEDIUM
- **Location**: `backend/models.py:105,130`
- **Description**: `session_id` only validates `min_length=1`, allowing arbitrary strings. This enables unbounded session creation and potential abuse.
- **Recommendation**: Add format validation (e.g., `pattern="^[a-zA-Z0-9_-]{1,100}$"`) or enforce UUID format.

### M7: Unbounded `data` Field on Things

- **Severity**: MEDIUM
- **Location**: `backend/models.py:44,56`
- **Description**: `Thing.data` accepts `dict[str, Any]` with no size or depth limits. Deeply nested or very large JSON payloads could cause parser bombs or fill the database.
- **Recommendation**: Validate payload size (e.g., max 10KB) and reject deeply nested structures.

### M8: Environment Variables Not Validated at Startup

- **Severity**: MEDIUM
- **Location**: `backend/agents.py:62-78`, `backend/web_search.py:12-13`
- **Description**: API keys are read from environment but never validated. Missing or invalid keys cause silent runtime failures.
- **Recommendation**: Add a startup validation function that checks required env vars and raises explicit errors.

### M9: No Token Rotation or Expiry Mechanism

- **Severity**: MEDIUM
- **Location**: `backend/google_calendar.py`, `backend/routers/gmail.py`
- **Description**: OAuth refresh tokens are stored indefinitely without rotation or expiry tracking. A compromised token provides permanent access.
- **Recommendation**: Track `expires_at` and implement forced re-authentication after a configurable period.

### M10: ChromaDB Vector Store Has No Access Controls

- **Severity**: MEDIUM
- **Location**: `backend/vector_store.py:77-83`
- **Description**: ChromaDB is initialized with `PersistentClient` and no authentication. The `chroma_db/` directory has no documented permission requirements.
- **Recommendation**: Set directory permissions to `700`. Document access control requirements.

---

## LOW Findings

### L1: No Audit Logging for Sensitive Operations

- **Severity**: LOW
- **Location**: All routers
- **Description**: No structured logging for OAuth connections, data access, or administrative operations. Security incidents cannot be investigated.
- **Recommendation**: Add structured audit logging for OAuth flows, data modifications, and errors.

### L2: Dependencies Use Unpinned Version Ranges

- **Severity**: LOW
- **Location**: `backend/requirements.txt`
- **Description**: Dependencies use `>=` without upper bounds (e.g., `fastapi>=0.111.0`). This allows unexpected major version upgrades.
- **Recommendation**: Use pinned versions or a lock file for production deployments.

### L3: Source Maps May Be Served in Production

- **Severity**: LOW
- **Location**: `frontend/vite.config.ts`
- **Description**: Vite does not explicitly disable source maps in production builds. If `.map` files are generated, they could be served by the SPA fallback and expose source code.
- **Recommendation**: Explicitly set `build: { sourcemap: false }` in Vite config.

### L4: Config YAML Loaded Without Schema Validation

- **Severity**: LOW
- **Location**: `backend/agents.py:38-39`
- **Description**: `config.yaml` is loaded with `yaml.safe_load()` (safe from code execution) but parsed values are used without schema validation.
- **Recommendation**: Validate config structure using a Pydantic model after loading.

---

## Positive Findings

- **React XSS protection**: No use of `dangerouslySetInnerHTML`. All user content rendered as text.
- **No markdown rendering**: Eliminates markdown-based XSS vectors.
- **Parameterized SQL values**: All user-supplied values use `?` placeholders (not string interpolation).
- **`.env` excluded from git**: `.gitignore` correctly excludes `.env` and `data/`.
- **Multi-stage Docker build**: Frontend build artifacts don't leak into the production image.
- **Docker port binding**: `docker-compose.yml` binds to `127.0.0.1:8000` (not `0.0.0.0`).
- **`yaml.safe_load`**: Config loading is safe from YAML deserialization attacks.

---

## Prioritized Remediation Plan

1. **Immediate** (CRITICAL): Fix directory traversal (C2) and add authentication (C1)
2. **Urgent** (HIGH): Encrypt stored tokens (H1, H2), add rate limiting (H4), fix error leakage (H5), add non-root Docker user (H6)
3. **Short-term** (MEDIUM): Add security headers (M2), CSRF protection (M3), input size limits (M5-M7), CORS tightening (M1)
4. **Ongoing** (LOW): Audit logging (L1), dependency pinning (L2), config validation (L4)
