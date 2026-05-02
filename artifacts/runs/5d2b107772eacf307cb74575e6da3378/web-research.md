# Web Research: fix #858

**Researched**: 2026-05-02T03:02:27Z
**Workflow ID**: 5d2b107772eacf307cb74575e6da3378
**Issue**: #858 — Prod deploy failed on main (`RAILWAY_TOKEN is invalid or expired: Not Authorized`)
**Note**: This is the 40th recurring instance of this failure mode in the repo (recent commits reference incidents #843, #850, #854 within the past few days).

---

## Summary

Railway publishes four distinct token types (account, workspace, project, OAuth) with different headers and different expectations from CI. Two patterns drive recurring `Not Authorized` failures: (1) **token-type/env-var mismatch** — Railway's CI guide says `RAILWAY_TOKEN` should hold a project token (using `Project-Access-Token` header), while `RAILWAY_API_TOKEN` holds the account/workspace token (using `Authorization: Bearer`); Reli currently sends an account-shaped token (Bearer + `{me{id}}` query) under the `RAILWAY_TOKEN` name, which Railway staff have explicitly flagged as "literally says invalid or expired even if u just made it 2 seconds ago"; and (2) **default TTL surprise** — Railway's token-creation UI defaults to a finite TTL, and tokens silently expire unless "No expiration" is selected. There is also a documented Railway-side outage from ~2025-11-10 where valid tokens stopped working until a server-side fix landed. Railway does **not** currently support GitHub OIDC federation, so the long-term mitigation must be procedural (pick the right token type, set No expiration, monitor proactively) rather than removing the token entirely.

---

## Findings

### 1. Railway Token Types and Header Conventions

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why `RAILWAY_TOKEN` may reject an account token even when freshly created

**Key Information**:

- Railway supports four token types with different headers:

  | Type | Scope | Header |
  |---|---|---|
  | Account | All resources/workspaces | `Authorization: Bearer <token>` |
  | Workspace | One workspace | `Authorization: Bearer <token>` |
  | Project | Single environment in a project | `Project-Access-Token: <token>` |
  | OAuth | User-delegated, third-party apps | `Authorization: Bearer <token>` |

- Project tokens are the most restrictive and are the type Railway recommends for CI/CD deploy automation.
- A query like `{ me { id } }` returns user-scoped data and **cannot be executed with a project or workspace token** — this is the exact GraphQL probe Reli's `Validate Railway secrets` step runs (see `.github/workflows/staging-pipeline.yml`). The probe inherently requires an account token.

---

### 2. `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` — Naming Drives Token-Type Expectation

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway-staff-moderated community thread
**Relevant to**: The most likely root cause of recurring "expired" reports despite fresh tokens

**Key Information**:

- A Railway moderator confirmed: *"You will need to use an account-scoped `RAILWAY_API_TOKEN`."* for CLI workflows that perform account-level operations.
- The CLI's bug where `RAILWAY_API_TOKEN` was not being respected was fixed in CLI v668+ — this is now the recommended env-var name for account tokens.
- Workspace-level operations (e.g. preview environments) require an account/workspace-scoped token, not a project token.

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Community thread with multiple corroborating reports

**Key Information**:

- Direct quote: *"`RAILWAY_TOKEN` now only accepts project token, if u put the normal account token … it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- If both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` are set, `RAILWAY_TOKEN` takes precedence — a leftover/wrong-type secret will mask a correct one.
- Recreating an account token under the `RAILWAY_TOKEN` name does **not** fix the issue; the cure is to either rename the secret to `RAILWAY_API_TOKEN`, or replace the account token with a project token under `RAILWAY_TOKEN`.

---

### 3. Token Expiration Behavior

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Whether tokens can be made effectively non-expiring

**Key Information**:

- OAuth access tokens expire after **1 hour**; refresh tokens have a **1-year** lifetime that resets on use.
- For account/workspace/project tokens, Railway's public docs do **not** publish an explicit TTL. Community-reported behavior suggests:
  - The token-creation UI offers an expiration selector with finite defaults.
  - **A "No expiration" option exists and must be explicitly chosen** — confirmed by the existing `docs/RAILWAY_TOKEN_ROTATION_742.md` runbook in this repo.
- An old refresh token used after rotation **revokes the entire authorization chain** as a security measure — relevant if any tooling caches stale tokens.

**Source**: [CLI throwing "Unauthorized" with RAILWAY_TOKEN — Railway Help Station](https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1)
**Authority**: Thread with Railway staff response

**Key Information**:

- A documented **Railway-side outage around 2025-11-10** caused valid tokens to be rejected until Railway deployed a server-side fix. Recurring failures during that window were not caused by user-side expiration.
- Recommended workaround for users still seeing failures locally: delete `~/.railway/config.json` to clear cached auth state.

---

### 4. Official Railway GitHub Actions Pattern

**Source**: [Using GitHub Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions)
**Authority**: Official Railway engineering blog
**Relevant to**: The canonical token wiring for non-interactive deploys

**Key Information**:

- The official post sets `RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}` and runs `railway up --service=${{ env.SVC_ID }}`.
- The token in this snippet is created from **Project → Settings → Tokens** (i.e. a **project token**, not an account token).
- Service ID can be exposed in plain text; only the token must remain secret.

---

### 5. Modern Alternative — GitHub OIDC (Not Yet Supported by Railway)

**Source**: [OpenID Connect — GitHub Docs](https://docs.github.com/en/actions/concepts/security/openid-connect)
**Authority**: GitHub official documentation
**Relevant to**: Long-term elimination of the rotation toil

**Key Information**:

- GitHub Actions can mint a short-lived OIDC JWT per workflow run; the cloud provider trusts the JWT issuer and exchanges it for ephemeral credentials.
- AWS, Azure, GCP, and HashiCorp Vault all support this pattern — **no long-lived secret stored in GitHub**, no rotation needed.
- Railway is **not** listed among the providers with documented OIDC trust support; community searches and Railway docs surface no OIDC-based deploy guide as of this research. **This means OIDC is not currently a viable mitigation for Reli, but is worth tracking** as a future option.

---

## Code Examples

Reli's current pre-flight check (`.github/workflows/staging-pipeline.yml` `Validate Railway secrets` step):

```bash
# Implicitly assumes RAILWAY_TOKEN is an ACCOUNT token (Bearer + me{id} query)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

Per Railway docs, the canonical project-token probe is different (header name and supported queries):

```bash
# From https://docs.railway.com/integrations/api — project token form
curl -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

---

## Gaps and Conflicts

- **Exact default TTL for account tokens** is not published anywhere in official Railway docs. Community reports suggest a short default (1–7 days has been mentioned in this repo's prior runbooks), but this is not authoritatively confirmed. The "No expiration" option exists, but the precise label and UI placement may have shifted between Railway dashboard versions.
- **Whether the current `RAILWAY_TOKEN` in the repo holds an account or project token** cannot be determined from outside the GitHub Secrets vault. The pre-flight design (Bearer + `{me{id}}`) implies an account token, which means the env-var name (`RAILWAY_TOKEN`) is misaligned with Railway's documented naming convention. This may be working today by accident and could explain some past failures classified as "expiration."
- **Railway OIDC support** is unconfirmed — searches surfaced no documented federation flow. Worth confirming via Railway support before recommending as a future direction.
- **Token health-check workflow effectiveness**: the repo references `.github/workflows/railway-token-health.yml` (weekly Monday probe). At 40 occurrences, the cadence is clearly not catching pre-expiration. The 7-day window between probes is wider than at least some observed expirations.

---

## Recommendations

Based on research, three layered mitigations — short-term (this PR), medium-term (next iteration), long-term (track):

1. **Short-term — verify and align secret naming + TTL when the human rotates the token.**
   - When the human next rotates per `docs/RAILWAY_TOKEN_ROTATION_742.md`, **explicitly confirm "No expiration" is selected** in the Railway dashboard. The recurring nature (40 incidents) strongly suggests at least some past rotations defaulted to a finite TTL.
   - Decide whether the secret should be an **account token** (current Bearer + `{me{id}}` pattern, but rename to `RAILWAY_API_TOKEN` to match Railway's convention) or a **project token** (rewrite the pre-flight to use `Project-Access-Token` header and a project-scoped probe). Mixing the patterns is a documented source of "Not Authorized" misreporting.
   - Per the repo's own CLAUDE.md, **agents must not perform the rotation or create rotation-completion docs**. The fix to ship from this workflow is documentation/code, not the secret value.

2. **Medium-term — tighten the health-check cadence and surface impending expiration.**
   - Reduce the `railway-token-health.yml` cron from weekly to daily (or every 6 hours). At 40 incidents, the gap between health probe and real CI run is the bottleneck — the alert is firing only after a deploy is already broken.
   - If Railway's API exposes token-metadata fields (e.g. `expiresAt` on `me { tokens }`), query it during the health check and open a warning issue at T-7 days, not at T+0.

3. **Long-term — track Railway OIDC support and consider migration when available.**
   - File an internal tracking note (or upstream Railway feature request) for GitHub OIDC federation. This is the only durable fix that eliminates rotation toil. Until Railway ships it, no amount of in-repo tooling will end the recurrence.
   - Avoid re-implementing rotation automation in the repo — the constraint is at Railway's auth layer, not in CI.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API \| Railway Docs | https://docs.railway.com/integrations/api | Authoritative on token types and headers |
| 2 | Login & Tokens \| Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTLs (1h access / 1y refresh) |
| 3 | Using GitHub Actions with Railway (blog) | https://blog.railway.com/p/github-actions | Official deploy pattern with `RAILWAY_TOKEN` (project token) |
| 4 | Token for GitHub Action — Railway Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Staff: use account-scoped `RAILWAY_API_TOKEN` for CI |
| 5 | RAILWAY_TOKEN invalid or expired — Railway Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community: token-type/env-var mismatch causes "expired" misreports |
| 6 | CLI throwing "Unauthorized" with RAILWAY_TOKEN | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Documented 2025-11-10 Railway-side outage; cache-clearing fix |
| 7 | RAILWAY_API_TOKEN not respected — Railway Central Station | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Historical CLI bug fixed in v668+ |
| 8 | Authentication not working with RAILWAY_TOKEN | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | Confirms account-token pattern for CI workflows |
| 9 | Deploying with the CLI \| Railway Docs | https://docs.railway.com/cli/deploying | Reference for `railway up` non-interactive flow |
| 10 | OpenID Connect — GitHub Docs | https://docs.github.com/en/actions/concepts/security/openid-connect | Long-term mitigation pattern; not yet supported by Railway |
