# Web Research: fix #785

**Researched**: 2026-04-30T (UTC)
**Workflow ID**: 50c26f89b210dd820b779b2bbbaaf976
**Issue**: #785 — "Main CI red: Deploy to staging" — RAILWAY_TOKEN invalid or expired (16th occurrence in this repo, prior: #733, #739, #742, #744, #774, #777, #779, #781, #783)

---

## Summary

Issue #785 is yet another `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure on the `Deploy to staging` job. The team's runbook has been "rotate to a new account token with No expiration", but this has been recurring 15+ times — strong signal that either the team is still creating account tokens with default TTL, or Railway treats account tokens as expirable regardless of UI intent. Research surfaces a structural fix the runbook does **not** mention: switch the workflow from an **account token** (`Authorization: Bearer`, `{me{id}}` validation query) to a **project token** (`Project-Access-Token` header, `{projectToken{projectId,environmentId}}` validation), which is Railway's documented and recommended path for CI/CD because it is environment-scoped and not tied to a personal account's expirable token.

---

## Findings

### Railway has three distinct token types, with different headers and scopes

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Root cause — current workflow uses the wrong token class for CI

**Key Information**:

- **Account Token** — broadest scope, tied to a user account, all workspaces and resources. Header: `Authorization: Bearer <TOKEN>`.
- **Workspace Token** — single workspace. Header: `Authorization: Bearer <TOKEN>`.
- **Project Token** — scoped to a single environment in a single project. Header: `Project-Access-Token: <TOKEN>` (NOT `Authorization: Bearer`).
- API endpoint: `https://backboard.railway.com/graphql/v2`.
- Project token validation query (works without `me`): `query { projectToken { projectId environmentId } }` — confirms the token is valid and reports its scoped project/env.

---

### `me { id }` only works with account/workspace tokens, never project tokens

**Source**: [DeepWiki summary of Railway public API](https://deepwiki.com/railwayapp/docs/6.2-public-api-and-programmatic-access) and [Railway Help Station: API Token Permissions Issue](https://station.railway.com/questions/railway-api-token-permissions-issue-4dfeffde)
**Authority**: Railway-maintained docs index + community Q&A with staff replies
**Relevant to**: Why `.github/workflows/staging-pipeline.yml` is locked into account-token-only auth

**Key Information**:

- The `me` GraphQL field returns the personal account associated with the token. Project tokens have no personal account, so `{me{id}}` returns "Not Authorized" with a project token even when the token itself is valid.
- The repo's `staging-pipeline.yml` uses both `Authorization: Bearer $RAILWAY_TOKEN` AND `{me{id}}` for its validation step — this combination only accepts an **account or workspace** token. A project token would be rejected at the validate step.
- Implication: every prior rotation has produced an account token, and account tokens are the class with the recurring expiration problem.

---

### Account tokens have a TTL by default; "No expiration" is opt-in

**Source**: [Railway Help Station: RAILWAY_TOKEN invalid or expired](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20) + this repo's `docs/RAILWAY_TOKEN_ROTATION_742.md`
**Authority**: Community thread with multiple users hitting the same failure mode + project-internal runbook
**Relevant to**: Why rotation keeps recurring

**Key Information**:

- When creating an account token in the Railway dashboard, the expiration field defaults to a finite TTL (users on the help thread report values like 1 day, 7 days, 30 days). Selecting **"No expiration"** is required for a long-lived CI token.
- The repo's own runbook (#742) flagged this and instructed: name `github-actions-permanent`, expiration "No expiration". The fact that this is now the 16th occurrence suggests either the dropdown default has been chosen again on subsequent rotations, OR account tokens are subject to platform-level invalidation (e.g., rotated when the user's session changes, password reset, suspicious-activity flag).

---

### For CI/CD, Railway's documented recommendation is the **project token**

