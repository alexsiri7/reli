# Web Research: fix #860

**Researched**: 2026-05-02T00:00:00Z (date of writing)
**Workflow ID**: 31b45d722d1961ae59edfe9b72e7cf08

---

## Summary

Issue #860 is the **41st** consecutive `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure on the prod deploy pipeline, blocked at the "Validate Railway secrets" pre-flight that issues a `{me{id}}` GraphQL probe to `https://backboard.railway.app/graphql/v2` with an `Authorization: Bearer` header. Web research surfaces two structural fixes the existing rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) does not address: (a) the `me { id }` query and `Authorization: Bearer` header only work with **account/personal tokens** — not the project tokens that `RAILWAY_TOKEN` is documented for — and Railway support has explicitly stated personal tokens must be generated with **"No workspace"** selected to avoid silent rejection; (b) Railway provides **no OIDC/federated** alternative to long-lived tokens, so the only durable mitigations are creating a non-expiring account token and adding a **proactive weekly health check** (already present at `.github/workflows/railway-token-health.yml`) so rotations happen ahead of a prod deploy, not on top of one. The root cause is a procedural/configuration mismatch — not a Railway platform bug — and the fix has to be human-driven each time.

---

## Findings

### 1. The validator's `{me{id}}` query requires an **account/personal token**, not a project token

**Source**: [Public API | Railway Docs](https://docs.railway.com/guides/public-api)
**Authority**: Official Railway documentation
**Relevant to**: Diagnosing whether the secret stored as `RAILWAY_TOKEN` is the right *type* of token

**Key Information**:

- Railway has four auth methods: **account tokens**, **workspace tokens**, **project tokens**, and **OAuth tokens**.
- Header convention is **type-dependent**:
  - Account / workspace / OAuth → `Authorization: Bearer <TOKEN>`
  - Project → `Project-Access-Token: <TOKEN>` (NOT `Authorization: Bearer`)
- The `query { me { id email } }` GraphQL query "cannot be used with workspace or project tokens because the data returned is scoped to your personal account" — only **personal/account access tokens** can resolve `me`.
- Reli's `.github/workflows/staging-pipeline.yml` validator uses `Authorization: ***` + `{me{id}}` against `backboard.railway.app/graphql/v2`. That probe shape implies the secret in `RAILWAY_TOKEN` must be an **account token** for validation to pass.

**Implication**: If the rotator ever pastes a project token (or a workspace token) into `RAILWAY_TOKEN`, the validator will return `Not Authorized` even with a brand-new, non-expired token. This is consistent with the recurring "rotated yesterday, broken today" pattern.

---

### 2. Railway support: account tokens must be created with **"No workspace"** selected

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Official Railway support thread (resolved)
**Relevant to**: How the token must be created in the dashboard

**Key Information**:

- "Personal API tokens should grant full access to your personal resources. However, some users have reported that personal API tokens don't work with the GraphQL endpoint."
- The thread's resolved fix: navigate to **personal Account Settings** (not project settings), generate a new token, **explicitly select "No workspace"** rather than the default workspace.
- Tokens silently authenticate against a different scope when bound to a workspace — they will not satisfy `me { id }` queries.

**Implication**: The Reli rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) tells the human to "Create a new Railway token … Name: `github-actions-permanent`, Expiration: No expiration" but does **not** tell them to select "No workspace". Adding this step will likely eliminate the most common silent failure mode.

---

### 3. Railway Help Station explicit confirmation: `RAILWAY_TOKEN` and account tokens are not interchangeable

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway support thread (multiple confirmed resolutions)
**Relevant to**: Naming conflict between Reli's secret and the CLI's expected token type

**Key Information**:

- A Railway user states: *"RAILWAY_TOKEN now only accepts project token; if u put the normal account token … it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- For CLI-level CI/CD use, Railway's docs prescribe:
  - `RAILWAY_TOKEN` → **project token** (`railway up` style deploys, scoped to one environment)
  - `RAILWAY_API_TOKEN` → **account or workspace token** (cross-project / account-level operations)
- If both are set, `RAILWAY_TOKEN` takes precedence in the CLI.

**Implication**: There is a **naming conflict** in Reli's setup. The validator script needs an account token (because it queries `me`), but the env var it uses (`RAILWAY_TOKEN`) is the slot the Railway CLI expects to be a project token. The current pipeline works only because the validator hits the GraphQL API directly via `curl`, not via the CLI. If the team ever introduces `railway up` or `railway redeploy`, the same secret will mysteriously fail. The cleaner long-term fix is to rename the secret to `RAILWAY_API_TOKEN` for the validator and switch to `Project-Access-Token` + project tokens for the actual deploy steps.

