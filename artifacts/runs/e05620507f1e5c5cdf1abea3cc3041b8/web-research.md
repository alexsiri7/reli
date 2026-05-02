# Web Research: fix #915 — Main CI red: Deploy to staging (RAILWAY_TOKEN expired)

**Researched**: 2026-05-02T19:50:00Z
**Workflow ID**: e05620507f1e5c5cdf1abea3cc3041b8

---

## Summary

Issue #915 is the 64th `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure. The
recurring nature is not bad luck: the staging-pipeline workflow authenticates to the Railway
GraphQL API using `Authorization: Bearer $RAILWAY_TOKEN` and validates with `{me{id}}`, both
of which require an **Account/Personal token** (or Workspace token). Railway documents three
distinct token types — Account, Workspace, and **Project** — and explicitly recommends the
Project Token for CI/CD because it is environment-scoped, uses a different header
(`Project-Access-Token: <token>`), and is purpose-built for unattended deployments. The
existing `docs/RAILWAY_TOKEN_ROTATION_742.md` runbook directs operators to
`https://railway.com/account/tokens` (the Account-token page), confirming the wrong token
class is in use. Switching to a Project token eliminates the rotation treadmill but requires
two changes to the workflow: swap the auth header, and replace the `{me{id}}` validation query
(which a Project token cannot execute) with a project-scoped probe.

---

## Findings

