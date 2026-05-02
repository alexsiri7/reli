---
name: Web Research — Issue #854 (RAILWAY_TOKEN expiration, 39th occurrence)
description: Research on Railway API token types, expiration behavior, and rotation patterns to inform the recurring RAILWAY_TOKEN failure
---

# Web Research: fix #854

**Researched**: 2026-05-02
**Workflow ID**: 8a2386c3ae1983d14df8161ca0d0849e
**Issue**: Main CI red — `Deploy to staging` fails at `Validate Railway secrets` step with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. This is the **39th occurrence** of the same RAILWAY_TOKEN expiration per the recent commit log (#742, #733, #739, #843, #847, #850, #854, etc.).

---

## Summary

Railway exposes three token types — **Account**, **Workspace**, and **Project** — with different scopes, headers, and capabilities. The repo's CI validates the secret by calling `{me{id}}` against the GraphQL API, which **only works with account tokens** (workspace/project tokens are explicitly rejected). The Railway public docs do **not** publicly document a "No expiration" checkbox, so the internal runbook's promise that selecting "No expiration" will end the recurrence cannot be confirmed from official sources — and after 39 rotations the pattern itself is the strongest evidence that whatever rotation procedure is being used does not produce a permanent token. The most authoritative community guidance (and Railway's own GitHub Actions blog) recommends **Project tokens** for deploy automation, but doing so would also require changing the validation query and the auth header (`Project-Access-Token` instead of `Authorization: Bearer`).

---

## Findings

### 1. Railway API Token Types

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Choosing the right token type for CI deploys.

**Key Information**:

- **Account token** — "tied to your Railway account. This is the broadest scope. The token can perform any API action you're authorized to do across all your resources and workspaces." Authenticates via `Authorization: Bearer <TOKEN>`.
- **Workspace token** — scoped to a specific workspace; cannot access personal resources or other workspaces. Authenticates via `Authorization: Bearer <TOKEN>`.
- **Project token** — "scoped to a specific environment within a project and can only be used to authenticate requests to that environment." Uses a **different header**: `Project-Access-Token: <TOKEN>`, **not** `Authorization: Bearer`.
- The `{me{id}}` query (used by the repo's `Validate Railway secrets` step) **cannot be used with workspace or project tokens** because the data returned is scoped to the personal account. Only account tokens satisfy this query.

---

### 2. Token Expiration Behavior

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Using Github Actions with Railway](https://blog.railway.com/p/github-actions)
**Authority**: Official Railway documentation and blog
**Relevant to**: Why the token keeps expiring after every rotation.

**Key Information**:

- The official Railway API docs and the GitHub Actions blog post do **not** publicly mention TTL settings, expiration durations, or a "No expiration" option for Account/Workspace/Project tokens. The internal runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` claims such an option exists, but I could not corroborate that claim from any authoritative public source.
- OAuth access tokens (a separate flow, not what CI uses) "expire after one hour"; refresh tokens are documented as the way to obtain new access tokens for long-lived workloads.
- Railway's general troubleshooting guidance: "If API requests start failing with authentication errors, check whether the token has expired."

**Implication**: Either (a) the rotator is not selecting "No expiration" (human error during manual rotation), (b) the option is named differently or was removed, or (c) tokens are being revoked by some other mechanism (e.g., session reset, account-level security event). After 39 occurrences, this is no longer plausibly random — the rotation procedure itself is broken or based on a faulty assumption.

---

### 3. Recommended Token Type for GitHub Actions

**Source**: [Using Github Actions with Railway](https://blog.railway.com/p/github-actions), [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway blog; Railway community Q&A
**Relevant to**: Whether the repo should switch token types.

**Key Information**:

- Railway's official GitHub Actions blog post recommends **Project tokens**: "Project tokens allow the CLI to access all the environment variables associated with a specific project and environment." Stored in repo secrets, exposed as `RAILWAY_TOKEN` in the workflow.
- For some Actions operations (notably PR-environment workflows that need to *create* environments), an **account-scoped token** is required and conventionally stored as `RAILWAY_API_TOKEN`. Per the docs: "If both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` environment variables are set, `RAILWAY_TOKEN` takes precedence."
- Team/Workspace tokens "cannot create or link projects" — limited utility for some flows.

---

### 4. "RAILWAY_TOKEN invalid or expired" Community Reports

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community help station (user reports, including community member commentary; not Railway staff)
**Relevant to**: Diagnosing the exact error this CI reports.

**Key Information**:

- A community member (`bytekeim`) claims Railway changed its token requirements at some point and that the system began rejecting **account-level tokens** with this exact "invalid or expired" message regardless of recency. The recommended fix in the thread is to switch to a **project-level token** generated under the project's Settings → Tokens.
- The thread also recommends removing or renaming any `RAILWAY_API_TOKEN` variable that may be set, on the grounds it can interfere.
- **Caveat**: This was a community post, not an official Railway statement. Treat the "Railway changed its token requirements" claim as a hypothesis, not as confirmed.

---

### 5. GraphQL Endpoint and `me` Query Scope

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [GraphQL requests returning "Not Authorized" for PAT — Railway Help Station](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Official docs; community
**Relevant to**: Whether the validation step itself is structurally compatible with the recommended token type.

**Key Information**:

- Endpoint: `https://backboard.railway.app/graphql/v2` (the URL the workflow uses). One community post claimed `backboard.railway.com` is correct; the `.app` URL is what the official docs and CLI use today.
- "There are only two token scopes [in some discussions]: personal access tokens (highest level, working with essentially any workspace) and workspace access tokens (limited to queries regarding that workspace). For the `me` query you'll need a personal access token while for getting projects, either will work."
- **Critical mismatch**: The repo's `Validate Railway secrets` step runs `{me{id}}`. If the team rotates to a Project token (per the GitHub Actions blog recommendation in #3), this validation query will return "Not Authorized" *even with a perfectly valid token*. The validation query was designed for account tokens specifically.

---

## Code Examples

The current validation step (from CI logs):

```bash
# From .github/workflows/staging-pipeline.yml (visible in run 25238494833 logs)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: ***" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
fi
```

If the project ever switches to a **Project token**, both the header and the query must change. From [Railway API docs](https://docs.railway.com/integrations/api):

```bash
# Project-token-compatible probe (header is Project-Access-Token, not Bearer)
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

(Exact safe probe query for project tokens is not given verbatim in the docs I read — confirm against the GraphQL schema before implementing.)

---

## Gaps and Conflicts

- **No official confirmation of a "No expiration" option** in Railway's token UI from the public docs I reviewed. The internal runbook asserts it exists. Either the docs are silent on a real feature, or the runbook is mistaken. Worth verifying directly against `https://railway.com/account/tokens` during the next rotation.
- **Conflicting claim** about whether account tokens still work for deploys: one community thread says Railway moved away from accepting account tokens; the official blog and current docs still describe account tokens as the broadest-scope token. The 39 successful-then-expired cycles suggest the token *does* work for a while after each rotation, so account tokens are not categorically rejected — they expire.
- **Endpoint discrepancy** (`.app` vs `.com`): one community post claimed `.com` is correct; the docs and the CLI use `.app`. The current workflow uses `.app` and gets `Not Authorized` rather than a connection error, so the endpoint is fine.
- **Why 39 occurrences?** Public sources do not explain a mechanism by which a "No expiration" token would still get revoked. Possibilities not covered by docs: workspace owner changes, password resets invalidating tokens, Railway-side mass revocation events, billing/plan downgrades. None of these are documented as token-revoking events publicly.

---

## Recommendations

Based on research, ordered by likely impact:

1. **Do NOT attempt to rotate the token from this agent.** Per `CLAUDE.md`, this is a Category 1 error. File an issue / send mail to mayor and direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`. The recurrence count (39) is itself a finding — escalate it, do not paper over it.

2. **When the human next rotates, capture ground truth on the "No expiration" option.** Have them screenshot or note the exact UI label and confirm the token is created without TTL. If the option does not exist as documented in the runbook, the runbook is wrong and needs an update — that is the root cause of the recurrence pattern.

3. **Consider migrating the deploy job to a Project token** ([Railway's recommendation for GitHub Actions](https://blog.railway.com/p/github-actions)). This requires three coordinated changes:
   - Generate a Project token under the project's Settings → Tokens (not Account → Tokens).
   - Update `.github/workflows/staging-pipeline.yml` to use `Project-Access-Token: $RAILWAY_TOKEN` instead of `Authorization: Bearer $RAILWAY_TOKEN`.
   - Replace the `{me{id}}` validation query with a query compatible with project tokens (e.g., `{ projectToken { projectId } }` — confirm against the schema).
   This is a real refactor, not an in-scope fix for issue #854. Send it to mayor as a follow-up suggestion rather than implementing it speculatively.

4. **Long-term**: investigate whether the Railway CLI's OAuth flow (with refresh tokens) could replace the static `RAILWAY_TOKEN`. Refresh tokens are designed exactly for "background jobs / scheduled tasks / avoiding frequent re-authentication" per [Login & Tokens](https://docs.railway.com/integrations/oauth/login-and-tokens). This would require a custom Railway OAuth app and a stored refresh token — significantly more work than rotation, but eliminates the recurrence.

5. **Do not modify the validation step in this PR.** The validation step is correctly catching expired tokens; the bug is upstream (the token expires). Removing or weakening the validation would mask the failure but ship a broken deploy.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Token types, headers, `me` query scope |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth/refresh token flow |
| 3 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Official recommendation: Project token for GH Actions |
| 4 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community report of identical error message |
| 5 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account vs Project vs Workspace token guidance for Actions |
| 6 | Railway Help Station — GraphQL "Not Authorized" for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Community note that `me` requires personal/account token |
| 7 | Railway Docs — Deploying with the CLI | https://docs.railway.com/cli/deploying | RAILWAY_TOKEN usage in CLI |
| 8 | Railway Docs — GitHub Actions PR Environment | https://docs.railway.com/tutorials/github-actions-pr-environment | Account-scoped `RAILWAY_API_TOKEN` for some flows |