---

### 4. Token expiration is **set at creation time**; default is not "no expiration"

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway documentation + support thread
**Relevant to**: Why expiration keeps recurring (41 incidents)

**Key Information**:

- Railway's published docs only describe the OAuth path explicitly: **"Access tokens expire after one hour."** Refresh tokens have a 1-year rolling lifetime when issued with `offline_access`.
- For account / workspace / project tokens (the dashboard-generated kind used in CI), Railway docs do **not** publish a default TTL. The dashboard UI offers an expiration picker, and selecting "No expiration" is required to get a permanent token.
- Reli's existing runbook captures this: *"the default TTL may be short (e.g., 1 day or 7 days). Previous rotations may have used these defaults. The new token must be created with 'No expiration'."* Yet the issue keeps recurring 41 times — strong signal the human is either (a) missing the "No expiration" toggle on rotation, (b) creating a workspace-bound token that is silently rejected, or (c) the token is being revoked by Railway for an unrelated reason (workspace change, account event, refresh-token rotation).

**Implication**: The dashboard step is the failure point. The runbook needs more defensive checks — ideally, after pasting the new token into the GitHub secret, the human should run `gh workflow run railway-token-health.yml` immediately (the health check workflow already exists in this repo) and verify the **next scheduled** Monday run also passes, before considering the rotation done.

---

### 5. Refresh-token rotation can silently revoke an entire authorization chain

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: An alternative explanation for unexpected expirations (OAuth-derived tokens only)

**Key Information**:

- Refresh tokens are rotated for security. *"If your user's authorization is suddenly revoked when using a refresh token, you likely used an old, already-rotated token. As a security measure, using a rotated refresh token immediately revokes the entire authorization."*
- Each user authorization can have a maximum of 100 refresh tokens; oldest are auto-revoked beyond that.

**Implication**: This applies only if the GitHub-secret token was provisioned via Railway's OAuth flow (with `offline_access`). Dashboard-generated personal access tokens are a different code path. Worth confirming during rotation that the token in use is a **dashboard PAT**, not an OAuth-derived access token.

---

### 6. Railway does **not** support GitHub OIDC federation — no zero-rotation path today

