# Web Research: fix #896

**Researched**: 2026-05-02T11:30:00Z
**Workflow ID**: e8c76f128bf0299ed89d2f4ac237a1fa
**Issue**: alexsiri7/reli#896 — "Prod deploy failed on main"
**Failing job**: `Deploy to staging → Validate Railway secrets`
**Error**: `RAILWAY_TOKEN is invalid or expired: Not Authorized`

---

## Summary

This is a recurring `RAILWAY_TOKEN` rejection (the runbook in `docs/RAILWAY_TOKEN_ROTATION_742.md` cites prior occurrences #733/#739, and recent commits show ~15 same-day repeats and 56+ total). Per Railway's own documentation, API tokens (account/workspace/project) are designed to be **long-lived and persist until manually revoked** — they do not have a default TTL. The error message "invalid or expired" is documented in the Railway Help Station as **frequently misleading**: the most common root causes are (a) token-type mismatch with the env var name, (b) conflicting `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` set simultaneously, and (c) workspace/account scope mismatch. Before the next rotation, the team should verify what token type the workflow actually requires and whether the validation query (`{me{id}}`) is even compatible with that token type.

---

## Findings

### 1. Railway Token Types and Scope

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Choosing the correct token for `RAILWAY_TOKEN` GitHub Actions secret

**Key Information**:

Railway offers three distinct API token types:

| Type | Scope | Best For |
|------|-------|----------|
| **Account Token** | All resources and workspaces tied to your Railway account | Personal automation; Railway warns "do not share this token" |
| **Workspace Token** | A single workspace; cannot access personal resources or other workspaces | Team CI/CD, shared automation |
| **Project Token** | A single environment within a project | Deployments, service-specific automation |

The official docs do **not** document a default expiration TTL for any of these three types. They are presented as persistent credentials.

---

### 2. Token Lifetime — API Tokens vs OAuth Tokens

**Source**: [Login & Tokens — Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway OAuth documentation
**Relevant to**: Whether tokens "auto-expire" and whether a "no expiration" option is configurable

**Key Information**:

- **OAuth access tokens**: 1-hour TTL (used by browser/SDK auth flows, not GitHub Actions).
- **OAuth refresh tokens**: 1-year lifetime, automatically rotated on use. **Critical security note**: "If your user's authorization is suddenly revoked... you likely used an old, already-rotated token. As a security measure, using a rotated refresh token immediately revokes the entire authorization."
- **Account/workspace/project API tokens**: documentation does **not** describe an expiration policy, suggesting they are non-expiring until manually revoked. There is no documented "no expiration" toggle in the create-token UI — the docs imply tokens are simply long-lived by default.

This contradicts the assumption in `docs/RAILWAY_TOKEN_ROTATION_742.md` that "the new token must be created with 'No expiration'" — that toggle is not documented to exist on Railway. (It may exist in the UI; the rotation runbook should be re-verified next time a human accesses the dashboard.)

---

### 3. The "Invalid or Expired" Error Is Often Misleading

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Community Q&A with input from Railway users (incl. `bytekeim` who is active on the platform)
**Relevant to**: Root-causing why the same error keeps recurring after rotation

**Key Information** (direct quote):

> "RAILWAY_TOKEN now only accepts *project token*. If u put the normal account token... it literally says 'invalid or expired.'"

Additional documented causes:

- **Conflict between env vars**: If both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` are set simultaneously, `RAILWAY_TOKEN` takes precedence and may cause auth failures.
- **Token type mismatch**: Recreating the *same wrong type* of token will keep failing with the same error.
- The error label "expired" is often a generic catch-all for any auth failure, not literal expiration.

---

### 4. Conflicting Guidance — Account Token vs Project Token for GitHub Actions

This is a **gap/conflict** worth flagging.

**Source A**: [Using GitHub Actions with Railway (official blog)](https://blog.railway.com/p/github-actions)
- Recommends **project token** stored as `RAILWAY_TOKEN`.
- Example workflow uses `RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}` with `railway up --service=...`.
- Project tokens are created from **project settings → Tokens** (NOT account settings).

**Source B**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
- Railway employee `brody` says: "You need to use an **account-scoped token**" — created at https://railway.com/account/tokens.
- Reasoning: project tokens are scoped to a single environment and **don't support creating preview environments** or multi-env CLI operations.

**Source C**: [Authentication not working with RAILWAY_TOKEN — Railway Help Station](https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7)
- Community answer: "you have to use your account/team's token, not project token, and export it via `RAILWAY_API_TOKEN`" (note the env var name).
- "Go to personal account, create a token, *DON'T SELECT A WORKSPACE*."

**Resolution of the conflict**: The two env vars are different.
- `RAILWAY_TOKEN` → **project token** (per official blog).
- `RAILWAY_API_TOKEN` → **account/workspace token** (broader CLI ops).

The reli workflow uses `RAILWAY_TOKEN`. Per the official blog, this *should* be a project token created from project settings — but the rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) directs humans to https://railway.com/account/tokens, which creates an **account token**. This is a likely root cause of the recurring failures.

---

### 5. Validation Step May Be Incompatible with Project Tokens

**Source**: Inferred from [Public API docs](https://docs.railway.com/integrations/api) + the failing workflow log

**Relevant to**: Why the validation step in `.github/workflows/staging-pipeline.yml` fails

**Key Information**:

The workflow validates the token with:

```bash
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -d '{"query":"{me{id}}"}'
```

The `{me{id}}` GraphQL query returns the **authenticated user's identity**. Project tokens have no user identity — they identify a *project environment*, not a person. If `RAILWAY_TOKEN` is a project token (as the official Railway blog recommends for this env var), this validation query may inherently return "Not Authorized" regardless of whether the token is valid.

This could not be confirmed from official Railway GraphQL schema documentation (which is sparse on which queries work with which token types), so it should be tested in isolation before assuming.

---

### 6. Alternative Deployment Methods (No Long-Lived Token)

**Source**: [GitHub Autodeploys — Railway Docs](https://docs.railway.com/guides/github-autodeploys), [Comparing Deployment Methods in Railway (blog)](https://blog.railway.com/p/comparing-deployment-methods-in-railway)
**Authority**: Official Railway docs and blog
**Relevant to**: Eliminating the rotation burden entirely

**Key Information**:

Railway's **GitHub autodeploy** integration deploys on push without storing a Railway token in GitHub Secrets — it uses Railway's own GitHub App OAuth integration. If the project's only CI need is "deploy on push to main," autodeploys remove the rotation burden completely.

The trade-off: autodeploys don't run custom validation (the `Validate Railway secrets` step would no longer apply because the workflow itself wouldn't be needed). Custom pre-deploy gates (tests, builds, environment validation) would need to move to other mechanisms (branch protection, status checks).

---

## Code Examples

### Project-token GitHub Actions workflow (per Railway blog)

```yaml
# From the official Railway blog: https://blog.railway.com/p/github-actions
name: Deploy to Railway

on:
  push:
    branches: [main]

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

Note: this example does **not** include a separate "validate token" step that calls `{me{id}}`. The `railway up` command itself fails fast if the token is wrong.

---

## Gaps and Conflicts

- **Gap**: Railway documentation does not explicitly state whether account/workspace/project API tokens have any default TTL or "no expiration" toggle. The runbook's claim that tokens must be created with "No expiration" could not be verified against official docs — it may be conventional wisdom from a previous Railway UI.
- **Gap**: Whether the GraphQL `{me{id}}` query works with project tokens is undocumented. Testing required.
- **Conflict**: Railway's own documentation contradicts itself on `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` and project vs account scope. The blog says project token for `RAILWAY_TOKEN`; the help station threads (with Railway-staff answers) say account token. Both env-var names are referenced in different official docs.
- **Gap**: No evidence found that Railway has changed their token policy to add automatic expiration in 2026 — but the recurring failures across 56+ issues in this repo suggest *something* is invalidating tokens that the public docs don't describe.

---

## Recommendations

Based on research, the next rotation should be paired with diagnostic steps, not just a fresh token:

1. **Investigate token type before rotating again.** Open https://railway.com/account/tokens AND the project-settings tokens page side-by-side. The runbook currently directs humans to the account URL, but the `RAILWAY_TOKEN` env var name conventionally maps to a *project* token. If past rotations created account tokens, that may explain the persistent "Not Authorized" — the token isn't expiring; it's the wrong type.

2. **Test the validation query in isolation.** Before the next rotation, manually run `curl ... -d '{"query":"{me{id}}"}'` against a known-good project token AND a known-good account token. If `{me{id}}` only works for account tokens, the validation step itself is misdesigned and needs to be replaced with a query that works for whichever token type is correct (e.g., `{ projects { edges { node { id } } } }` for an account token, or a project-scoped query for a project token).

3. **Audit for env var conflicts.** Check the workflow and any inherited environments for both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` being set simultaneously — Railway docs explicitly call this out as a cause of auth failures.

4. **Consider migrating to GitHub autodeploys.** If the team only needs "deploy on push to main," Railway's GitHub App integration eliminates the GitHub-Secrets-stored token entirely. The custom validation/health-check steps would need to move to branch protection or post-deploy webhooks.

5. **Do not have an agent create another `RAILWAY_TOKEN_ROTATION_*.md` file.** Per `CLAUDE.md`, agents cannot rotate the token. The existing runbook at `docs/RAILWAY_TOKEN_ROTATION_742.md` should be **updated** with the diagnostic findings above before the next rotation, not duplicated.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Token types and scopes |
| 2 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth vs API token lifetimes |
| 3 | Using GitHub Actions with Railway (blog) | https://blog.railway.com/p/github-actions | Official `RAILWAY_TOKEN` workflow recommendation (project token) |
| 4 | RAILWAY_TOKEN invalid or expired — Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Misleading error message; token-type mismatch is the usual cause |
| 5 | Token for GitHub Action — Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Conflicting Railway-staff guidance: account token for multi-env CLI |
| 6 | Authentication not working with RAILWAY_TOKEN — Help Station | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env-var distinction |
| 7 | GitHub Autodeploys — Railway Docs | https://docs.railway.com/guides/github-autodeploys | Token-free deploy alternative |
| 8 | Comparing Deployment Methods (blog) | https://blog.railway.com/p/comparing-deployment-methods-in-railway | Trade-offs of autodeploy vs CLI deploy |
| 9 | GitHub Actions Post-Deploy — Railway Docs | https://docs.railway.com/guides/github-actions-post-deploy | Post-deploy hook patterns |
