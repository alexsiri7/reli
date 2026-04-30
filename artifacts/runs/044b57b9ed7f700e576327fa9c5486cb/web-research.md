# Web Research: fix #781

**Researched**: 2026-04-30T00:00:00Z
**Workflow ID**: 044b57b9ed7f700e576327fa9c5486cb

---

## Summary

Issue #781 is the **14th occurrence** in this repo of "Prod deploy failed on main / RAILWAY_TOKEN is invalid or expired: Not Authorized" (prior: #725, #727, #728, #733, #737, #739, #742, #745, #747, #748, #751, #752, #755, #762, #769, #771, #773, #774, #777, #779). Web research suggests two distinct root-cause hypotheses worth investigating: (a) Railway's dashboard-created account tokens may have an undocumented or short default TTL, and (b) the validation query (`{me{id}}`) and `Authorization: Bearer` header pin the workflow to an *account-scoped* personal access token specifically — workspace tokens (the type Railway recommends "Best For Team CI/CD") will be rejected by that validation step even though they could perform the actual deploy mutation. The recurring rotation pattern strongly indicates the operator is creating a token type whose lifecycle is not under our control rather than a token mis-scoped against our workflow.

---

## Findings

### 1. Railway has four token types with different scopes and headers

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Picking the right token for `.github/workflows/staging-pipeline.yml`

**Key Information**:

- **Account token** — "All your resources and workspaces" scope, "Best For Personal scripts, local development". Created at `https://railway.com/account/tokens` with no workspace selected.
- **Workspace token** — "Single workspace" scope, **"Best For Team CI/CD, shared automation"**. Created at the same URL with a workspace selected.
- **Project token** — "Single environment in a project" scope, "Best For Deployments, service-specific automation". Created from the project's settings page.
- **OAuth** — third-party app delegation.
- Header format: account/workspace/OAuth tokens use `Authorization: Bearer <token>`; project tokens use `Project-Access-Token: <token>`.

---

### 2. The `{me{id}}` validation query requires an account (personal) token specifically

**Source**: [GraphQL requests returning "Not Authorized" for PAT — Railway Help Station](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Railway moderator response in the official help forum
**Relevant to**: The workflow's "Validate Railway secrets" step at `.github/workflows/staging-pipeline.yml:42`

**Key Information**:

- Quoted from moderator: *"personal access token is the highest level token and should work with essentially any workspace,"* while *"workspace access tokens are limited to that specific workspace. The `me` query specifically requires a personal access token."*
- Implication: our validation `{me{id}}` will fail with `Not Authorized` if a workspace token is used, even though the workspace token would correctly authorize the actual `serviceInstanceUpdate` mutation that deploys.
- Project tokens cannot be used at all here because they require the `Project-Access-Token` header, not `Authorization: Bearer`.

---

### 3. Railway docs do **not** document a TTL on dashboard-created tokens

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli)
**Authority**: Official Railway documentation
**Relevant to**: The local runbook's claim that operators must select "No expiration" when creating the token

**Key Information**:

- The only TTL documentation Railway publishes is for **OAuth flows**: *"Access tokens expire after one hour"* and *"refresh tokens... one-year lifetime from the time of issuance"* — these are OAuth access/refresh tokens, **not** the account/workspace/project tokens created in the dashboard.
- No public Railway documentation could be found that mentions a TTL selector or "No expiration" option in the dashboard token-creation UI. The existing local runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) asserts *"the default TTL may be short (e.g., 1 day or 7 days)... The new token must be created with 'No expiration'"* — this guidance is **not corroborated** by any source we could find and may be speculation from an earlier rotation.
- **Gap**: We cannot determine from public documentation whether the recurring expirations are caused by (a) a configurable TTL the operator keeps missing, (b) an undocumented Railway-side TTL on certain token types, or (c) external invalidation (password change, session revocation, security policy).

---

### 4. "RAILWAY_TOKEN invalid or expired" is frequently a *token-type* issue, not actual expiration

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community help forum
**Relevant to**: Ruling out a class of false-expiration reports for the **CLI** specifically

**Key Information**:

- Direct quote from thread: *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token (the one u make in account settings) it literally says 'invalid or expired' even if u just made it 2 seconds ago"*
- **Important caveat**: This applies to the **Railway CLI's** parsing of the `RAILWAY_TOKEN` env var. Our workflow does NOT use the CLI — it calls `https://backboard.railway.app/graphql/v2` directly via `curl`. So this specific failure mode does not match our setup. But the fact that "invalid or expired" is the generic GraphQL error string for any auth failure (wrong token type, revoked token, malformed bearer, actually-expired) means our error message should not be taken literally as "the token expired."

---

### 5. Railway recommends **account/personal tokens** for GitHub Actions, but in conflicting environment variables

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720), [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli)
**Authority**: Railway employee response + official docs
**Relevant to**: Whether the current secret naming/usage matches Railway's intent

**Key Information**:

