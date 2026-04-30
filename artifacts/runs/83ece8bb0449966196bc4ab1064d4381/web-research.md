# Web Research: fix #783 (Main CI red — Deploy to staging)

**Researched**: 2026-04-30T10:33:42Z
**Workflow ID**: 83ece8bb0449966196bc4ab1064d4381

---

## Summary

Issue #783 is the **15th** recurrence of `RAILWAY_TOKEN is invalid or expired: Not Authorized` failing the `Deploy to staging` job (lineage: `#733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #773 / #774 → #777 → #779 → #781 → #783`). The current rotation playbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) treats this as a one-off rotation, but the recurrence pattern indicates the underlying setup is structurally fragile. Research turned up three concrete improvements supported by Railway's official documentation: (1) the workflow uses an **account-scoped token**, but Railway's docs explicitly recommend **workspace tokens** for "Team CI/CD"; (2) the workflow hits **`backboard.railway.app`**, but current Railway docs publish **`backboard.railway.com`** as the endpoint; (3) Railway publishes no public OIDC / workload-identity-federation support, so static tokens remain unavoidable — the only mitigation is choosing the longest-lived, most-narrowly-scoped token type and reducing the chance of auto-expiry. None of these are within the agent's authority to apply alone (rotating the token requires human Railway dashboard access per `CLAUDE.md`), but they should inform whatever human follow-up is taken.

---

## Findings

