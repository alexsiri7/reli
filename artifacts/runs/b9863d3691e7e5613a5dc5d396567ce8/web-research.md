## Web Research: fix #804

**Researched**: 2026-04-30T18:55:00Z
**Workflow ID**: b9863d3691e7e5613a5dc5d396567ce8

---

## Summary

Issue #804 is the **21st** recurrence of the same failure: `RAILWAY_TOKEN is invalid or expired: Not Authorized` returned by `https://backboard.railway.app/graphql/v2` during the `Validate Railway secrets` step of `Deploy to staging`. Per Reli's `CLAUDE.md` policy, agents cannot rotate the token — a human must visit `railway.com/account/tokens`. Web research confirms the Reli runbook's existing guidance and surfaces two structural options worth flagging to the human: (1) Railway **project (environment-scoped) tokens** authenticate with a different header than account tokens and are the recommended CI/CD primitive; (2) account tokens default to short TTLs, so the new token must be created with **No expiration** to break the rotation cycle.

---

## Findings

### Railway Token Types & Authentication Headers

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why the current token keeps expiring; whether the workflow uses the right token type.

**Key Information**:

- Railway exposes **three distinct token types**, each with its own auth header:
  - **Account / personal tokens** → `Authorization: Bearer <token>` (full account access)
  - **Team / workspace tokens** → `Team-Access-Token: <token>` (team-scoped)
  - **Project tokens** → `Project-Access-Token: <token>` (environment-scoped; the recommended CI/CD primitive)
- Endpoint: `https://backboard.railway.com/graphql/v2` (note: `.com`, not `.app` — both appear in the wild but `.com` is the documented one).
- Rate limit: 1000 requests/hour per token.
- The current `staging-pipeline.yml` uses `Authorization: ***` (Bearer-style), which means the secret is an **account token**, not a project token.

---

### "Not Authorized" Failure Modes

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway's official community help station; confirmed by Railway staff responses
**Relevant to**: Diagnosing why the validation curl returns `Not Authorized`.

**Key Information**:

- `{ me { id } }` returns `Not Authorized` when the supplied token is **not a personal/account token** (e.g., a team or project token sent with the wrong header). For Reli's validation query (`{me{id}}`), only an **account token** with `Authorization: Bearer` works.
- Tokens silently revoke after expiration — the API responds with `Not Authorized` rather than a dedicated "expired" error code.
- See also: [GraphQL requests returning "Not Authorized" for PAT](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52) — same root cause; Railway support typically asks for traceIds to confirm revocation vs. permission scoping.

---

### Token Expiration & "No Expiration" Option

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Why the token has now expired 21 times — and how to stop the bleeding.

**Key Information**:

- When generating an account token in the dashboard, the user picks an expiration. Defaults are short (1 day / 7 days / 30 days). The **"No expiration"** option exists but is opt-in.
- OAuth-issued access tokens always expire after 1 hour and require `offline_access` for refresh. Dashboard-generated tokens are separate and follow the user-picked TTL.
- The Reli runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) already calls out **"Expiration: No expiration (critical — do not accept default TTL)"**, but the 21× recurrence suggests this step has not been honored on at least one rotation.

---

### Project Tokens for CI/CD (Long-Lived Alternative)

