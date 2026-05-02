---
name: Web Research — Issue #903
description: Web research for issue #903 (Railway token expiration, 60th occurrence) — what Railway's docs and community say about token types, expiration behavior, and CI integration
type: project
---

# Web Research: fix #903

**Researched**: 2026-05-02T16:30:00Z
**Workflow ID**: 20f0bd115fe4c3a0d2dd10f737e6f8e5
**Issue**: Main CI red — `RAILWAY_TOKEN is invalid or expired: Not Authorized` on Deploy to staging job (run 25255409159, SHA 86aca5c)

---

## Summary

Issue #903 is the 60th recurrence of the Railway token expiration problem. Per `CLAUDE.md`, **agents cannot rotate this token** — it lives in GitHub Actions secrets and requires human access to railway.com. The web research below is therefore aimed at the **underlying question** of why this keeps recurring: it surfaces three concrete findings that the existing runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) does not capture, and which a human rotator may want to act on next time. Headline finding: the workflow uses `Authorization: Bearer` with the `{me{id}}` query — that combination requires a **personal/account token**, not a project or workspace token, and Railway's public docs do **not** document a "no expiration" option for these tokens, contradicting the existing runbook's "Expiration: No expiration (critical)" instruction.

---

## Findings

### 1. Railway has three distinct token types, with different headers and capabilities

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Choosing the correct token type for the staging-pipeline workflow

**Key Information**:

- **Account (personal) tokens** — broadest scope, tied to a Railway account, "access across all resources and workspaces"; created at https://railway.com/account/tokens. Use `Authorization: Bearer <token>` header.
- **Workspace tokens** — scoped to a single workspace, "ideal for team CI/CD and shared automation". Use `Authorization: Bearer <token>` header.
- **Project tokens** — limited to "a specific environment within a project", created from project settings (not account settings). Use the **`Project-Access-Token`** header (NOT `Authorization: Bearer`).
- The CLI environment variables map: `RAILWAY_TOKEN` is for project-level actions, `RAILWAY_API_TOKEN` is for account-level actions ([CLI docs](https://docs.railway.com/guides/cli)). When both are set, `RAILWAY_TOKEN` takes precedence.

---

### 2. The `{me{id}}` validation query requires a personal access token

**Source**: [GraphQL requests returning "Not Authorized" for PAT — Railway Help Station](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Railway community moderator response
**Relevant to**: The exact validation query in `.github/workflows/staging-pipeline.yml:52`

**Key Information**:

- Direct quote: *"The `query { me { id email } }` query specifically requires a personal access token (PAT)."*
- Project tokens cannot query `me` — they will return "Not Authorized" even when freshly issued.
- Workspace tokens reportedly can't access `me` or `teams` queries either; "you need to generate a personal token from your Railway account settings."
- Project tokens can read project info but can return "Not Authorized" for deployment-triggering mutations as well — see [Railway API Token Permissions Issue](https://station.railway.com/questions/railway-api-token-permissions-issue-4dfeffde).

**Implication for our workflow**: Our validation step (`{me{id}}`) and our deployment mutation (`serviceInstanceUpdate`) are both run with `Authorization: Bearer $RAILWAY_TOKEN`. This is the **personal/account token pattern**, not the project token pattern. The secret name `RAILWAY_TOKEN` is misleading — Railway CLI semantics reserve that name for project tokens, but our raw curl-based workflow is using it as a personal/account token. The secret should arguably be renamed `RAILWAY_API_TOKEN` to match Railway's own conventions, or the rotation runbook should make explicit that the rotator must create an **account token** (not a project token).

---

### 3. Railway's public docs do NOT document a "No expiration" option for API tokens

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [CLI | Railway Docs](https://docs.railway.com/cli)
**Authority**: Official Railway documentation (multiple pages)
**Relevant to**: The existing runbook's claim that "Expiration: No expiration" is a selectable option

**Key Information**:

- The Public API page documents account/workspace/project token types and creation procedure but **does not specify token expiration behavior, TTL, default expiration, or any "no expiration" option**.
- The CLI page does not mention token TTL.
- The Login & Tokens (OAuth) page documents OAuth-flow tokens only: OAuth access tokens expire after 1 hour, refresh tokens last 1 year and rotate. This is unrelated to dashboard-issued API tokens.
- Multiple targeted searches for "Railway API token TTL", "no expiration", "30/90 days" returned no official guidance on configurable expiration.

**Implication**: `docs/RAILWAY_TOKEN_ROTATION_742.md` instructs the rotator to "Expiration: No expiration (critical — do not accept default TTL)". If Railway's dashboard no longer (or never) offered that option, every rotation since #742 has been creating a token that will expire on whatever default Railway applies. This is consistent with the recurrence pattern (60 expirations). **A human with dashboard access should verify on https://railway.com/account/tokens whether a "No expiration" option still exists, and if not, the runbook needs to be updated to reflect reality** — possibly switching to a scheduled rotation cadence rather than promising perpetual tokens.

---

### 4. Railway provides no API-side automated refresh / rotation for dashboard tokens

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Ability to run all railway commands with RAILWAY_TOKEN · Issue #105](https://github.com/railwayapp/cli/issues/105)
**Authority**: Official Railway docs and the official Railway CLI repo
**Relevant to**: Whether automation (an Action, a cron) could rotate the token without a human

**Key Information**:

- Refresh-token rotation exists **only inside the OAuth 2.0 flow** (requiring `offline_access` scope and a registered OAuth app).
- Dashboard-created account/workspace/project tokens have no documented refresh endpoint.
- There is no publicly documented API for *creating* a new account-level API token programmatically — token creation is a dashboard-only action.

**Implication**: The CLAUDE.md restriction ("Agents cannot rotate the Railway API token") is correct and is a property of Railway's design, not just our policy. The only paths to reduce recurrence are: (a) ensure a non-expiring token type is used if available, (b) move to OAuth + refresh-token rotation (requires registering an OAuth app and refactoring the workflow), or (c) accept the cadence and schedule a calendar reminder ahead of expected expiry.

---

### 5. The Railway API endpoint in the workflow may be on the legacy host

**Source**: [Railway GraphQL API documentation (Postman)](https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api), Help Station threads
**Authority**: Community documentation
**Relevant to**: The endpoint string in `.github/workflows/staging-pipeline.yml:49`

**Key Information**:

- The current workflow targets `https://backboard.railway.app/graphql/v2`.
- One community source asserts the correct endpoint is now `https://backboard.railway.com/graphql/v2` (matching Railway's domain rebrand from `.app` to `.com`).
- This is **not** likely the cause of issue #903 — the API returned a structured `{"errors":[{"message":"Not Authorized"}]}` payload, which means the endpoint accepted the request but rejected the token. So the host is at minimum still routing.
- Worth flagging only as an aside; do not change as part of fixing #903.

---

## Code Examples

The validation step in the workflow exactly matches the "personal access token" pattern from Railway's community — including the bearer header and the `{me{id}}` query:

```yaml
# From .github/workflows/staging-pipeline.yml:49-52
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

Railway community guidance ([source](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)):

> "The `query { me { id email } }` query specifically requires a personal access token."

So the secret currently labelled `RAILWAY_TOKEN` must in fact be a **personal/account token from https://railway.com/account/tokens**, and the CLAUDE.md / runbook guidance directing the rotator there is correct.

---

## Gaps and Conflicts

- **Gap (most important)**: No official Railway documentation describes API token expiration semantics. We cannot confirm from public sources whether "No expiration" is or ever was an option in the dashboard. The runbook's claim relies on this — a human rotator should confirm directly in the dashboard on the next rotation.
- **Gap**: No public Railway communication about whether token TTL defaults changed at any point — which would explain why this has cascaded to 60 occurrences after the #742 runbook was written.
- **Conflict**: One Help Station thread says `RAILWAY_TOKEN` "must be a project token" (CLI semantics); another says use a "personal account token" via `RAILWAY_API_TOKEN`. The conflict resolves because **our workflow does not use the CLI** — it makes raw GraphQL calls and uses the env-var name as a label, so the semantics are governed by the GraphQL request shape (Bearer + `{me{id}}` → personal token), not by the CLI's interpretation of the variable name.
- **Gap**: Whether the new `backboard.railway.com` host should be preferred over `backboard.railway.app` is unconfirmed; the latter clearly still works (it returns structured GraphQL errors).

---

## Recommendations

These are recommendations for the human rotator (per CLAUDE.md, the agent must not rotate the token itself, must not write a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming it did, and should file an issue / mail mayor instead):

1. **At next rotation, confirm whether "No expiration" is still an offered option on https://railway.com/account/tokens.** If it is, use it. If it is **not**, update `docs/RAILWAY_TOKEN_ROTATION_742.md` to remove the false promise and replace it with a `/schedule`-based reminder cadence sized to the longest TTL the dashboard offers.
2. **Confirm the rotated token is a personal/account token** (created from account settings, not project settings). The `Authorization: Bearer` + `{me{id}}` validation requires this; project tokens will return "Not Authorized" even when fresh.
3. **Consider renaming the GitHub secret `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** to align with Railway's own CLI naming conventions and reduce future confusion about which token type is required. (Out of scope for fixing #903 — would require a coordinated workflow + secret update; flag to mayor rather than acting.)
4. **Do not change the API endpoint** as part of this fix. The `.app` host is still routing requests; the `Not Authorized` response proves the request reached Railway and was rejected by auth, not by routing.
5. **Do not attempt OAuth-based refresh rotation** as part of this fix. It would require registering an OAuth app and refactoring the workflow — a separate piece of work that should be proposed via mail to mayor, not bundled in.

For this specific bead — **the agent's only valid action is to file an issue or send mail to mayor with the error details and direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`**. The research above gives the human additional context for the rotation conversation.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs | https://docs.railway.com/integrations/api | Authoritative on token types (account/workspace/project) and headers |
| 2 | Railway CLI docs | https://docs.railway.com/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env-var semantics |
| 3 | Railway CLI guide | https://docs.railway.com/guides/cli | CI/CD usage of the env vars |
| 4 | Railway Login & Tokens (OAuth) | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token expiration (different from dashboard tokens) |
| 5 | Help Station — GraphQL "Not Authorized" for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | `{me{id}}` requires a personal access token |
| 6 | Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Common cause of the exact error in #903 |
| 7 | Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | "use a Railway API token scoped to the user account, not a project token" |
| 8 | Help Station — Authentication not working with RAILWAY_TOKEN | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | Resolution required switching to account token via `RAILWAY_API_TOKEN` |
| 9 | Help Station — Railway API Token Permissions Issue | https://station.railway.com/questions/railway-api-token-permissions-issue-4dfeffde | Project tokens return "Not Authorized" for deployment mutations |
| 10 | Railway CLI Issue #105 | https://github.com/railwayapp/cli/issues/105 | Long-standing gap: no programmatic way to refresh dashboard tokens |
| 11 | Railway GraphQL API (Postman) | https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api | GraphQL endpoint reference |
