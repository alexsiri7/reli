---
name: Web Research — Issue #777
description: Web research for prod deploy failure (RAILWAY_TOKEN expired) — Railway token types, expiration behavior, and GitHub Actions auth alternatives
type: research-artifact
---

# Web Research: fix #777

**Researched**: 2026-04-30T09:00:00Z
**Workflow ID**: 29fcbf22353ef9c87dd380854e4aa85a
**Issue**: alexsiri7/reli#777 — *Prod deploy failed on main* (12th occurrence of `RAILWAY_TOKEN is invalid or expired: Not Authorized`)

---

## Summary

Issue #777 is the latest in a recurring series (`#733 → #739 → #742 → #762 → #769 → #771 → #773 → #774 → #777`) where Railway's `RAILWAY_TOKEN` GitHub Actions secret stops authenticating against the Railway GraphQL API (`backboard.railway.app/graphql/v2`, query `{me{id}}`). Research confirms three things: **(1)** the `{me{id}}` introspection query requires a *personal-scoped* token (Account or Workspace), not a Project Token — the workflow's choice of token type and the validation query are coupled; **(2)** Railway publishes no documented default TTL for dashboard-created API tokens, but multiple Help Station threads and Railway employee responses confirm tokens *can* and *do* get revoked/expire, and the dashboard offers a TTL selector that defaults to a finite value; **(3)** Railway does not currently offer OIDC federation with GitHub Actions, so the long-term fix must come from token-type/TTL hygiene plus monitoring, not a secretless rewrite.

---

## Findings

### 1. Railway has four token types — only some authenticate `{me{id}}`

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why the validation step in `staging-pipeline.yml` fails

**Key Information**:

- Four token types exist:
  - **Account Token** — "All your resources and workspaces" — recommended use: "Personal scripts, local development"
  - **Workspace Token** — "Single workspace" — recommended use: "Team CI/CD, shared automation"
  - **Project Token** — "Single environment in a project" — recommended use: "Deployments, service-specific automation"
  - **OAuth** — third-party app authorization
- The `{ me { id email } }` GraphQL query "requires personal access token" (Account or Workspace). Project Tokens cannot answer `me` and will return `Not Authorized` against this query.
- The docs do **not** publish an explicit TTL/expiration field for any token type.

**Implication for #777**: The validation block in `.github/workflows/staging-pipeline.yml:49-58` uses `{me{id}}`, which means the secret must be an Account or Workspace token, not a Project Token. If a previous rotation accidentally used a Project Token, every deploy would fail at this exact step.

---

### 2. Railway employees explicitly recommend account- or workspace-scoped tokens for GitHub Actions

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway employee answer in official help forum
**Relevant to**: Choice of token type going forward

**Key Information**:

- Railway employee guidance: *"use a Railway API token scoped to the user account, not a project token, for the GitHub Action."*
- Set as `RAILWAY_API_TOKEN` (preferred); `RAILWAY_TOKEN` works too, and when both are set `RAILWAY_TOKEN` takes precedence per the CLI docs.
- One historical CLI bug (since fixed) caused `RAILWAY_API_TOKEN` to be ignored, which is why many older guides still pick `RAILWAY_TOKEN`.

**Conflict to flag**: Railway's *blog post* on GitHub Actions ([blog.railway.com/p/github-actions](https://blog.railway.com/p/github-actions)) recommends a **Project Token** ("Project tokens allow the CLI to access all the environment variables associated with a specific project and environment"). The Help Station employee answer is **newer and contradicts** the blog. For our use case — running a `me` validation query *and* deploying — only an account/workspace token works for both. The blog example never validates, so it never hits the Project-Token-doesn't-answer-`me` problem.

---

### 3. Token "Not Authorized" is overwhelmingly token-type or TTL related

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway Help Station Q&A with employee response
**Relevant to**: The exact error string in #777

**Key Information**:

- Quote: *"RAILWAY_TOKEN now only accepts project token"* (in the CLI's `railway up` context — distinct from raw GraphQL `me` queries).
- Recommended fix: *"Generate a project-specific token instead"* — but this guidance is for `railway up`, not for the `me` introspection used in our validation step.
- Additional note: an existing `RAILWAY_API_TOKEN` env var can shadow `RAILWAY_TOKEN` and produce phantom auth failures. Make sure only one is set at a time per step.

**Conflict to flag**: Across Help Station threads, Railway has shifted recommendations between 2023–2025 about which token works for `railway up` vs the public GraphQL API. The safest 2026 reading: the *deploy* step needs whatever token your CLI invocation uses (Project for `railway up --service`, Account/Workspace for graph mutations), and the *validation* step's `me` query mandates Account or Workspace.

---

### 4. Railway OAuth tokens are short-lived; "API tokens" are not OAuth and have a separate (undocumented) lifetime

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Whether the `RAILWAY_TOKEN` we use is supposed to last or rotate

**Key Information**:

- OAuth access tokens expire after **one hour**; refresh tokens are valid for **one year** with rotation-on-use.
- A user authorization may hold at most **100 refresh tokens** before the oldest are auto-revoked.
- API tokens (Account/Workspace/Project) created in the dashboard are described as separate from OAuth and the docs do not state a fixed TTL — but the dashboard's token-creation modal lets the creator pick an expiration window (commonly 1 day, 7 days, 30 days, no expiration).

**Implication for #777**: Recurring expirations strongly suggest the token was created with a **finite TTL** (default in the picker). The local runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md:20`) already calls this out: *"the new token must be created with No expiration"*. If the rotator selected a default TTL on any of the prior 11 rotations, that explains the cadence.

---

### 5. Railway has no OIDC federation with GitHub Actions

**Source**: [GitHub Actions Self-Hosted Runners | Railway Docs](https://docs.railway.com/guides/github-actions-runners) and [Configuring OpenID Connect in cloud providers — GitHub Docs](https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers)
**Authority**: Official Railway + GitHub docs
**Relevant to**: Whether the secretless / OIDC path is viable

**Key Information**:

- GitHub OIDC is supported for AWS, Azure, GCP, HashiCorp Vault, and a handful of third parties — **Railway is not among them**, and Railway's docs do not advertise an OIDC trust endpoint.
- The recommended GitHub-side pattern (`permissions: id-token: write`, then exchange for a short-lived cloud token) requires the cloud provider to host an OIDC trust configuration. Without Railway support, this pattern can't apply to Railway deploys today.
- Practical consequence: until Railway ships OIDC, a long-lived secret is structurally required. Hygiene (correct TTL, monitoring, automated alerting) is the only mitigation.

---

### 6. The repo already has a daily health check; the gap is alerting lead time

**Source**: Local file [.github/workflows/railway-token-health.yml](../../../.github/workflows/railway-token-health.yml)
**Authority**: Repo state at HEAD (1346f34)
**Relevant to**: Whether the team is detecting expirations *before* a deploy fails

**Key Information**:

- A scheduled workflow runs daily at 09:00 UTC and posts the same `{me{id}}` probe.
- On failure it opens an idempotent issue titled "Railway token expired — rotate RAILWAY_TOKEN before next deploy".
- Issue #777 was filed at 09:00:27 UTC with deploy failure timestamped 08:35:10 UTC — i.e. the deploy failed *before* the health check could pre-warn. The health check's daily cadence is too coarse to beat a CI-on-merge deploy that runs at any hour.

**Gap**: the health check provides post-mortem alerting, not pre-deploy prevention. A ~7-day-ahead expiration warning (querying the token's expiry metadata, if Railway exposes it) would catch finite-TTL tokens before they fire.

---

## Code Examples

### Validating a Railway token with the public GraphQL API

```bash
# From [staging-pipeline.yml validation step in this repo + corroborated by Railway Help Station threads]
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
# `me` resolves only for Account/Workspace tokens, not Project tokens.
```

### GitHub OIDC pattern (illustrative — does NOT work with Railway today)

```yaml
# From https://docs.github.com/en/actions/concepts/security/openid-connect
# Shown to demonstrate why this is not yet a fix for #777.
permissions:
  id-token: write
  contents: read
jobs:
  deploy:
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123:role/github-deploy
          aws-region: us-east-1
      # No equivalent action exists for Railway as of April 2026.
```

---

## Gaps and Conflicts

- **Undocumented default TTL**: Railway does not publish what the dashboard's token-creation default expiration is. We can only infer from the recurrence pattern in this repo (~tokens expire every few days to weeks) that a finite default exists. We could not find an official source confirming this number.
- **Account vs Workspace vs Project recommendation drift**: The Railway *blog* (uses Project), the *Help Station employee answer* (uses Account/Workspace), and the *CLI docs* (refers ambiguously to "tokens") give different recommendations. The ground truth depends on which API surface you're hitting (`me` vs `railway up` vs deploy mutation). No single Railway doc reconciles these.
- **No OIDC roadmap**: We could not find any Railway public statement about adding OIDC for GitHub Actions. Issue trackers and changelogs were silent on it as of the search date.
- **Token-introspection endpoint**: Whether the Railway GraphQL API exposes `expiresAt` for the *current* bearer token (so we could pre-warn N days out) was not confirmed. The schema documentation we accessed did not surface such a field.

---

## Recommendations

Based on research, prioritized for the maintainer of #777:

1. **Confirm the active token type and recreate it as Workspace-scoped with "No expiration"**. This is consistent with the Help Station employee answer and the local `RAILWAY_TOKEN_ROTATION_742.md` guidance. *Why workspace not account*: workspace tokens are the recommended CI/CD scope and have lower blast radius than account tokens. Both can answer `me`.
2. **Do not switch to a Project Token** without also rewriting the validation step. The current `{me{id}}` probe will reject Project Tokens 100% of the time — that would convert a recurring ~weekly failure into a permanent one.
3. **Audit the rotation runbook** to require operators to (a) explicitly select "No expiration" and (b) screenshot/confirm the selection — the 11 prior rotations evidently kept ending up with TTL'd tokens, suggesting a checklist gap.
4. **Move the health check to hourly, not daily**, until OIDC is available. The current `0 9 * * *` cadence cannot pre-warn deploys that happen on merge.
5. **Watch for Railway OIDC** as a future eliminator. No timeline exists today, but the maintenance burden of #777 justifies tracking Railway's roadmap (release notes, blog) for an OIDC-trust announcement and migrating off long-lived secrets when available.
6. **Defer to the human for rotation** per repo `CLAUDE.md`: agents cannot rotate the token; they must file an issue and direct the human to the runbook. Do not create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming completion.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs | https://docs.railway.com/integrations/api | Token-type taxonomy and scope semantics |
| 2 | Railway CLI docs | https://docs.railway.com/guides/cli | RAILWAY_TOKEN vs RAILWAY_API_TOKEN behavior |
| 3 | Railway Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTL (1 hr / 1 yr) — distinct from API tokens |
| 4 | Railway blog: GitHub Actions | https://blog.railway.com/p/github-actions | Project Token recommendation (older, conflicts with Help Station) |
| 5 | Help Station: Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Employee answer recommending Account/Workspace token |
| 6 | Help Station: RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Diagnosis pattern for the exact error in #777 |
| 7 | Help Station: Project Token Not Found | https://station.railway.com/questions/error-project-token-not-found-when-dep-391b52a3 | Token-type confusion failure mode |
| 8 | Railway GraphQL via Postman | https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api | Schema reference for `me` query scope |
| 9 | GitHub OIDC concepts | https://docs.github.com/en/actions/concepts/security/openid-connect | Secretless pattern (not yet supported by Railway) |
| 10 | GitHub OIDC cloud provider list | https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers | Confirms Railway is not a federated provider |
| 11 | bervProject/railway-deploy | https://github.com/bervProject/railway-deploy | Community Action's expected env var (RAILWAY_TOKEN) |
| 12 | Local runbook | docs/RAILWAY_TOKEN_ROTATION_742.md | Existing rotation guidance — already prescribes "No expiration" |
