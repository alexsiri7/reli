# Web Research: fix #789

**Researched**: 2026-04-30T00:00:00Z
**Workflow ID**: dd6abcadab89d9cb7488949c7f296639

---

## Summary

Issue #789 is the 17th recurrence of the `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure in the staging-deploy workflow's "Validate Railway secrets" step. Railway documents four token types (Account, Workspace, Project, OAuth) and they use **different env vars and different HTTP headers** — the `{me{id}}` health-check query in `.github/workflows/staging-pipeline.yml` only works with an Account/Workspace token via `Authorization: Bearer …`, while community reports state that `RAILWAY_TOKEN` is now treated as a *Project* token and rejects Account tokens with "invalid or expired" even when freshly minted. Railway publishes no "no-expiration" toggle in its public docs; the only documented long-lived credentials are OAuth refresh tokens (1y, rotated). The recurring failure is therefore best explained by either token-type/header mismatch or short default TTLs, not a one-off rotation lapse.

---

## Findings

### 1. Railway has four token types with different scopes and headers

**Source**: [Public API | Railway Docs](https://docs.railway.com/guides/public-api)
**Authority**: Official Railway documentation
**Relevant to**: Why `RAILWAY_TOKEN` keeps being rejected — the validation step's auth header and GraphQL query may not match the token type that was rotated in.

**Key Information**:

- Four token categories: **Account Token** (all resources), **Workspace Token** (single workspace, recommended for "Team CI/CD, shared automation"), **Project Token** (single environment, recommended for "Deployments, service-specific automation"), **OAuth Token**.
- Account/Workspace/OAuth use `Authorization: Bearer <TOKEN>`.
- Project tokens use a **different header**: `Project-Access-Token: <TOKEN>` — they are NOT bearer-style.
- Verification queries differ by token type:
  - Account: `query { me { name email } }`
  - Workspace: `query { workspace(workspaceId: "…") { name id } }`
  - Project: `query { projectToken { projectId environmentId } }`
- The current workflow validates with `{me{id}}` and `Authorization: ***` — that combination **only works for Account or Workspace tokens**, never Project tokens.

---

### 2. `RAILWAY_TOKEN` env var is project-scoped; account tokens go in `RAILWAY_API_TOKEN`

**Source**: [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli) and [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway docs + Railway employee response in the help-station thread
**Relevant to**: The naming of the GitHub Actions secret in this repo — if a Railway-employee-recommended account-scoped token was placed under `RAILWAY_TOKEN` instead of `RAILWAY_API_TOKEN`, behavior is officially undefined.

**Key Information**:

- `RAILWAY_TOKEN` → "project-level" token, "project-level actions"
- `RAILWAY_API_TOKEN` → "account/workspace" token, "account-level actions"
- Railway employee guidance (Reply 1 of the help-station thread): "use a Railway API token scoped to the user account", set as `RAILWAY_API_TOKEN`.
- Project tokens are scoped to a single environment; multi-environment automation requires an account/workspace token.

---

### 3. "Invalid or expired" is frequently a token-type mismatch, not actual expiry

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway help station (community + staff responses)
**Relevant to**: Direct match for our failure mode — "RAILWAY_TOKEN is invalid or expired: Not Authorized".

**Key Information**:

- Direct quote: "RAILWAY_TOKEN now only accepts *project token*, if u put the normal account token...it literally says 'invalid or expired' even if u just made it 2 seconds ago." (community member `bytekeim`)
- Direct quote: "if u have RAILWAY_API_TOKEN set at the same time, delete it or rename it cuz RAILWAY_TOKEN wins and screws everything up if its wrong."
- Implication for issue #789: a freshly rotated token that is the *wrong type* (or stored under the wrong env var) will fail the validation step instantly with the exact error string we see — and look like an "expiration" event from CI logs alone.

---

### 4. Railway documents NO "no expiration" toggle; OAuth tokens are the only long-lived primitive and they rotate

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway docs
**Relevant to**: The repo's `RAILWAY_TOKEN_ROTATION_742.md` runbook tells humans to choose **Expiration: No expiration** when minting the new token — but this option is not described anywhere in current Railway docs we could find.

**Key Information**:

- OAuth access tokens: **1 hour** TTL (3600 s).
- OAuth refresh tokens: **1 year** TTL, rotated on use, max 100 per user authorization (oldest auto-revoked beyond 100).
- The dashboard token-creation flow for Account/Workspace/Project tokens is not described in the OAuth doc, and the Public API doc "does not address expiration policies or methods for creating non-expiring tokens" (per direct read of the page).
- **Gap**: We could not corroborate from official docs whether the dashboard's manual token-creation UI actually offers a "No expiration" option. The runbook's instruction may have been accurate when written but should be re-verified each rotation.

---

### 5. Modern CI/CD avoids long-lived secrets via OIDC — but Railway has no documented OIDC integration

**Source**: [GitHub Docs — OpenID Connect](https://docs.github.com/en/actions/concepts/security/openid-connect), [GitGuardian — Securing your CI/CD: an OIDC Tutorial](https://blog.gitguardian.com/securing-your-ci-cd-an-oidc-tutorial/), [Doppler — Managing secrets in CI/CD environments](https://www.doppler.com/blog/managing-secrets-ci-cd-environments-github-actions-advanced-techniques)
**Authority**: GitHub official docs + recognized DevOps blogs
**Relevant to**: Long-term fix candidates beyond "rotate again, this time really pick no-expiration".

**Key Information**:

- OIDC issues short-lived (per-job) tokens directly from GitHub Actions to the cloud provider — no stored long-lived secret. Documented for AWS, Azure, GCP, HashiCorp Vault.
- Railway is not listed in any GitHub OIDC integration guides we found, and no Railway docs reference OIDC federation.
- Doppler / Vault patterns: store the long-lived secret in a vault, fetch at job start, optionally rotate-on-deploy.
- General industry guidance: rotate manually-managed secrets every ≤ 90 days or move to OIDC/short-lived flows.

---

### 6. Reli's recurring-failure cadence is faster than the documented 1-year refresh-token TTL

**Source**: This repo's git log (commits `2fbf1e6`, `3bc1758`, `d21b401`, `841211c`, `bb69f77` plus issue body referencing "third occurrence" in `docs/RAILWAY_TOKEN_ROTATION_742.md`) and Issue #789 body
**Authority**: Repository history (authoritative for the pattern, not the cause)
**Relevant to**: Estimating how long the next rotation will hold.

**Key Information**:

- Issue #789 is the 17th occurrence; recent investigations (#779, #781, #783, #785, #786) all close as Railway-token expirations.
- This cadence (~weekly to bi-weekly based on commit dates) is much faster than 1y refresh tokens or even 90-day rotation hygiene.
- That cadence is consistent with either (a) tokens minted with the **default short TTL** Railway offers in the dashboard, or (b) tokens of the **wrong type** that fail immediately and get re-rotated as a no-op.

---

## Code Examples

### Validation query that matches an Account/Workspace token (current workflow)

```bash
# From [Railway Public API docs](https://docs.railway.com/guides/public-api)
curl --request POST \
  --url https://backboard.railway.com/graphql/v2 \
  --header 'Authorization: Bearer <ACCOUNT_OR_WORKSPACE_TOKEN>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"query { me { name email } }"}'
```

### Validation query that matches a Project token (would NOT work with current header)

```bash
# From [Railway Public API docs](https://docs.railway.com/guides/public-api)
curl --request POST \
  --url https://backboard.railway.com/graphql/v2 \
  --header 'Project-Access-Token: <PROJECT_TOKEN>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"query { projectToken { projectId environmentId } }"}'
```

### Reference workflow snippet from Railway's own blog

```yaml
# From [Using GitHub Actions with Railway (Railway blog)](https://blog.railway.com/p/github-actions)
jobs:
  deploy:
    runs-on: ubuntu-latest
    container: ghcr.io/railwayapp/cli:latest
    env:
      SVC_ID: my-service-id
      RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
    steps:
      - uses: actions/checkout@v3
      - run: railway up --service=${{ env.SVC_ID }}
```

Note: Railway's public blog post uses `RAILWAY_TOKEN` for a project token here, while their staff later (in the help-station thread) recommend `RAILWAY_API_TOKEN` for account-scoped tokens. Both can be valid; the choice dictates header and validation query.

---

## Gaps and Conflicts

- **No-expiration toggle**: The repo's `docs/RAILWAY_TOKEN_ROTATION_742.md` instructs humans to select "Expiration: No expiration" when minting the token. We could not find this option documented in any current Railway public docs page. Either (a) the option exists and is undocumented, (b) it was removed, or (c) the runbook's wording is wishful — needs visual confirmation by a human at https://railway.com/account/tokens.
- **Conflict on which env var to use**: Railway's blog post sets `RAILWAY_TOKEN` (project token), Railway's CLI docs distinguish `RAILWAY_TOKEN` (project) vs `RAILWAY_API_TOKEN` (account), and Railway staff in the help-station thread recommend `RAILWAY_API_TOKEN` for GitHub Actions. The right answer depends on whether the workflow needs cross-environment access.
- **Rotation cadence**: We could not find a documented default TTL for dashboard-minted Account/Workspace/Project tokens. The 17 recurrences in this repo strongly suggest a short default TTL or a configuration mismatch but we cannot confirm from public docs.
- **No Railway OIDC**: We found no documentation, blog post, or community thread describing a GitHub Actions → Railway OIDC federation path. If it exists, it is not surfaced by search.

---

## Recommendations

Based on research, in priority order:

1. **Verify token TYPE matches the workflow's validation query before re-rotating.** The "Validate Railway secrets" step uses `{me{id}}` with `Authorization: Bearer …`. That requires an **Account or Workspace token**. If the previous rotation produced a Project token (or used the Project-Access-Token header path mentally), it will fail with the exact "invalid or expired: Not Authorized" string we see — even at age zero. (Source: Railway help-station thread #59011e20.)
2. **Standardize on Workspace token + `RAILWAY_API_TOKEN`.** Railway staff guidance in the help-station thread points to an account-scoped token via `RAILWAY_API_TOKEN`. Workspace tokens are explicitly recommended for "Team CI/CD, shared automation". Renaming the secret avoids the documented `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` collision footgun.
3. **At rotation time, the human should screenshot the Railway dashboard's expiration field** and paste the chosen TTL into the rotation issue. If "No expiration" is not actually offered, the runbook should be corrected and a calendar-based rotation reminder added (a `/schedule`'d cleanup agent, for example) rather than waiting for CI to fail.
4. **Long-term: file a Railway support / feature-request asking about OIDC federation or documented long-lived CI tokens.** Until then, OIDC-style elimination of long-lived secrets is not available for Railway specifically.
5. **Do not** create another `.github/RAILWAY_TOKEN_ROTATION_*.md` from an agent — per `CLAUDE.md`, agents cannot rotate the token, and writing a doc claiming success is a Category 1 error. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs | https://docs.railway.com/guides/public-api | Authoritative list of token types, headers, and validation queries |
| 2 | Railway CLI docs | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env-var distinction |
| 3 | Railway OAuth Login & Tokens docs | https://docs.railway.com/integrations/oauth/login-and-tokens | Documented TTLs (1h access, 1y refresh, rotated) |
| 4 | Railway blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Reference workflow YAML using `RAILWAY_TOKEN` |
| 5 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Token-type mismatch produces our exact error string |
| 6 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Railway employee guidance: account-scoped via `RAILWAY_API_TOKEN` |
| 7 | GitHub Docs — OpenID Connect | https://docs.github.com/en/actions/concepts/security/openid-connect | Long-term replacement for stored long-lived secrets |
| 8 | GitGuardian — Securing your CI/CD: an OIDC Tutorial | https://blog.gitguardian.com/securing-your-ci-cd-an-oidc-tutorial/ | Industry pattern for short-lived CI credentials |
| 9 | Doppler — Managing secrets in CI/CD environments | https://www.doppler.com/blog/managing-secrets-ci-cd-environments-github-actions-advanced-techniques | Vault-backed rotate-on-deploy pattern |
| 10 | GitHub community discussion #168661 — Best Practices for Rotating Secrets | https://github.com/orgs/community/discussions/168661 | General rotation-cadence guidance (≤90 days) |