- Railway employee guidance: *"use a Railway API token scoped to the user account, not a project token, for the GitHub Action"* — and to set it via `RAILWAY_API_TOKEN`, not `RAILWAY_TOKEN`.
- CLI doc: *"Set `RAILWAY_TOKEN` for project-level actions"*, *"Set `RAILWAY_API_TOKEN` for account-level actions"*.
- Our workflow uses an env var named `RAILWAY_TOKEN` but passes its value as a literal `Authorization: Bearer` header (account-style) and queries `{me{id}}` (account-required). The secret-variable *name* is irrelevant to the raw HTTP call (it's never read by the CLI), but anyone debugging based on Railway docs may be misled by the naming. The token *value* must be an account-scoped personal access token.

---

### 6. A January 2026 Railway incident report exists but does not mention token mass-invalidation

**Source**: [Incident Report: January 28-29, 2026](https://blog.railway.com/p/incident-report-january-26-2026)
**Authority**: Official Railway blog
**Relevant to**: Ruling out platform-wide token invalidation events as the recurring cause

**Key Information**:

- The reference appeared in search results but the page was not deeply inspected for token-related content. Worth a follow-up read to confirm it doesn't describe rolling token invalidation, but at first glance it does not look like a token-lifecycle event.

---

## Code Examples

### Current workflow validation (the failing step)

```yaml
# From .github/workflows/staging-pipeline.yml
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
```

The `{me{id}}` payload pins this step to a personal/account token. A workspace token would fail validation here, even though the same token could successfully run the downstream `serviceInstanceUpdate` mutation.

### Switching to a workspace-token-tolerant validation

```graphql
# Compatible with both account AND workspace tokens
query { __typename }
```

A `__typename` ping confirms the token authenticates without depending on account-only scope. Trade-off: it no longer asserts the token resolves to a known identity, only that some token works.

---

## Gaps and Conflicts

- **Unresolved**: Whether Railway's account-token dashboard UI actually offers an expiration TTL selector. The existing runbook says it does (with "No expiration" as one option); no public Railway documentation we can find corroborates this. The operator (human) needs to confirm by visiting `https://railway.com/account/tokens` and reporting what selectors appear.
- **Unresolved**: Why this token expires roughly every few days (14 incidents in the visible commit history). If account tokens truly have no TTL, an external invalidator must exist — possible candidates: workspace ownership changes, billing/plan changes, automated security rotation if the account has 2FA or session policies set, or an account-suspension/email-verification loop.
- **Conflicting**: Railway docs say `RAILWAY_API_TOKEN` is the env var for account tokens, but the secret in this repo is `RAILWAY_TOKEN`. This is harmless in our workflow (we don't use the CLI), but if anyone follows Railway's official CI quickstart they'll get conflicting advice.
- **Not searched**: Railway's status page and recent changelog for any April 2026 token-lifecycle policy changes.

---

## Recommendations

1. **Have the human inspect the Railway token-creation dashboard and report what expiration options actually exist.** The runbook's "No expiration" advice is uncorroborated. If the UI offers TTLs of {7 days, 30 days, 90 days, never} the operator may be selecting the wrong one each rotation. If "never" doesn't exist, the recurring rotations are unavoidable with the current token type.

2. **Try a workspace token as an alternative.** Railway officially flags workspace tokens as "Best For Team CI/CD, shared automation" — they're designed not to be tied to a single human's account lifecycle. This requires changing the validation query in `.github/workflows/staging-pipeline.yml` from `{me{id}}` (account-only) to `{__typename}` (works for both) so the validation doesn't reject the new token type. Confirmed by Railway moderator that `me` will fail for workspace tokens.

3. **Do not change to a project token.** Project tokens require the `Project-Access-Token` header instead of `Authorization: Bearer`, so adopting one would require restructuring all `curl` calls in the workflow, and they cannot run cross-environment GraphQL mutations the same way.

4. **Update `docs/RAILWAY_TOKEN_ROTATION_742.md`** to remove the unverified "TTL: No expiration" claim and instead document the actual options offered by the dashboard once a human verifies them. Note that the recurring failures suggest the current advice is not actually preventing re-expiration.

5. **Consistent with `CLAUDE.md` policy** (Railway Token Rotation section): this agent will NOT rotate the token or create a `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming success. The above recommendations are research output for the human operator and the implementation phase that follows.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API | Railway Docs | https://docs.railway.com/integrations/api | Token type taxonomy and headers |
| 2 | Using the CLI | Railway Docs | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env var semantics |
| 3 | Login & Tokens | Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth-only TTL info; no dashboard-token TTL documented |
| 4 | GraphQL "Not Authorized" for PAT | Railway Help Station | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | `me` query requires personal/account token |
| 5 | Token for GitHub Action | Railway Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account token recommended for GitHub Actions |
| 6 | RAILWAY_TOKEN invalid or expired | Railway Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | "Invalid or expired" frequently means wrong token *type* (CLI context) |
| 7 | CLI throwing "Unauthorized" | Railway Help Station | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Token scope confusion + corrupted local config |
| 8 | Incident Report Jan 28-29 2026 | Railway Blog | https://blog.railway.com/p/incident-report-january-26-2026 | Recent platform incident, not directly token-related |
