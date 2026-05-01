# Web Research: fix #841

**Researched**: 2026-05-01T12:03:50Z
**Workflow ID**: 8531a0fb983e22588f40e6f43484ee47
**Issue**: #841 — "Prod deploy failed on main" (Railway staging deploy fails with `RAILWAY_TOKEN is invalid or expired: Not Authorized`)

---

## Summary

Issue #841 is the 34th+ recurrence of a `RAILWAY_TOKEN` "Not Authorized" failure in this repo. Public Railway documentation does **not** describe any TTL for project, account, or workspace tokens — so the existing rotation runbook's claim of a "1-day or 7-day default TTL" is unverified by official sources. The much more strongly attested cause across Railway's own docs and Help Station threads is **token-type / scope mismatch**: `RAILWAY_TOKEN` only accepts a true *Project Token* (created in project settings → Tokens), while a token created at `/account/tokens` is either an account-scoped or workspace-scoped token and the CLI returns "invalid or expired" against it even when freshly minted. For GitHub Actions, Railway's own deploying-with-CLI page now uses `RAILWAY_API_TOKEN` (account-scoped, workspace field left blank) in its examples.

---

## Findings

### 1. Railway has four distinct token types — they are not interchangeable

**Source**: [Public API — Railway Docs](https://docs.railway.com/reference/integrations)
**Authority**: Official Railway documentation
**Relevant to**: Root cause investigation; runbook accuracy

**Key Information**:

- **Account Token** — "If you select 'No workspace', the token will be tied to your Railway account." Recommended for "Personal scripts, local development."
- **Workspace Token** — "Select a specific workspace in the dropdown to create a token scoped to that workspace." Recommended for "Team CI/CD, shared automation."
- **Project Token** — "can only be used to authenticate requests to that environment." Recommended for "Deployments, service-specific automation."
- **OAuth tokens** — separate flow.
- Account/workspace/OAuth tokens use `Authorization: Bearer` header; **project tokens use a different header — `Project-Access-Token`**. This is why a wrongly-typed token fails authorization.

---

### 2. `RAILWAY_TOKEN` ONLY accepts a Project Token (not an account token)

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway's official user forum, including a clarification consistently echoed by Railway employees
**Relevant to**: Likely root cause of the 34× recurring failure

**Key Information**:

- Direct quote: *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token (the one u make in account settings) it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- Project tokens are generated at **project settings → Tokens** (not at `https://railway.com/account/tokens`).
- If both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` are set, `RAILWAY_TOKEN` takes priority — a wrong `RAILWAY_TOKEN` will mask a correct `RAILWAY_API_TOKEN`.

---

### 3. Workspace-vs-account-scope gotcha at `/account/tokens`

**Source**: [RAILWAY_API_TOKEN not Working — Railway Help Station](https://station.railway.com/questions/railway-api-token-not-working-2083f58a) (resolved 2026-01-21)
**Authority**: Railway employee "brody" provided the fix; user confirmed working
**Relevant to**: A second known cause of "Not Authorized" with a fresh token

**Key Information**:

- Direct quote (brody, Railway): *"For the resources you are trying to use, you would need to use an account-scoped token, not a workspace-scoped token."*
- Resolution: at `https://railway.com/account/tokens`, leave the **Workspace field blank** to create an account-scoped token. Selecting your workspace silently produces a workspace-scoped token that fails for many CLI/API operations.
- Issue date: 2026-01-21 — within the last few months, so this gotcha is current.

---

### 4. Railway's own GitHub Actions example uses `RAILWAY_API_TOKEN`, not `RAILWAY_TOKEN`

**Source**: [Deploying with the CLI — Railway Docs](https://docs.railway.com/cli/deploying); [Token for GitHub Action — Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway docs + Railway employee statement
**Relevant to**: Whether the reli workflow is using the right env var

**Key Information**:

- Railway's PR-environment example uses `RAILWAY_API_TOKEN: ${{ secrets.RAILWAY_API_TOKEN }}` and notes: *"ensure the token is scoped to your account, not a specific workspace"*.
- Railway employee on Help Station: *"use a Railway API token scoped to the user account, not a project token, for the GitHub Action."*
- Project Tokens can perform: `railway up`, `railway redeploy`, `railway logs`. They **cannot** create environments, link projects, or do anything cross-environment — useful guardrail for deploy-only workflows.
- Project Token compatibility note: an older CLI bug (pre-4.5.0) caused `RAILWAY_API_TOKEN` to be ignored, forcing a fallback to `RAILWAY_TOKEN`. Fixed in CLI 4.5.0+ ([railwayapp/cli#668](https://github.com/railwayapp/cli/pull/668/)).

---

### 5. No documented TTL on Project, Account, or Workspace tokens

**Sources**: [Login & Tokens — Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens); [Public API — Railway Docs](https://docs.railway.com/reference/integrations); [Using GitHub Actions with Railway](https://blog.railway.com/p/github-actions)
**Authority**: All three are official Railway sources
**Relevant to**: Validates/invalidates the existing runbook's "default TTL" claim

**Key Information**:

- The Login & Tokens doc only documents expirations for **OAuth** tokens: access tokens expire in 1 hour; refresh tokens have a "fresh one-year lifetime from the time of issuance" and rotate.
- The Public API page describing Project / Account / Workspace tokens **mentions no TTL or expiration policy** at all.
- The blog post on GitHub Actions integration likewise does not mention an expiration.
- **Implication**: The reli runbook's note that "the default TTL may be short (e.g., 1 day or 7 days)" appears to be folklore — there is no public evidence of a user-selectable TTL on these token types, and "No expiration" is not visibly an option in the public docs. If repeated expirations are real, they are likely caused by something other than a TTL the user is forgetting to override (e.g., scope mismatch, workspace deletion/rotation, an undocumented session invalidation).

---

### 6. Open upstream issue: tokens rejected by API directly (not just CLI)

**Source**: [railwayapp/cli#699 — CLI authentication fails with valid API token on Linux](https://github.com/railwayapp/cli/issues/699)
**Authority**: Railway's own CLI repo; opened 2025-11-21, status open as of last fetch
**Relevant to**: Indicates Railway has had real auth-side regressions recently

**Key Information**:

- User reproduced failure by hitting `https://backboard.railway.app/graphql/v2` directly with the token; got `{"errors":[{"message":"Not Authorized"…}]}`.
- Authentication failure is at the **API layer**, not the CLI client.
- No Railway team response or fix as of last fetch — so users have been seeing legitimate token-rejection bugs upstream during this window.

---

### 7. Community alternative for token rotation automation

**Source**: [0xdps/railway-secrets on GitHub](https://github.com/0xdps/railway-secrets)
**Authority**: Community project; not official Railway
**Relevant to**: Long-term mitigation if rotations remain manual

**Key Information**:

- Self-hosted PHP dashboard that "rotate Railway environment variables with AES-256-GCM encryption."
- Rotation runs via crond inside a container, with per-secret interval logic.
- Note: this rotates **app environment variables in Railway**, not the auth token itself — so it is partial coverage.

---

### 8. OIDC alternative: not yet available for Railway

**Sources**: [GitHub OpenID Connect docs](https://docs.github.com/en/actions/concepts/security/openid-connect); [Securing CI/CD with OIDC — Amplify Security](https://amplify.security/blog/securing-ci/cd-dont-use-long-lived-api-tokens-use-openid-connect-instead)
**Authority**: GitHub official + security industry blog
**Relevant to**: Best-practice north star

**Key Information**:

- The cloud-native pattern is to **drop long-lived tokens entirely**: GitHub Actions presents an OIDC identity, and the cloud provider issues a short-lived token scoped to one job.
- Railway supports OAuth/OIDC for *Login with Railway* (third-party apps logging in as a Railway user), but no public docs describe a GitHub-Actions ↔ Railway OIDC trust relationship that would replace `RAILWAY_TOKEN`.
- Conclusion: **OIDC is not a viable workaround today** — the workflow has to keep handling some long-lived secret, but should reduce rotation surface area (correct token type, correct scope).

---

## Code Examples

### Recommended GitHub Actions snippet (from Railway docs, simplified)

```yaml
# From Railway's official "Deploying with the CLI" page
# https://docs.railway.com/cli/deploying
- name: Deploy to Railway
  env:
    RAILWAY_API_TOKEN: ${{ secrets.RAILWAY_API_TOKEN }}
  run: railway up --service my-service
```

### How a Project Token differs at the wire level

```http
# Project Token — uses dedicated header (NOT Authorization: Bearer)
POST /graphql/v2 HTTP/1.1
Host: backboard.railway.app
Project-Access-Token: <project-token>

# Account / Workspace Token — uses standard bearer
POST /graphql/v2 HTTP/1.1
Host: backboard.railway.app
Authorization: Bearer <account-token>
```

Source: [Public API — Railway Docs](https://docs.railway.com/reference/integrations)

---

## Gaps and Conflicts

- **Gap (significant)**: Railway's public docs do not state any expiration / TTL policy for Project, Account, or Workspace tokens. The reli runbook's "1 day / 7 day default TTL" guidance is not corroborated by any source found and may not reflect the actual UI today.
- **Gap**: No official docs confirm whether a workspace-scoped token tracks a workspace's billing/admin lifecycle (e.g., gets invalidated when seat counts change, when admins rotate, etc.). This would be a plausible explanation for repeated "valid this week, invalid next week" behavior.
- **Conflict**: The current reli runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) instructs creating the token at `https://railway.com/account/tokens`. That URL produces account or workspace tokens, **not** Project Tokens. But the workflow uses the env var `RAILWAY_TOKEN`, which Help Station threads explicitly say only accepts Project Tokens. This mismatch alone could cause "invalid or expired" on a freshly minted token.
- **Currency caveat**: Several Help Station threads cited are from late 2025 / early 2026; Railway has been actively shipping changes in this area, so behavior may shift again.

---

## Recommendations

Based on research, the following changes would address the recurring symptom directly, ranked by confidence:

1. **Switch the workflow env var to `RAILWAY_API_TOKEN` and the secret to an account-scoped token created with the Workspace field BLANK** at `https://railway.com/account/tokens`. This is what Railway's own docs and a Railway employee both recommend for GitHub Actions ([Deploying with the CLI](https://docs.railway.com/cli/deploying); [Help Station thread](https://station.railway.com/questions/token-for-git-hub-action-53342720)). High confidence this resolves "Not Authorized" episodes that are actually scope-mismatch.

2. **Alternatively, keep `RAILWAY_TOKEN` but rotate it from the right place — project settings → Tokens, not the account page.** If rotations are happening at `/account/tokens`, the token type is wrong and rejection is expected even when fresh ([Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)).

3. **Update `docs/RAILWAY_TOKEN_ROTATION_742.md`** to (a) drop the unverified TTL claim, (b) document the workspace-blank requirement, (c) make the `RAILWAY_TOKEN` (Project Token, project settings) vs `RAILWAY_API_TOKEN` (account token, workspace blank) distinction explicit, and (d) name which one this repo uses.

4. **Pin a recent Railway CLI version** (≥4.5.0; current is 4.26.0) in CI to avoid the historical bug where `RAILWAY_API_TOKEN` was silently ignored ([railwayapp/cli#668](https://github.com/railwayapp/cli/pull/668/)).

5. **Add a pre-flight token sanity check** to the workflow that calls a cheap authenticated endpoint and fails fast with a clear error pointing at the rotation runbook — turning the 34th expiration into a one-line diagnostic instead of a deploy failure.

6. **Do not pursue OIDC for Railway today** — Railway does not appear to offer a GitHub Actions OIDC trust path; revisit if Railway publishes one.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/reference/integrations | Definitive source on the four token types and headers |
| 2 | Deploying with the CLI — Railway Docs | https://docs.railway.com/cli/deploying | Official GitHub Actions example uses `RAILWAY_API_TOKEN` |
| 3 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | Confirms only OAuth tokens have documented expiration |
| 4 | Using GitHub Actions with Railway — Railway Blog | https://blog.railway.com/p/github-actions | Walkthrough; uses Project Token for `railway up` |
| 5 | Using the CLI — Railway Docs | https://docs.railway.com/guides/cli | CLI auth modes overview |
| 6 | RAILWAY_TOKEN invalid or expired — Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | "RAILWAY_TOKEN now only accepts project token" |
| 7 | RAILWAY_API_TOKEN not Working — Help Station | https://station.railway.com/questions/railway-api-token-not-working-2083f58a | Workspace-blank fix, employee-confirmed (2026-01-21) |
| 8 | RAILWAY_API_TOKEN not being respected — Help Station | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Confirms scope-vs-env-var mismatch pattern |
| 9 | CLI throwing "Unauthorized" with RAILWAY_TOKEN — Help Station | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Token-type mismatch + config corruption causes |
| 10 | Token for GitHub Action — Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Railway employee: use account-scoped `RAILWAY_API_TOKEN` |
| 11 | railwayapp/cli#699 — CLI auth fails with valid token | https://github.com/railwayapp/cli/issues/699 | Active upstream auth bug (Nov 2025, still open) |
| 12 | railwayapp/cli#668 — CLI 4.5.0 fix for `RAILWAY_API_TOKEN` | https://github.com/railwayapp/cli/pull/668/ | Historical bug; pin CLI ≥4.5.0 |
| 13 | 0xdps/railway-secrets | https://github.com/0xdps/railway-secrets | Community rotation tool (rotates app vars, not auth token) |
| 14 | OpenID Connect — GitHub Docs | https://docs.github.com/en/actions/concepts/security/openid-connect | OIDC pattern background |
| 15 | Securing CI/CD with OIDC — Amplify Security | https://amplify.security/blog/securing-ci/cd-dont-use-long-lived-api-tokens-use-openid-connect-instead | Best-practice rationale for moving off long-lived tokens |