**Source**: [GitHub OIDC docs](https://docs.github.com/en/actions/concepts/security/openid-connect), [Railway docs (no OIDC entry found)](https://docs.railway.com/integrations/api)
**Authority**: GitHub official docs + absence of any matching Railway OIDC documentation
**Relevant to**: Whether long-lived `RAILWAY_TOKEN` can be replaced entirely

**Key Information**:

- GitHub Actions supports OIDC for AWS, Azure, GCP, HashiCorp Vault, etc. — a job receives a short-lived JWT, and the cloud provider exchanges it for a per-job access token, eliminating long-lived secrets.
- A search for Railway-specific OIDC integration returns **no results**. Railway has no `id-token` exchange endpoint and is not in GitHub's documented OIDC cloud provider list.
- Railway's only published CI auth pattern is "store a long-lived token as a GitHub secret".

**Implication**: Until Railway ships OIDC, the long-lived token *will* keep needing rotation. The leverage points are (a) make the token last as long as Railway allows ("No expiration"), (b) detect expiry early via the existing weekly health-check cron, and (c) fail loudly with a clear runbook pointer (the validator already does this). Replacing with OIDC is not currently possible.

---

### 7. The `backboard.railway.app` vs `backboard.railway.com` host distinction

**Source**: [Public API | Railway Docs](https://docs.railway.com/guides/public-api), multiple Help Station threads
**Authority**: Official docs + community confirmation
**Relevant to**: Whether the validator's URL is contributing to errors

**Key Information**:

- One thread asserts the "correct" endpoint is `https://backboard.railway.com/graphql/v2`; others (and many production examples) successfully use `https://backboard.railway.app/graphql/v2`.
- Both hostnames currently resolve to Railway's GraphQL gateway; the `.app` variant has been the historical canonical form. There is **no evidence** that the host choice is causing the `Not Authorized` errors here — the same workflow has succeeded against `.app` many times.
- Worth a future hardening pass to switch to `.com` for forward-compat, but this is not the root cause of #860.

**Implication**: Out of scope for the current fix. Mention only as a future cleanup.

---

## Code Examples

The recommended dual-token pattern from Railway's official guide (relevant if the team ever splits validator-vs-deploy roles):

```yaml
# From https://docs.railway.com/guides/public-api
# Validator step (account/workspace token)
- name: Validate Railway secrets
  env:
    RAILWAY_API_TOKEN: ${{ secrets.RAILWAY_API_TOKEN }}
  run: |
    curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
      -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"query":"{ me { id } }"}'

# Deploy step (project token)
- name: Deploy
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_PROJECT_TOKEN }}
  run: railway up --service=$SVC_ID
```

---

## Gaps and Conflicts

- **Default TTL for dashboard-generated PATs is undocumented.** Railway docs publish OAuth TTLs (1 hour access / 1 year refresh) but not the default for personal access tokens created via `https://railway.com/account/tokens`. Empirically the Reli incident pattern (~weekly) suggests a 7-day default if "No expiration" is not selected, but this is inferred, not confirmed.
- **Conflicting reports on whether personal tokens work with the GraphQL `me` query.** Railway's own docs say `me` only works for personal/account tokens; one Help Station thread reports personal tokens *don't* work with GraphQL. The resolved fix in that thread was to create the token with **"No workspace"** selected — suggesting the report was a workspace-binding mismatch, not a fundamental incompatibility.
- **No first-party Railway statement on tokens being silently revoked outside expiration.** Several community reports describe "valid yesterday, invalid today" without a clear cause. We could not find a published cause list from Railway.
- **`.app` vs `.com` host:** community guidance is mixed; official docs use both in different pages. Not the cause of #860 but worth a cleanup pass.

---

## Recommendations

Based on research, the fix for #860 itself is unchanged from the existing process — **a human must rotate `RAILWAY_TOKEN` via the Railway dashboard**, since agents cannot perform this action (per `CLAUDE.md`). Beyond the immediate rotation, the research suggests three durable improvements that would reduce recurrence below the current ~weekly cadence:

1. **Update the rotation runbook to require two non-default settings, not one.** `docs/RAILWAY_TOKEN_ROTATION_742.md` already says "Expiration: No expiration". Add: **"Workspace: No workspace"** (Finding #2). Both must be set, or the validator's `me { id }` probe will fail.

2. **Add a post-rotation verification step that runs the health-check workflow before closing the issue.** The repo already has `.github/workflows/railway-token-health.yml` (per `DEPLOYMENT_SECRETS.md`). The runbook should require: after `gh secret set RAILWAY_TOKEN`, run `gh workflow run railway-token-health.yml --repo alexsiri7/reli` and wait for green before re-running the failed deploy. This catches workspace-binding errors immediately rather than at the next prod deploy.

3. **Do not attempt OIDC migration.** Railway does not support GitHub OIDC federation as of this research (Finding #6). The long-lived-token pattern is the only path Railway publishes. The recurring rotation pain is a Railway product gap, not a Reli configuration error — the only meaningful mitigation is detect-early (health check) + rotate-correctly (runbook).

4. **Avoid touching the `Authorization` header / endpoint.** The validator's choice of `Authorization: Bearer` + `{me{id}}` against `backboard.railway.app` is correct for an account token (Finding #1). Don't switch to `Project-Access-Token` — that would break validation. Optional: switch host to `backboard.railway.com` in a future cleanup, but not in this fix (Finding #7).

Per `CLAUDE.md`'s Railway Token Rotation policy, the agent's role on #860 is to **file/investigate, not rotate**. This research informs the human handoff and proposes runbook improvements that can be merged independently.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/guides/public-api | Authoritative on token types, headers, scopes |
| 2 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth TTLs, refresh-rotation revocation behavior |
| 3 | Using the CLI — Railway Docs | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env-var semantics |
| 4 | RAILWAY_TOKEN invalid or expired — Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Confirms `RAILWAY_TOKEN` only accepts project tokens at the CLI layer |
| 5 | API Token "Not Authorized" — Help Station | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | "No workspace" selection is required for personal tokens to satisfy `me` queries |
| 6 | Token for GitHub Action — Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account-scoped token recommendation for GitHub Actions |
| 7 | Using GitHub Actions with Railway — Railway Blog | https://blog.railway.com/p/github-actions | Official walkthrough; confirms no published rotation guidance |
| 8 | Unable to Generate API Token with Deployment Permissions — Help Station | https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12 | Confirms project-token deploy-permission limits |
| 9 | OpenID Connect — GitHub Docs | https://docs.github.com/en/actions/concepts/security/openid-connect | Establishes that OIDC federation is the zero-rotation pattern (not available for Railway) |
| 10 | CLI authentication fails with valid API token on Linux — railwayapp/cli #699 | https://github.com/railwayapp/cli/issues/699 | Background on token-auth failure modes in Railway CLI |