### Railway has three token types with different headers

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), corroborated by [Public API and Programmatic Access | DeepWiki](https://deepwiki.com/railwayapp/docs/6.2-public-api-and-programmatic-access)
**Authority**: Official Railway documentation; DeepWiki mirror of railwayapp/docs repo.
**Relevant to**: Root cause of the recurring expirations.

**Key Information**:

| Token Type | Header | Scope |
|---|---|---|
| Account / Personal | `Authorization: Bearer <TOKEN>` | All your resources and workspaces |
| Workspace / Team | `Authorization: Bearer <TOKEN>` (also `Team-Access-Token`) | Single workspace |
| **Project** | `Project-Access-Token: <TOKEN>` | A single environment within a project |

- "Project tokens use the `Project-Access-Token` header, **not** the `Authorization: Bearer` header used by account, workspace, and OAuth tokens."
- "Project tokens … provide the most restrictive access, limited to a single project environment, **making them ideal for CI/CD deployments**."

---

### `RAILWAY_TOKEN` only accepts a Project token — Account tokens return "invalid or expired"

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Official Railway community help forum; reproduced user reports plus staff guidance.
**Relevant to**: The exact error string the CI run logs (`Not Authorized`).

**Key Information**:

- Direct quote from a user thread: *"RAILWAY_TOKEN now only accepts **project token**, if u put the normal account token … it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- Recommended fix: generate the token from **project settings → Tokens** (not account settings), and remove any conflicting `RAILWAY_API_TOKEN` env var.
- Note: the Railway CLI distinguishes `RAILWAY_TOKEN` (project-scoped, for `railway up`-style deploys) from `RAILWAY_API_TOKEN` (account-scoped, for general API calls). Using the wrong class in the wrong slot is a documented footgun.

---

### Railway officially recommends Project tokens for GitHub Actions

**Source**: [Using GitHub Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions)
**Authority**: Railway's own engineering blog.
**Relevant to**: The pattern this repo's `staging-pipeline.yml` is implementing.

**Key Information**:

- "You can create a new project token on the **Settings** page of your project dashboard within the **Tokens** submenu."
- The blog tells users to put that project token into the GitHub secret named `RAILWAY_TOKEN` and reference it from the workflow.
- Project tokens "allow the CLI to access all the environment variables associated with a specific project and environment," which is exactly what unattended deploys need.

---

### Token expiration policy — what's documented vs. observed

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway docs.
**Relevant to**: Whether switching token types actually stops the bleeding.

**Key Information**:

- Railway's token-management docs **do not publish a TTL** for Account, Workspace, or Project tokens. The only documented expiration is on **OAuth access tokens (1 hour)**, which is a different code path (Login-with-Railway).
- Observed pattern in this repo (issues #733, #739, #742, … #903, #907, #909, #912, #915): Account tokens are being invalidated frequently — at minimum daily on heavy days (issue #909 noted 22 expirations in one day).
- Possible mechanisms (not confirmed by docs): tokens created with a non-zero TTL in the dashboard; tokens auto-revoked on session changes / new device sign-ins / 2FA events; or rate-limit-style server-side rejection. The Help Station thread above shows users hitting "invalid or expired" on tokens that are seconds old, suggesting it can also be a token-class mismatch rather than literal expiry.
- Project tokens, by contrast, are not tied to a user session and are not reported in community threads as expiring spontaneously when used with the correct header.

---

### The `{me{id}}` validation query is incompatible with a Project token

**Source**: Cross-reference of [Public API | Railway Docs](https://docs.railway.com/integrations/api) (token scopes) and [Postman: Railway GraphQL API](https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api).
**Authority**: Official schema reference + Railway docs.
**Relevant to**: A required workflow change once the token type flips.

**Key Information**:

- `me { id }` returns the authenticated **user**, which only exists for tokens tied to a Railway account (Account/Workspace/OAuth).
- A Project token has no associated user — it authenticates as a project/environment principal — so `{me{id}}` will return null/error even when the token is valid.
- A safer probe under a Project token is a project-scoped query, e.g. `{ projectToken { projectId environmentId } }` or simply attempting the `serviceInstanceUpdate`/`serviceInstanceDeploy` mutation in dry-run fashion.

---

### Adjacent fact: this repo's runbook points operators at the Account token UI

**Source**: Local file `docs/RAILWAY_TOKEN_ROTATION_742.md` (lines 24–26).
**Authority**: First-party project artifact.
**Relevant to**: Why the wrong token type keeps being installed.

**Key Information**:

- The runbook says: *"Create a new Railway token (requires Railway dashboard access at `https://railway.com/account/tokens`)"* — that URL is the **Account** token page.
- Recommendation: update the runbook to send operators to **Project Settings → Tokens** instead, or the next rotation will reproduce the bug.

---

## Code Examples

### What the workflow does today (account-token shape)

```bash
# From .github/workflows/staging-pipeline.yml:49-53
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
fi
```

### What it should look like with a Project token

```bash
# Header changes; validation must not rely on `me`
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}')
if ! echo "$RESP" | jq -e '.data.projectToken.projectId' > /dev/null 2>&1; then
  echo "::error::RAILWAY_TOKEN is invalid or wrong type"
fi
```

The deploy mutations themselves (`serviceInstanceUpdate`, `serviceInstanceDeploy`) work with
both token classes, but the **header must match the token class** — not Bearer for a project
token. Pattern derived from [DeepWiki: Public API and Programmatic Access](https://deepwiki.com/railwayapp/docs/6.2-public-api-and-programmatic-access).

---

## Gaps and Conflicts

- **Documented Project-token TTL**: Railway's official docs do not state in writing that
  Project tokens are non-expiring. The recommendation rests on (a) absence of any documented
  TTL, (b) the official blog/CI guidance pointing at Project tokens for unattended use, and
  (c) the absence of community reports of spontaneous Project-token expiry.
- **Why account tokens specifically expire so fast in this account**: not determinable from
  public docs. Could be TTL chosen at creation, an account security policy, 2FA/session
  rotation, or server-side revocation. Worth confirming with Railway support before relying
  on Project tokens to be permanent.
- **Conflicting community guidance**: one Help Station thread on `serviceInstanceRedeploy`
  errors says "for all mutations, one must use the ACCOUNT TOKEN" — this contradicts the
  official CI guidance and likely refers to mutations outside a single project's scope. For
  the two mutations this workflow uses (`serviceInstanceUpdate`, `serviceInstanceDeploy`,
  both with explicit `serviceId` + `environmentId`), Project tokens are documented to work.
- **Whether any non-API switch could help**: e.g. moving deploys to `railway up` via the
  official CLI action would still need a token; it does not change the underlying class
  problem.

---

## Recommendations

Based on research:

1. **Switch `RAILWAY_TOKEN` to a Project token, not an Account token.** Generate it from
   *Project Settings → Tokens* in the Railway dashboard for the staging project, then again
   for the production project (project tokens are environment-scoped — a single token cannot
   cover both staging and production unless they share an environment). Store as
   `RAILWAY_STAGING_TOKEN` / `RAILWAY_PRODUCTION_TOKEN` GitHub secrets so the two
   environments are independent.
2. **Update `.github/workflows/staging-pipeline.yml`** to send `Project-Access-Token: $TOKEN`
   instead of `Authorization: Bearer $TOKEN` on every Railway API call (validation step plus
   both deploy steps, in both the staging and production jobs — six call sites total).
3. **Replace the `{me{id}}` validation query** with a project-scoped probe such as
   `{ projectToken { projectId environmentId } }`. The current query is guaranteed to fail
   under a Project token even when the token is healthy, so leaving it in place would just
   move the false-positive failure from "expired" to "rejected."
4. **Fix the operator runbook** (`docs/RAILWAY_TOKEN_ROTATION_742.md`) to point at the
   Project Tokens UI, not `https://railway.com/account/tokens`. Otherwise the next rotation
   will silently reintroduce the wrong token class.
5. **Avoid** any "create the token with No expiration in the account UI" workaround. Even if
   such a setting exists, Account tokens are not the right class for this workflow per
   Railway's own CI guidance — the symptom would return under a different trigger
   (workspace change, security event, etc.).
6. **Out of scope for this issue but worth flagging**: this is the 64th occurrence. Per
   `CLAUDE.md`, agents cannot rotate the token themselves — the actual rotation requires a
   human at railway.com. The fix above is what an agent *can* PR; the human still has to
   generate the new Project token and install it as the GitHub secret.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Authoritative description of the three token types and their headers |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | Token lifecycle; documents 1h OAuth TTL only |
| 3 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Confirms `RAILWAY_TOKEN` slot rejects Account tokens with the exact error in this issue |
| 4 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Official guidance: generate the token from Project Settings → Tokens for CI |
| 5 | Railway Docs — GitHub Actions Self-Hosted Runners | https://docs.railway.com/guides/github-actions-runners | Adjacent: principle-of-least-privilege guidance for CI tokens |
| 6 | DeepWiki — Public API and Programmatic Access | https://deepwiki.com/railwayapp/docs/6.2-public-api-and-programmatic-access | Cross-check of header/scope table for all token types |
| 7 | Postman — Railway GraphQL API | https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api | Schema reference for `me`, `projectToken`, `serviceInstance*` shapes |
| 8 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Community-confirmed end-to-end Project-token + GitHub Actions setup |
| 9 | Railway Help Station — Error: Project Token Not Found in GitHub Actions | https://station.railway.com/questions/error-project-token-not-found-when-dep-391b52a3 | Adjacent failure mode if the token class is right but env-scoping is wrong |