**Source**: [Using GitHub Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions) and [Railway Help Station — Token for GitHub Action](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway's official blog and help station
**Relevant to**: A potentially better long-term primitive than rotating an account token.

**Key Information**:

- For GitHub Actions, Railway recommends a **project token** stored as `RAILWAY_TOKEN` and used by the `railway up` CLI: `railway up --service=<id>`.
- Project tokens **do not expire by default**, are scoped to one environment, and break the validation pattern Reli currently uses (no `me { id }` query — the CLI handles auth opaquely).
- Trade-off: project tokens cannot satisfy the existing `{me{id}}` validation curl. Switching to project tokens would require changing the workflow's "Validate Railway secrets" step to either (a) drop the `me` check, or (b) call a project-scoped query like `{project(id:"...") { name }}`.

---

### Reusable GitHub Action

**Source**: [bervProject/railway-deploy — GitHub](https://github.com/bervProject/railway-deploy)
**Authority**: Most-starred third-party action for Railway deploys
**Relevant to**: Reduces the surface area where `RAILWAY_TOKEN` is consumed.

**Key Information**:

- Drop-in action: `bervProject/railway-deploy@main` with `service:` input and `RAILWAY_TOKEN` env. Wraps `railway up`.
- Useful as a future simplification, but **does not** address the rotation cadence — same token expiry rules apply.

---

### Secretless / OIDC Alternatives

**Source**: [Secretless Access for GitHub Actions and Workflows — Aembit](https://aembit.io/blog/secretless-access-for-github-actions/) and [GitHub community discussion #168661 — Best Practices for Managing and Rotating Secrets](https://github.com/orgs/community/discussions/168661)
**Authority**: Vendor blog (Aembit) cross-checked against GitHub's own community-discussion thread
**Relevant to**: Long-term answer to "how do we stop rotating this token by hand?"

**Key Information**:

- GitHub Actions supports OIDC-based secretless auth for AWS/GCP/Azure/HashiCorp Vault out of the box — but **Railway does not currently expose an OIDC trust relationship for GitHub Actions** (no entry in their docs as of April 2026).
- Realistic intermediate step: rotate to a project token + use a secrets manager (Doppler, GitHub-native rotation webhooks, or a `railway-token-health.yml` workflow that already exists in this repo) to alert *before* expiry rather than after.

---

## Code Examples

The current validation step in `.github/workflows/staging-pipeline.yml`:

```bash
# From the failing run log
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: ***" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  exit 1
fi
```

If the team chose to migrate to a **project token**, the validation curl would change to (project tokens cannot run `me`):

```bash
# Hypothetical replacement using project tokens — from
# https://docs.railway.com/integrations/api
RESP=$(curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"{ projectToken { projectId environmentId } }\"}")
```

---

## Gaps and Conflicts

- **Endpoint domain inconsistency**: Railway's docs use `backboard.railway.com` while Reli's workflow hits `backboard.railway.app`. Both currently resolve, but the `.app` domain is undocumented and may be deprecated. Worth flagging to the human, but **not the cause of issue #804** (the curl returns a structured `Not Authorized`, so the endpoint is reachable).
- **Railway OIDC support**: No public roadmap entry. Could not confirm whether Railway plans to add it.
- **Token TTL audit**: I cannot determine from outside whether the most recent `RAILWAY_TOKEN` rotation was performed with "No expiration" or accepted a default TTL. The 21× recurrence strongly suggests at least one rotation accepted a default.
- **Why 21 rotations**: The cadence of the recent issues (#793, #794, #798, #801, #800, #804) suggests roughly weekly recurrence — consistent with a 7-day default TTL. None of the search results confirm Railway's exact default value.

---

## Recommendations

Based on research, in priority order:

1. **Do NOT attempt to fix this in code.** Per `CLAUDE.md`'s "Railway Token Rotation" section, the agent's only legitimate action is to file an investigation note pointing at `docs/RAILWAY_TOKEN_ROTATION_742.md`. Creating a `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming the rotation is done is a Category 1 error.
2. **Tell the human to verify "No expiration" on rotation.** The recurrence pattern (21 incidents) strongly indicates a default TTL is being accepted. The runbook already says this — the failure mode is human compliance, not documentation.
3. **Recommend migration to a Railway project token.** Trade-offs: (a) project tokens are environment-scoped and don't expire by default; (b) the `Validate Railway secrets` step must be rewritten because `{me{id}}` requires an account token; (c) auth header changes from `Authorization: Bearer` to `Project-Access-Token`. This would meaningfully break the cycle.
4. **Fix endpoint to `backboard.railway.com`.** Low-risk hygiene change; the `.app` domain is undocumented.
5. **Consider an `expires_at` health check.** The repo already has `railway-token-health.yml` — if it doesn't already query token TTL, extending it to alert ~7 days pre-expiry would prevent main-CI-red incidents from being the first signal.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Official token-type reference (account/team/project), correct headers, endpoint |
| 2 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | Token expiration semantics, "No expiration" option |
| 3 | Introduction to GraphQL — Railway Docs | https://docs.railway.com/integrations/api/graphql-overview | GraphQL schema and auth model |
| 4 | API Token "Not Authorized" Error — Railway Help Station | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Confirms `me{id}` requires account token; explains the exact error message Reli sees |
| 5 | GraphQL requests returning "Not Authorized" for PAT — Railway Help Station | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Cross-reference for the same failure mode |
| 6 | Using GitHub Actions with Railway — Railway Blog | https://blog.railway.com/p/github-actions | Recommends project tokens for CI/CD |
| 7 | Token for GitHub Action — Railway Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Practical project-token setup pattern |
| 8 | Unable to Generate API Token with Deployment Permissions | https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12 | Edge cases on token scoping |
| 9 | bervProject/railway-deploy — GitHub | https://github.com/bervProject/railway-deploy | Reusable Action that wraps `railway up` |
| 10 | Secretless Access for GitHub Actions — Aembit | https://aembit.io/blog/secretless-access-for-github-actions/ | OIDC trust-relationship background |
| 11 | Best Practices for Managing and Rotating Secrets — GitHub Community Discussion #168661 | https://github.com/orgs/community/discussions/168661 | GitHub-native rotation guidance |
| 12 | Automated secrets rotation with Doppler and GitHub Actions | https://www.doppler.com/blog/automated-secrets-rotation-with-doppler-and-github-actions | Optional secrets-manager path |
