# Web Research: fix #800

**Researched**: 2026-04-30T19:05:00Z
**Workflow ID**: e02f5757b5e3c7f37e9b93b9127881f7
**Issue**: [alexsiri7/reli#800 — Main CI red: Deploy to staging](https://github.com/alexsiri7/reli/issues/800)

---

## Summary

Issue #800 is the latest in a long string (~20 in three days) of `RAILWAY_TOKEN is invalid or expired: Not Authorized` failures from the `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml`. Web research surfaced two findings that the existing rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) does not capture and that may explain why rotations keep failing within hours: (1) the validation query `{me{id}}` is **only** valid against an **account token** with no workspace assignment ("No Team / No workspace"), so a workspace- or project-scoped token will return `Not Authorized` immediately even though it is freshly issued; (2) Railway's public docs do **not** document any TTL knob on account or workspace tokens, but community threads repeatedly report that the `Not Authorized` error message is misleading — it usually signals a token-type mismatch rather than actual expiration. Together these point at a likely root cause: each rotation may produce a token that is not the right type for this workflow's probe query, so the very next CI run fails. The agent **cannot** verify or rotate the token (CLAUDE.md "Railway Token Rotation" is explicit), but the human rotator should be told to (a) create the token at `https://railway.com/account/tokens` with **No workspace / No Team** selected, and (b) ideally adjust the validation step to use a query compatible with whichever token type is actually issued.

---

## Findings

### 1. Railway token types — three distinct kinds, different headers

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why the `Validate Railway secrets` step keeps returning `Not Authorized` even after rotation

**Key Information**:

- Three token types: **account**, **workspace** (a.k.a. team), and **project** tokens.
- Authentication header differs by type:
  - Account & workspace tokens → `Authorization: Bearer <TOKEN>`
  - Project tokens → `Project-Access-Token: <TOKEN>` (NOT `Authorization: Bearer`)
- Quote: *"Project tokens use the `Project-Access-Token` header, not the `Authorization: Bearer` header used by account, workspace, and OAuth tokens."*
- Canonical endpoint per docs: `https://backboard.railway.com/graphql/v2` (the workflow currently uses `backboard.railway.app`, which has been an accepted alias historically but is not the canonical hostname).
- Account tokens are created at `https://railway.com/account/tokens`. Project tokens are created from the project's settings → tokens page.

---

### 2. The `{me{id}}` probe query only works with an account token

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: The exact validation step that fails in #800 (`.github/workflows/staging-pipeline.yml:49-58`)

**Key Information**:

| Query | Compatible token types |
|-------|------------------------|
| `query { me { name email } }` | **Account tokens only** |
| `query { workspace(workspaceId: "...") { name id } }` | Account & workspace tokens |
| `query { projectToken { projectId environmentId } }` | Project tokens only |

- Quote: *"This query [`me`] cannot be used with a workspace or project token because the data returned is scoped to your personal account."*
- Implication for `staging-pipeline.yml`: if the rotated `RAILWAY_TOKEN` is anything other than an account token (e.g. a workspace token or a project token), the `Validate Railway secrets` step will emit `RAILWAY_TOKEN is invalid or expired: Not Authorized` even though the token is healthy and recent.

---

### 3. `serviceInstanceUpdate` / `serviceInstanceDeploy` mutations require an account token with **No Team**

**Source**: [Trigger redeploy after docker image rebuild — Railway Help Station](https://station.railway.com/questions/trigger-redeploy-after-docker-image-rebu-161d2f2d)
**Authority**: Railway Help Station thread with employee response
**Relevant to**: The actual deploy step (`.github/workflows/staging-pipeline.yml:71-88` and `:188-205`)

**Key Information**:

- Quote (employee): *"You would be using the wrong token — `https://railway.app/account/tokens` `Team` → `No Team`"*.
- A token created **inside a team workspace** does not authorize `serviceInstanceDeploy`. The token must be issued under the **No Team** account section.
- This is the same constraint as Finding #2 — both the probe query and the deploy mutations want an account-scoped token.

---

### 4. "Invalid or expired" is frequently a token-type error, not real expiration

**Source 4a**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Source 4b**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway community help station (user reports)
**Relevant to**: Why rotations don't stick — the misleading error message

**Key Information**:

- Quote (4a): *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token … it literally says 'invalid or expired' even if u just made it 2 seconds ago."* Note: this user's claim is the opposite of Finding #3 — the disagreement is itself evidence that the wire-level error is identical regardless of cause, so the message alone is unreliable for diagnosis.
- Quote (4a, on env-var conflicts): *"if u have RAILWAY_API_TOKEN set at the same time, delete it or rename it cuz RAILWAY_TOKEN wins and screws everything up if its wrong."*
- Quote (4b): *"Do NOT set a workplace [sic] just leave it 'No workspace' and click Create. Try that token."*
- **Currency caveat**: these are user posts, not official Railway statements. Treat as strong-signal hypotheses to test, not as ground truth.

---

### 5. No documented TTL knob for account or workspace tokens

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Public API | Railway Docs](https://docs.railway.com/guides/public-api)
**Authority**: Official Railway documentation
**Relevant to**: The premise in `docs/RAILWAY_TOKEN_ROTATION_742.md` that *"the new token must be created with 'No expiration'"*

**Key Information**:

- The `Login & Tokens` page documents OAuth-flow tokens only: *"Access tokens expire after one hour"* and refresh tokens have a *"fresh one-year lifetime from the time of issuance"*.
- The `Public API` page documents how to create account, workspace, and project tokens but **does not surface any TTL option or "no expiration" toggle** in the public docs.
- Implication: the existing runbook's instruction to choose *"Expiration: No expiration (critical — do not accept default TTL)"* may be referring to a UI control that exists in Railway's dashboard but is not documented publicly. If that toggle does not exist in the current dashboard, the runbook's claim is wrong, which would explain why rotations using the runbook keep failing within hours.
- **This is a gap that should be verified by the human rotator at the dashboard.**

---

### 6. GitHub Actions pattern: prefer OIDC / federated identity over long-lived deploy tokens

**Source**: [GitHub Docs — OpenID Connect](https://docs.github.com/en/actions/concepts/security/openid-connect), [Wiz — Hardening GitHub Actions](https://www.wiz.io/blog/github-actions-security-guide)
**Authority**: GitHub official docs + recognized security vendor
**Relevant to**: Strategic alternative if rotations remain unreliable

**Key Information**:

- GitHub Actions supports OIDC, allowing workflows to authenticate to cloud providers via short-lived, identity-bound tokens — eliminating long-lived secrets entirely.
- Wiz (paraphrased): *"Where possible, use dynamic secrets or short-lived secrets … that automatically expire after a certain period, reducing the window of opportunity for bad actors to exploit stale secrets."*
- **Railway does not currently appear to support OIDC federation for GitHub Actions.** Documented Railway integration paths are: (a) project tokens stored in `RAILWAY_TOKEN`, (b) account tokens for GraphQL automation, (c) Railway's GitHub app which does its own deploys without GitHub Actions secrets.
- Implication: short of waiting for Railway to ship OIDC, the only structural fix is to either (i) make the rotation reliable (correct token type + verify expiry behavior), or (ii) move the deploy off GitHub Actions onto Railway's own GitHub integration.

---

## Code Examples

### Working validation that doesn't depend on token type (proposed)

The current step assumes an account token. A more tolerant probe — useful if the project ever switches to a project-scoped token — could route by header:

```bash
# From [Public API | Railway Docs](https://docs.railway.com/integrations/api)
# (composed example, not a Railway-published snippet)

# Account/workspace token path
curl -sf -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ me { id } }"}'

# Project token path (different header, different probe query)
curl -sf -X POST https://backboard.railway.com/graphql/v2 \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

The current workflow at `.github/workflows/staging-pipeline.yml:49-58` only probes the first path, so any non-account token is reported as "expired" regardless of actual validity.

---

## Gaps and Conflicts

- **Gap**: Railway's public docs do not state a TTL for account or workspace tokens, nor surface a "No expiration" toggle. The rotation runbook claims this toggle exists in the dashboard UI — that claim could not be corroborated from public documentation. A human rotator should confirm what options the dashboard actually offers.
- **Gap**: No authoritative Railway statement was found about whether tokens issued in a team/workspace context auto-rotate, get revoked when team membership changes, or expire on dashboard activity. Community threads disagree.
- **Conflict**: Source 4a says `RAILWAY_TOKEN now only accepts project token` (i.e. account token returns "invalid or expired"). Sources 1, 2, and 3 say `serviceInstanceDeploy` and `{me{id}}` require an account token. The community thread (4a) is likely conflating CLI behavior (`railway up` with `RAILWAY_TOKEN` does want a project token) with API behavior (the GraphQL mutations this workflow uses want an account token). The workflow uses raw `curl` against GraphQL, so the official-docs guidance (account token) applies — but this is worth flagging because using the wrong heuristic in the rotation runbook would explain the recurring failures.
- **Currency**: most cited Help Station threads have no dates visible in the fetched content; treat the technical claims as plausible signals rather than authoritative.

---

## Recommendations

1. **Do not attempt to fix this in code from the agent's side.** Per `CLAUDE.md` ("Railway Token Rotation"), the agent cannot rotate the token and must not write a `RAILWAY_TOKEN_ROTATION_*.md` file claiming it has. File the issue / mail to mayor with the error details and direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`. This issue (#800) is already filed by the cron, so the next step is mail-to-mayor with the new findings below.
2. **Surface to the human rotator the token-type constraint** before they create the next token: the GitHub-Actions-side `RAILWAY_TOKEN` must be an **account token created with "No workspace / No Team"**, because both the probe query (`{me{id}}`) and the deploy mutations (`serviceInstanceUpdate`, `serviceInstanceDeploy`) require that scope. If the previous rotations used a workspace-scoped token, that alone explains every "Not Authorized" failure since #742.
3. **Verify the "No expiration" claim in the runbook against the live dashboard.** If the dashboard does not offer that toggle, update `docs/RAILWAY_TOKEN_ROTATION_742.md` to remove the false reassurance and document whatever the actual maximum TTL is. The repeated multi-rotation pattern strongly suggests the runbook's premise is wrong.
4. **Consider hardening the validation step** so the next failure produces a more actionable error — e.g. detect token type via a fallback `Project-Access-Token` probe and report which type was supplied. This is out of scope for this bead (Polecat Scope Discipline) but worth a separate mail to mayor.
5. **Long-term**: evaluate Railway's first-party GitHub integration (no Actions secret needed) as a replacement for the curl-against-GraphQL deploy path, since Railway does not yet offer OIDC federation for GitHub Actions.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Official statement on token types, headers, query compatibility |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | Documented TTLs (OAuth only); no permanent-token toggle documented |
| 3 | Railway Docs — Public API guide | https://docs.railway.com/guides/public-api | Token creation URL, no TTL options surfaced |
| 4 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community report that the error is usually a token-type mismatch |
| 5 | Railway Help Station — API Token "Not Authorized" | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | "No workspace" guidance for new tokens |
| 6 | Railway Help Station — Trigger redeploy after docker image rebuild | https://station.railway.com/questions/trigger-redeploy-after-docker-image-rebu-161d2f2d | Employee guidance: deploy mutations require **No Team** account token |
| 7 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account-scoped token recommended for GitHub Actions |
| 8 | GitHub Docs — OpenID Connect | https://docs.github.com/en/actions/concepts/security/openid-connect | Pattern for short-lived federated tokens (not yet supported by Railway) |
| 9 | Wiz — Hardening GitHub Actions | https://www.wiz.io/blog/github-actions-security-guide | General secret-rotation guidance for CI |
| 10 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Confirms long-lived `RAILWAY_TOKEN` is the documented integration path |