**Source**: [Deploying with the CLI | Railway Docs](https://docs.railway.com/cli/deploying), [Token for GitHub Action — Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway docs + staff-answered community Q&A
**Relevant to**: The architectural fix

**Key Information**:

- "For automated deployments, use a Project Token instead of interactive login. Project tokens are scoped to a specific environment and can only perform deployment-related actions."
- Project tokens are created from **Project → Settings → Tokens** (NOT account settings).
- The header is `Project-Access-Token: <TOKEN>`, not `Authorization: Bearer`.
- Project tokens do not appear to expire on a default TTL — community threads describe them as long-lived for CI use.
- Project tokens **can** call `serviceInstanceUpdate` and `serviceInstanceDeployV2` against the project/environment they are scoped to, which is exactly what `staging-pipeline.yml` uses.
- They cannot call `me{id}` — the validation query must change to `{projectToken{projectId,environmentId}}`.

---

### Conflicting precedence behavior of `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN`

**Source**: [RAILWAY_API_TOKEN not Working — Help Station](https://station.railway.com/questions/railway-api-token-not-working-2083f58a)
**Authority**: Community Q&A with consistent reproduction
**Relevant to**: Avoiding a regression if the workflow gets refactored

**Key Information**:

- The Railway CLI honors `RAILWAY_TOKEN` (project token) first; if both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` (account token) are set, `RAILWAY_TOKEN` wins.
- Several users reported "invalid or expired" on a freshly-created account token because they were setting it as `RAILWAY_TOKEN` instead of `RAILWAY_API_TOKEN`. The CLI was treating it as a project token and silently rejecting it.
- The repo's workflow uses raw `curl` against the GraphQL endpoint, not the CLI, so this CLI-precedence rule does not affect us — but if anyone migrates to the CLI later, they need to know.

---

### GitHub Actions OIDC is **not** supported by Railway

**Source**: [GitHub Docs: OIDC](https://docs.github.com/en/actions/concepts/security/openid-connect), [GitHub Blog: Passwordless deployments](https://github.blog/2023-01-11-passwordless-deployments-to-the-cloud/)
**Authority**: Official GitHub docs
**Relevant to**: Whether we can eliminate the long-lived secret entirely

**Key Information**:

- GitHub OIDC enables short-lived tokens federated to AWS, Azure, GCP, and any provider that registers GitHub as an OIDC IdP.
- Railway does not appear in any official OIDC trust-relationship guide and Railway docs do not list OIDC as an authentication option as of April 2026. There is no `railway/login` Action analogous to `aws-actions/configure-aws-credentials`.
- Conclusion: passwordless / OIDC-only auth is not available for Railway today. A long-lived secret is unavoidable; the question is which kind.

---

### Recurring secret-rotation patterns when the platform forces long-lived secrets

**Source**: [Shopify Engineering: Automatically Rotating GitHub Tokens](https://shopify.engineering/automatically-rotate-github-tokens), [Rotate AWS Access Keys Action](https://github.com/marketplace/actions/rotate-aws-access-keys)
**Authority**: Shopify production engineering blog + a popular GitHub Marketplace action
**Relevant to**: Defensive options if we cannot move to a non-expiring project token

**Key Information**:

- Pattern: a scheduled workflow (cron) that uses an admin token to mint a new short-lived secret, then writes the new secret back via the GitHub API (`gh secret set`).
- Requires the platform to expose a "create token" API; Railway does have a public GraphQL API but the **`tokenCreate` / similar mutation is not documented for project tokens** (mutations like `projectTokenCreate` exist via introspection but are not part of the documented API surface).
- Realistic application here: a weekly workflow that calls `{projectToken{projectId,environmentId}}` against the current `RAILWAY_TOKEN` and opens an issue if it returns "Not Authorized" — a pre-flight canary that fires before the next deploy. This is what `pipeline-health-cron.sh` already approximates, but we can run it on a tighter cadence to catch the failure between commits rather than during them.

---

## Code Examples

### Current workflow (uses account token, breaks on expiration)

```yaml
# From .github/workflows/staging-pipeline.yml in this repo
- name: Validate Railway secrets
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
  run: |
    RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
      -H "Authorization: Bearer $RAILWAY_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"query":"{me{id}}"}')
    if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
      echo "::error::RAILWAY_TOKEN is invalid or expired"
      exit 1
    fi
```

### Project-token equivalent (long-lived, environment-scoped)

```bash
# From https://docs.railway.com/integrations/api — Project Token section
curl --request POST \
  --url https://backboard.railway.com/graphql/v2 \
  --header 'Project-Access-Token: <PROJECT_TOKEN>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"query { projectToken { projectId environmentId } }"}'
```

The deploy step's `serviceInstanceUpdate` mutation works under both auth schemes; only the header line and the validation query change.

---

## Gaps and Conflicts

- **Default account-token TTL is not in official Railway docs.** Community reports say it's a dropdown with multiple options including "No expiration", but the *default* selection is not documented. We are inferring "short TTL is the default" from the fact that this repo has rotated 15+ times.
- **Project-token expiration policy is not explicitly documented either.** The community consensus is "they don't expire on a TTL", but Railway has not published a written guarantee. They could be revoked when the creating user's account changes (similar to fine-grained PATs on GitHub).
- **`projectTokenCreate` and similar mutations** appear in introspection but are absent from the documented API. We cannot rely on them for automated rotation without Railway support confirmation.
- **Conflict**: one community thread asserts "RAILWAY_TOKEN now only accepts project tokens" — this contradicts the workflow's success in the past with an account token. The likely resolution is that Railway's CLI changed at some point, but the raw GraphQL endpoint still accepts both header forms. Our workflow uses raw GraphQL, so both still work; the CLI claim does not apply here.

---

## Recommendations

Based on research:

1. **Short-term fix for #785**: rotate `RAILWAY_TOKEN` to a new account token at https://railway.com/account/tokens with **expiration explicitly set to "No expiration"**. This is what the existing runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) prescribes and is the lowest-risk change to unblock CI today. Per `CLAUDE.md`, agents cannot perform this action — it requires a human with Railway dashboard access.

2. **Structural fix to stop the recurrence (recommended follow-up issue)**: migrate `staging-pipeline.yml` from an account token to a **project token**. Concrete diff:
   - Replace `-H "Authorization: Bearer $RAILWAY_TOKEN"` with `-H "Project-Access-Token: $RAILWAY_TOKEN"` in every curl in the workflow.
   - Replace the validation query `{me{id}}` with `{projectToken{projectId environmentId}}` and update the `jq -e` selector to `.data.projectToken.projectId`.
   - Generate the new token from Railway dashboard → Project → Settings → Tokens (NOT account settings), scoped to the staging environment.
   - This eliminates the personal-account dependency, scopes the credential to exactly the environment that needs it, and removes the recurring TTL failure mode.

3. **Do not pursue OIDC/passwordless auth for Railway** — Railway does not support it as of April 2026. Any plan that assumes federated identity here will not work.

4. **Do not attempt automated rotation** of account tokens via Railway's GraphQL API. The relevant mutations are not in the documented public API and would be unsupported. Build the canary instead: a scheduled job that hits the validation query and opens an issue *before* the next deploy fails, narrowing detection latency without trying to rotate.

5. **Update the existing runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`)** to add the project-token migration as the documented long-term fix, so the next investigator finds it in the first place they look.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Definitive list of token types, headers, validation queries |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth vs API token semantics |
| 3 | Railway Docs — Deploying with the CLI | https://docs.railway.com/cli/deploying | Official "use project tokens for CI" guidance |
| 4 | Railway Docs — Introduction to GraphQL | https://docs.railway.com/integrations/api/graphql-overview | GraphQL endpoint and schema basics |
| 5 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Reproduces the exact error message in this issue |
| 6 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Project vs account token recommendation |
| 7 | Railway Help Station — RAILWAY_API_TOKEN not Working | https://station.railway.com/questions/railway-api-token-not-working-2083f58a | Env-var precedence between RAILWAY_TOKEN and RAILWAY_API_TOKEN |
| 8 | Railway Help Station — API Token Permissions Issue | https://station.railway.com/questions/railway-api-token-permissions-issue-4dfeffde | Confirms `me{id}` rejects project tokens |
| 9 | Railway Help Station — Unable to Generate API Token with Deployment Permissions | https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12 | Token-creation flow nuances |
| 10 | DeepWiki — Public API and Programmatic Access | https://deepwiki.com/railwayapp/docs/6.2-public-api-and-programmatic-access | Cross-reference of token semantics |
| 11 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Recommended GitHub Actions pattern |
| 12 | Railway Docs — Image Auto Updates | https://docs.railway.com/deployments/image-auto-updates | Alternative to imperative `serviceInstanceUpdate` |
| 13 | GitHub Docs — OpenID Connect | https://docs.github.com/en/actions/concepts/security/openid-connect | Confirms OIDC mechanism, but no Railway integration |
| 14 | GitHub Blog — Passwordless deployments | https://github.blog/2023-01-11-passwordless-deployments-to-the-cloud/ | OIDC providers list (Railway absent) |
| 15 | Shopify Engineering — Automatically Rotating GitHub Tokens | https://shopify.engineering/automatically-rotate-github-tokens | Pattern for cron-based rotation if needed |
| 16 | This repo — `docs/RAILWAY_TOKEN_ROTATION_742.md` | (local) | Existing rotation runbook with the "No expiration" instruction |