### Railway documents four distinct API token types, with explicit "Best For" guidance

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [Public API Guide | Railway Docs](https://docs.railway.com/guides/public-api)
**Authority**: Railway official documentation
**Relevant to**: Choosing the right token type for our GitHub Actions workflow

**Key Information**:

- Four token categories with explicit "Best For" mappings in the docs:
  1. **Account Token** — scope: "All your resources and workspaces" — Best For: **"Personal scripts, local development"**
  2. **Workspace Token** — scope: "Single workspace" — Best For: **"Team CI/CD, shared automation"**
  3. **Project Token** — scope: "Single environment in a project" — Best For: **"Deployments, service-specific automation"**
  4. **OAuth** — Best For: "Third-party apps acting on behalf of users"
- Authentication header differs by type:
  - Account, Workspace, and OAuth tokens: `Authorization: Bearer <TOKEN>`
  - Project tokens: `Project-Access-Token: <TOKEN>` (different header entirely)
- Workspace tokens "[have] access to all the workspace's resources, and cannot be used to access your personal resources or other workspaces. You can share this token with your teammates."

**Implication for #783**: Our workflow stores a `RAILWAY_TOKEN` that authenticates as the personal account (Bearer header). Per Railway's own docs, the recommended type for "Team CI/CD" is a **workspace token**, not an account token. Workspace tokens are still Bearer-header so the workflow would not require code changes to switch.

---

### Railway's documented GraphQL endpoint is `backboard.railway.com`, not `backboard.railway.app`

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [Public API Guide | Railway Docs](https://docs.railway.com/guides/public-api)
**Authority**: Railway official documentation
**Relevant to**: All four `curl` calls in `.github/workflows/staging-pipeline.yml`

**Key Information**:

- Direct quote from docs (verified by two independent fetches): the API endpoint is `https://backboard.railway.com/graphql/v2`.
- Our workflow currently calls `https://backboard.railway.app/graphql/v2` (4 occurrences in `staging-pipeline.yml` — staging validate, staging deploy + redeploy, production validate, production deploy + redeploy).
- Community discussion (mixed authority — not Railway staff) on the help station and Postman collection consistently shows `.com` as the current endpoint, with at least one community summary asserting the `.app` host now returns "Not Authorized".

**Caveat**: We cannot prove that `.app` is the *cause* of issue #783, because the same workflow has succeeded against `.app` in the past (after each prior rotation). The most parsimonious explanation is that `.app` still resolves but redirects/aliases or has differing token-validation behavior. Either way, the documented endpoint is `.com` — our config has drifted from the docs.

---

### No official "no expiration" option is documented for account / workspace / project tokens

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Railway official documentation
**Relevant to**: The premise of `docs/RAILWAY_TOKEN_ROTATION_742.md` (which claims "No expiration" can be selected when creating an account token)

**Key Information**:

- The OAuth-and-tokens page explicitly documents OAuth-token lifetimes only:
  - OAuth **access tokens** "expire after one hour"
  - OAuth **refresh tokens** have "a fresh one-year lifetime from the time of issuance"
- For dashboard-created Account / Workspace / Project tokens, **the public docs do not specify an expiration policy or a "no expiration" UI option**. Multiple targeted searches did not surface a "TTL" or "never expires" setting in indexed Railway docs.
- Community evidence (help station threads on `RAILWAY_TOKEN invalid or expired`, `API Token Not Authorized`, `RAILWAY_API_TOKEN not Working`) consistently treats these tokens as expirable artifacts that "must be regenerated", without mentioning a permanence option.

**Implication for #783**: The current rotation runbook's load-bearing instruction — "**Expiration: No expiration** (critical — do not accept default TTL)" — may not correspond to a real UI option, or may have been removed/changed. If that step is silently a no-op, every rotation is producing a token with the same default TTL, fully explaining the 14× recurrence. **A human with dashboard access should verify whether this option still exists** before issuing the next rotation.

---

### Railway has no published OIDC / workload identity support for GitHub Actions

**Source**: [Using GitHub Actions with Railway | Railway Blog](https://blog.railway.com/p/github-actions), [GitHub Actions Post-Deploy | Railway Docs](https://docs.railway.com/guides/github-actions-post-deploy)
**Authority**: Railway official blog and docs
**Relevant to**: Whether we can eliminate static tokens entirely

**Key Information**:

- Every Railway-published example for GitHub Actions integration uses a **static token stored as a repo secret** (`RAILWAY_TOKEN` or `RAILWAY_API_TOKEN`).
- Targeted searches for "Railway OIDC", "workload identity federation", "Railway keyless GitHub Actions" turned up GCP, Azure, and AWS OIDC documentation — nothing from Railway. There is no evidence Railway accepts GitHub's signed OIDC tokens for trust-based auth.
- Railway's official GitHub Actions blog post still recommends "create a new project token on the `Settings` page of your project dashboard" → "add it to your repository secrets on Github".

**Implication for #783**: We cannot trade the static token for OIDC — it is not on offer. Any durable fix must be of the form "make the static token live longer / fail less often", not "remove the static token".

---

### Railway employee guidance on GitHub Actions auth is mixed — historically suggested account tokens, but newer docs steer to workspace tokens

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720), [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Railway employee post (one historical comment) vs. current docs
**Relevant to**: Token-type recommendation

**Key Information**:

- Help station thread quotes Railway employee David: *"use a Railway API token scoped to the user account, not a project token, for the GitHub Action. This token should be set in the `RAILWAY_API_TOKEN` environment variable."*
- A moderator follow-up clarified that earlier CLI bugs around the env-var name have since been fixed.
- Current docs (above) list **workspace tokens** as the "Best For: Team CI/CD" option — which post-dates the help-station thread. This is consistent with Railway adding a workspace concept after the original employee post.

**Implication for #783**: The help-station guidance may be outdated. The most up-to-date official guidance is the table on the Public API docs page recommending **workspace tokens** for team CI/CD.

---

### Project tokens are scoped narrowly but use a different header — not a drop-in replacement

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), community: [API Token "Not Authorized" Error](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1), [RAILWAY_TOKEN invalid or expired](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway docs (primary) + community (secondary)
**Relevant to**: Whether to switch to a project token

**Key Information**:

- Project tokens advertise "Best For: Deployments, service-specific automation" — superficially the closest fit for our use case.
- But: project tokens require the `Project-Access-Token: <TOKEN>` header, **not** `Authorization: Bearer`. Switching would require editing every `curl` call in `staging-pipeline.yml`.
- Community evidence is split: one help-station thread asserts "Railway now requires project tokens" (and fixed a recurring rotation issue by switching), while another reports project tokens reading project info but **failing on deployment mutations** with "Not Authorized". The official docs do not list which mutations are gated to which token types.

**Implication for #783**: Switching to a project token is a plausible but **risky** change because (a) the header format change must land in the same PR as the secret swap to avoid breakage, and (b) community reports of project tokens being insufficient for deploy mutations are unresolved. **Workspace tokens are the lower-risk option** because they keep the same Bearer header.

---

## Code Examples

The current workflow's `curl` invocation against the GraphQL API (used 5× across staging + production jobs):

```yaml
# From .github/workflows/staging-pipeline.yml (line 49)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

The **docs-aligned** equivalent (only the host changes; header is unchanged for account or workspace tokens):

```yaml
# Per https://docs.railway.com/guides/public-api
RESP=$(curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

If switching to a **project token**, both host and header change:

```yaml
RESP=$(curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

Note: the `{me{id}}` validation query authenticates as a *user* and is unlikely to work with a project token. The validation step would need to be replaced with a project-scoped query (e.g., `{project(id: $id) { id }}`).

---

## Gaps and Conflicts

- **Unknown**: The actual TTL of dashboard-created account / workspace / project tokens. Railway's public docs do not state it. The pattern of recurrences in #783 (and 13 prior) is the best available signal — analyzing the inter-arrival time between rotation issues (#733 → #739 → #742 → … → #783) would reveal the empirical TTL, which would in turn confirm or refute the rotation runbook's "No expiration" premise.
- **Unknown**: Whether `backboard.railway.app` is being phased out, fully deprecated, or just an undocumented alias. We have no Railway-staff statement on this.
- **Conflicting community reports**: Some users say project tokens cannot trigger `serviceInstanceDeploy`; Railway docs say project tokens are "Best For: Deployments". The contradiction is not resolved in any indexed source.
- **Conflicting Railway-employee guidance**: An older help-station post recommends account tokens for GitHub Actions; the current Public API docs recommend workspace tokens for team CI/CD. The latter is more recent and authoritative, but the contradiction is worth noting.
- **No OIDC path**: Searches for Railway OIDC / workload identity / keyless auth returned nothing. If Railway adds this in the future, it would be the structurally correct fix.

---

## Recommendations

For the human who picks up this issue:

1. **Short-term (resolves #783)**: Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`, but **before** rotating, capture a screenshot or note of whether the "No expiration" UI option still exists. If it does not, the runbook's claim is stale and must be updated. If it does, double-check the new token actually has no expiry shown on the tokens page after creation.
2. **Medium-term (reduces recurrence) — switch token type to Workspace**: Workspace tokens are Railway's documented recommendation for "Team CI/CD" and use the same Bearer header, so the switch is a pure secret swap with no workflow code change. This may also produce a longer-lived token (no documentation either way; switching is a small experiment).
3. **Medium-term (alignment with docs) — change endpoint host**: Update all five `curl` calls in `.github/workflows/staging-pipeline.yml` from `https://backboard.railway.app/graphql/v2` to `https://backboard.railway.com/graphql/v2` to match official docs. Land this **separately** from the token swap so a regression can be attributed to one change at a time.
4. **Diagnostic — measure actual token TTL**: Pull the GitHub issue dates for prior `RAILWAY_TOKEN` expirations (#733, #739, #742, #769, #773, #774, #777, #779, #783) and compute the inter-arrival times. If they cluster around a fixed value (30, 60, 90 days), the rotation runbook's "No expiration" step is verifiably ineffective and the team is paying a rotation tax. This data would justify or rule out option (5).
5. **Avoid for now — switching to project tokens**: Higher-risk change (header format + validation-query rewrite + unresolved community reports of deploy mutations failing). Only consider if workspace tokens also expire and the team wants to attempt project-token scope as the next experiment.
6. **Do not pursue — OIDC/keyless auth**: Not supported by Railway as of this research date.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Authoritative token-type table and endpoint URL |
| 2 | Railway Docs — Public API Guide | https://docs.railway.com/guides/public-api | Same content, mirrored under guides path |
| 3 | Railway Docs — Login & Tokens (OAuth) | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token lifetimes (1h access / 1y refresh) |
| 4 | Railway Docs — Deployment Actions | https://docs.railway.com/deployments/deployment-actions | UI-level deployment actions; does not document API auth specifics |
| 5 | Railway Docs — GitHub Actions Post-Deploy guide | https://docs.railway.com/guides/github-actions-post-deploy | Mentions GitHub Actions trigger pattern |
| 6 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Walkthrough using `RAILWAY_TOKEN` repo secret + project token |
| 7 | Railway Blog — Incident Report Jan 28-29 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Confirms recent incident was about *GitHub OAuth* token rate limits, not Railway-API token expiration — i.e., unrelated to #783 |
| 8 | Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Older Railway-employee guidance to use account tokens |
| 9 | Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community resolution recommending project tokens |
| 10 | Help Station — API Token "Not Authorized" Error | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Community discussion of the exact error string we hit |
| 11 | Help Station — Help using Railway API | https://station.railway.com/questions/help-using-railway-api-6778e043 | Mixed-evidence thread on `.com` vs `.app` endpoint |
| 12 | Postman — Railway GraphQL API collection | https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api | Confirms `backboard.railway.com` as the endpoint |
