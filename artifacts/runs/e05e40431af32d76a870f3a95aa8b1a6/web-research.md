---
name: Web Research — Issue #798 (Railway token expiration, recurring)
description: External research on Railway token types, expiration semantics, and GraphQL auth headers — informs why RAILWAY_TOKEN keeps "expiring" and how to break the cycle.
type: investigation
---

# Web Research: fix #798

**Researched**: 2026-04-30T18:00Z
**Workflow ID**: e05e40431af32d76a870f3a95aa8b1a6
**Issue**: [#798 — Prod deploy failed on main](https://github.com/alexsiri7/reli/issues/798)

---

## Summary

Issue #798 is the ~19th recurrence (prior incidents include #733, #739, #742, #786, #789, #790, #793, #794) of the staging deploy failing with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Web research surfaces a likely root cause beyond "the token's TTL ran out": **Railway has multiple token types, each with a different HTTP auth header and different scopes, and the current workflow's validation query (`{me{id}}`) is silently incompatible with two of the three types.** A token of the wrong type returns `Not Authorized` *immediately* and is indistinguishable from an expired token. Today's rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) doesn't disambiguate token type, doesn't mention the workspace-dropdown trap, and doesn't include a verification step — three plausible explanations for why each rotation only buys a few days.

---

## Findings

### 1. Railway has three token types with three different auth headers

**Source**: [Railway Public API docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why the `{me{id}}` validation query fails after a "valid" rotation

**Key Information**:

- Account/Personal tokens → `Authorization: Bearer <token>`
- Workspace (team) tokens → `Authorization: Bearer <token>` (also documented elsewhere as `Team-Access-Token: <token>`)
- Project tokens → **`Project-Access-Token: <token>`** (NOT `Authorization: Bearer`)

Direct quote: *"Project tokens use the `Project-Access-Token` header, not the `Authorization: Bearer` header used by account, workspace, and OAuth tokens."*

Project tokens are created in **project settings → Tokens**, not in the account-level tokens page. Account tokens are created at `https://railway.com/account/tokens`.

---

### 2. The `{me{id}}` validation query only works for personal/account tokens

**Source**: [Railway Help Station — "GraphQL requests returning Not Authorized for PAT"](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Multiple Railway support threads with consistent answers
**Relevant to**: Why `.github/workflows/staging-pipeline.yml:49-58` and `railway-token-health.yml:44-52` may be falsely flagging healthy tokens as "expired"

**Key Information**:

- `query { me { id } }` returns `Not Authorized` for project tokens and team/workspace tokens because `me` resolves to *personal* account data.
- A token that passes `{me{id}}` must be a **personal/account token with no workspace scoping**.
- A token that fails `{me{id}}` may still be a perfectly valid token of the wrong type — the error is not a TTL signal.

This means the current health check (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) cannot distinguish *expired* from *wrong-type* — and the rotation runbook bakes that ambiguity in.

---

### 3. `RAILWAY_TOKEN` (the env var) has type-strict CLI semantics that may differ from raw GraphQL

**Source**: [Railway Help Station — "RAILWAY_TOKEN invalid or expired"](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20), [Railway docs — Using the CLI](https://docs.railway.com/guides/cli), [Railway blog — GitHub Actions](https://blog.railway.com/p/github-actions)
**Authority**: Railway docs + multiple confirming forum answers
**Relevant to**: Naming convention vs. actual usage in this repo

**Key Information**:

- For the **Railway CLI**, the env vars are split: `RAILWAY_TOKEN` accepts **only project tokens**; `RAILWAY_API_TOKEN` accepts account/workspace tokens.
- Direct quote: *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token...it literally says 'invalid or expired'"*
- The official Railway GitHub Actions blog post recommends `RAILWAY_TOKEN` paired with a **project token** and the `railway up --service=...` CLI command.
- However, **this repo bypasses the CLI**. `staging-pipeline.yml` calls `https://backboard.railway.app/graphql/v2` directly with `Authorization: Bearer $RAILWAY_TOKEN`. That code path requires an account or workspace token and would never accept a project token (the header would be wrong).
- Net: the env var is named per the CLI convention but holds an account-token's worth of trust. That naming mismatch is fine functionally but invites the wrong rotation pattern.

---

### 4. The workspace-dropdown trap when creating account tokens

**Source**: [Railway Help Station — RAILWAY_API_TOKEN not respected](https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135), surfaced in the third WebSearch result for `"RAILWAY_TOKEN" "Not Authorized"`
**Authority**: Multiple support threads
**Relevant to**: Why a freshly-rotated account token can still fail

**Key Information**:

- On the account tokens page, the workspace dropdown defaults to your default workspace. If you accept the default, you get a **workspace-scoped token**, not a true account-scoped token.
- Workspace tokens **cannot** call `me{id}` — they fail with `Not Authorized`, looking identical to expiry.
- To create a true account-scoped token: leave the workspace dropdown **blank**.

---

### 5. Account-token TTL behavior

**Source**: [Railway docs — Login & Tokens (OAuth)](https://docs.railway.com/integrations/oauth/login-and-tokens), corroborated by RAILWAY_TOKEN_ROTATION_742.md
**Authority**: Official Railway docs
**Relevant to**: Whether "no expiration" exists for the right token type

**Key Information**:

- OAuth access tokens last 1 hour; OAuth refresh tokens last 1 year. (Not what we use, but indicates Railway's general posture: every credential has a TTL.)
- Personal/Account API tokens **can** be created with "No expiration" in the dashboard. Default TTL options (1 day / 7 days / 30 days / no expiration) are presented at creation time.
- The provided docs do **not** specify whether project tokens have a TTL; community reports say they don't expire on a fixed timer but can be revoked or deleted.

---

### 6. `serviceInstanceDeploy` token-type requirement

**Source**: [Railway Help Station — "Trigger redeploy after docker image rebuild"](https://station.railway.com/questions/trigger-redeploy-after-docker-image-rebu-161d2f2d)
**Authority**: Railway support forum, Railway-engineer-confirmed
**Relevant to**: Whether the actual deploy step (lines 80-88 of staging-pipeline.yml) needs the same token type as the validation step

**Key Information**:

- `serviceInstanceDeploy` and `serviceInstanceUpdate` are confirmed to work with **personal/account tokens with no team** (i.e., the same "leave-the-workspace-blank" creation pattern).
- Team-scoped tokens reportedly fail this mutation.
- This means the validation step (`{me{id}}`) and the deploy step are aligned in their token-type requirement — but rotation must produce *exactly* a no-team account token to satisfy both.

---

## Code Examples

### Verifying a Railway token before storing it as a GitHub secret

```bash
# From [Railway Public API docs](https://docs.railway.com/integrations/api)
# Account/personal/workspace tokens — Bearer header
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id email}}"}'
# ✅ Expected for account-scoped (no-workspace) token: {"data":{"me":{"id":"...","email":"..."}}}
# ❌ Workspace-scoped token: {"errors":[{"message":"Not Authorized"}]} — DO NOT use as RAILWAY_TOKEN
```

```bash
# Project token — different header
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $PROJECT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{projectToken{projectId environmentId}}"}'
```

### Official Railway recommendation for GitHub Actions (CLI flavor)

```yaml
# From Railway blog: https://blog.railway.com/p/github-actions
env:
  SVC_ID: my-service-id
  RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}   # project token
steps:
  - uses: actions/checkout@v3
  - run: railway up --service=${{ env.SVC_ID }}
```

This repo uses raw GraphQL instead — keeping the workflow but improving the rotation runbook is the path of least disruption.

---

## Gaps and Conflicts

- **Project token TTL**: Official docs do not state a TTL; forum reports say "indefinite until revoked." If the Railway CLI flavor (project token + `railway up`) were adopted, the rotation problem might disappear, but this is unverified.
- **Whether account tokens silently rotate on workspace membership changes**: One forum thread hinted that being added/removed from a team can invalidate workspace-scoped tokens. Could explain *some* recurrences but not all.
- **GitHub OIDC for Railway**: No evidence Railway supports OIDC-based federated auth for CI yet. (Would be the durable fix; it would replace static tokens entirely.) Not currently available based on docs surveyed.

---

## Recommendations

These are research-derived suggestions for the human who rotates the token (and for whoever updates the runbook). **Implementation is out of scope for this research artifact and the agent cannot execute the rotation itself (per CLAUDE.md "Railway Token Rotation").**

1. **Update `docs/RAILWAY_TOKEN_ROTATION_742.md` to specify the exact token type and creation pattern**:
   - Account/Personal token, **workspace dropdown LEFT BLANK** (critical), **"No expiration"** selected.
   - Created at `https://railway.com/account/tokens` (this URL is correct in the runbook, but the workspace caveat is missing).
   - Add a verification command before pasting into GitHub Secrets:
     ```bash
     curl -sf -X POST https://backboard.railway.app/graphql/v2 \
       -H "Authorization: Bearer $NEW_TOKEN" -H "Content-Type: application/json" \
       -d '{"query":"{me{id email}}"}' | jq -e '.data.me.id'
     ```
     If this fails with `Not Authorized`, the token is the wrong type — *do not* set the secret yet.

2. **Improve the health-check error message** in `.github/workflows/staging-pipeline.yml:49-58` and `.github/workflows/railway-token-health.yml:44-52`. Today it says "invalid or expired" for *any* `Not Authorized` response, conflating three distinct failure modes (expired, wrong type, workspace-scoped). A more useful message would be:
   > "RAILWAY_TOKEN failed `{me{id}}`. This means: (a) the token expired, (b) it is a project token (use Project-Access-Token header instead), or (c) it is workspace-scoped (recreate with workspace blank). See docs/RAILWAY_TOKEN_ROTATION_742.md."

3. **Consider migrating to the Railway CLI flavor** (`railway up --service=...` with a project token in `RAILWAY_TOKEN`). Project tokens reportedly do not expire and are tied to a specific service/environment, which is closer to least-privilege. This is a larger change — file as a follow-up issue, do not bundle.

4. **Do not** create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. CLAUDE.md explicitly forbids this and labels it a Category 1 error. The rotation must be performed by a human with Railway dashboard access.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs | https://docs.railway.com/integrations/api | Authoritative source for token types and HTTP headers |
| 2 | Railway docs — Using the CLI | https://docs.railway.com/guides/cli | Splits `RAILWAY_TOKEN` (project) from `RAILWAY_API_TOKEN` (account/workspace) |
| 3 | Railway docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTL semantics |
| 4 | Railway blog — GitHub Actions | https://blog.railway.com/p/github-actions | Official CI/CD recommendation (project token + CLI) |
| 5 | Railway Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Confirms token-type confusion is the most common cause |
| 6 | Railway Station — GraphQL Not Authorized for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | `me{id}` only works with personal/account tokens |
| 7 | Railway Station — RAILWAY_API_TOKEN not respected | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | The workspace-dropdown trap |
| 8 | Railway Station — Trigger redeploy via API | https://station.railway.com/questions/trigger-redeploy-after-docker-image-rebu-161d2f2d | `serviceInstanceDeploy` requires a no-team account token |
| 9 | Railway Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Cross-validates the CLI/GitHub-Actions recipe |
| 10 | Railway Station — Authentication not working with RAILWAY_TOKEN | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | Additional corroboration of token-type errors |
