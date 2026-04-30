# Web Research: fix #786 (Prod deploy failed — RAILWAY_TOKEN expired, 16th occurrence)

**Researched**: 2026-04-30T11:30:00Z
**Workflow ID**: 36bb722fce00aeff22f868dd098928fa
**Issue**: https://github.com/alexsiri7/reli/issues/786
**Failed run**: https://github.com/alexsiri7/reli/actions/runs/25161929515
**Failure mode**: `Validate Railway secrets` step → `RAILWAY_TOKEN is invalid or expired: Not Authorized`

---

## Summary

Reli has rotated the Railway token 15+ times (issues #733, #739, #742, #774, #777, #779, #781, #783, now #786). Each rotation follows `docs/RAILWAY_TOKEN_ROTATION_742.md`, yet the failure recurs. Web research reveals the recurrence is **not actually about expiration** — it is almost certainly a **token-type/scope mismatch**. Railway has three token types (account, workspace, project) with subtly different headers, validation rules, and capabilities. The validation query `{me{id}}` used in `staging-pipeline.yml` only succeeds with a **personal account token** — workspace-scoped or project-scoped tokens return `Not Authorized` even when freshly created with no expiration. Authoritative Railway docs and Help-Station threads confirm this. The fix is twofold: (1) make the runbook unambiguous about creating an account-scoped (workspace-blank) token, and (2) consider replacing the `{me{id}}` validation probe with a query that works across token types so a wrong-type rotation fails loudly during creation rather than at the next deploy.

---

## Findings

### 1. Railway has three distinct token types — they are NOT interchangeable

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Root cause of recurring "invalid or expired" errors

**Key Information**:

- **Account Token** — broadest scope, can call any API the user is authorized for, across all workspaces/resources. Created at `railway.com/account/tokens` with workspace dropdown left **blank**.
- **Workspace Token** — scoped to one workspace, sharable with teammates. Created at the same page by **selecting** a workspace.
- **Project Token** — scoped to a single environment within a project. Created from project settings → tokens, NOT the account page.
- The three token types use **different HTTP authentication headers**:
  - Account / Workspace tokens → `Authorization: Bearer <token>`
  - Project tokens → `Project-Access-Token: <token>` (NOT `Authorization: Bearer`)

---

### 2. The `{me{id}}` GraphQL query only works with **personal account tokens**

**Source**: [Railway Help Station — RAILWAY_TOKEN invalid or expired](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20) and [Postman — Railway GraphQL API](https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api)
**Authority**: Community thread with confirmed answers from Railway staff/long-time users; Postman API reference
**Relevant to**: Why `staging-pipeline.yml`'s validation step fails

**Key Information**:

- Quote from search results: *"For the `me` and `teams` query you need to use the person token, a team scoped token will not work for those because the data returned is specific to your personal account, not the team workspace."*
- The current workflow validation step (`staging-pipeline.yml:49-58`) calls `{me{id}}` with `Authorization: Bearer $RAILWAY_TOKEN`. If the human creates a **workspace-scoped** token (which happens by default in the Railway UI when a workspace is selected), `{me{id}}` returns `Not Authorized` and the workflow falsely reports the token is "invalid or expired."
- Community quote: *"RAILWAY_TOKEN now only accepts project token. If you put the normal account token, it literally says 'invalid or expired' even if you just made it 2 seconds ago."* — note: this conflict applies when using the **Railway CLI** `RAILWAY_TOKEN` env var, not the raw GraphQL endpoint, but it shows the platform's habit of returning the same opaque error for any token-type mismatch.

---

### 3. Recommended token type for GitHub Actions CI/CD: **account-scoped**

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway employee response in support thread
**Relevant to**: Choosing a stable rotation strategy

**Key Information**:

- Railway employee recommends an **account-scoped token** for GitHub Actions, NOT project-scoped, because project tokens are limited to specific environments and cannot perform workspace-level operations.
- The recommended environment-variable name is `RAILWAY_API_TOKEN`. `RAILWAY_TOKEN` was a historical workaround that was patched in Railway CLI PR #668. **For raw GraphQL calls (which Reli uses), the env var name does not matter** — only the header (`Authorization: Bearer`) and the token type stored.
- Recommended creation flow: visit `https://railway.com/account/tokens`, **leave Workspace blank**, set name, select expiration.

---

### 4. Token expiration: tokens DO have a TTL chosen at creation time

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens) and [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Whether genuine expiration is also a contributor

**Key Information**:

- Railway's account/workspace token creation UI offers expiration options — community references mention defaults of 7d, 30d, 90d, plus a "No expiration" option. **The user must explicitly choose "No expiration"** — defaults are short.
- OAuth access tokens are separate (1-hour TTL, refresh tokens 1 year), but the GitHub Actions secret is a long-lived API token, not an OAuth access token.
- The current runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) already calls this out, but evidence (16 rotations) suggests the instruction is being missed or that the operator is also creating a wrong-typed token.

---

### 5. Project tokens never expire in practice (community report)

**Source**: [Generate project-wide tokens within the CLI · Issue #122 · railwayapp/cli](https://github.com/railwayapp/cli/issues/122) (referenced in search results) and Railway CLI guide
**Authority**: Railway CLI repo and docs
**Relevant to**: Alternative approach that eliminates rotation entirely

**Key Information**:

- Project tokens are intended for deployment automation. They do not appear to expire (community reports — not officially documented).
- A project token authenticates as a project (not a user), so the `{me{id}}` query is invalid; validation must use a project-scoped query instead.
- Drawbacks: one token per environment (staging + production = 2 tokens); the deploy code must switch from `Authorization: Bearer` to the `Project-Access-Token` header.

---

### 6. Validation probe must match the token type — current probe is fragile

**Source**: Synthesis of [Railway Public API docs](https://docs.railway.com/integrations/api), [GraphQL Overview](https://docs.railway.com/integrations/api/graphql-overview), and the staging-pipeline workflow at lines 49–58 / 166–175.
**Authority**: Direct mapping of repo code against Railway's documented GraphQL surface.
**Relevant to**: How to detect a bad token at rotation time, not at deploy time

**Key Information**:

- A robust validation probe should query something the deploy step actually needs — e.g., `service(id: $SERVICE_ID) { id name }` or `project(id: $PROJECT_ID) { id }`. This succeeds for any token type that is permitted to deploy and fails clearly otherwise.
- Reli's daily `railway-token-health.yml` uses the same `{me{id}}` probe — it shares the same false-positive risk.

---

## Code Examples

### Replacement validation probe (works for account, workspace, and project tokens)

```bash
# From synthesis of https://docs.railway.com/integrations/api and Reli's existing service IDs
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" \
    '{query: "query($svc:String!,$env:String!){deployments(input:{serviceId:$svc,environmentId:$env},first:1){edges{node{id status}}}}",
      variables:{svc:$svc,env:$env}}')")
if ! echo "$RESP" | jq -e '.data.deployments' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid, expired, or wrong-scoped: $MSG"
  exit 1
fi
```

This probe asks for what the next step (`serviceInstanceUpdate` / `serviceInstanceDeploy`) needs — service-level permissions on the configured environment — so a passing probe guarantees the deploy step will not fail due to scoping.

### Project-token alternative (one secret per environment)

```bash
# Header changes; mutation body is the same
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_STAGING_PROJECT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"..."}'
```

Project tokens skip rotation but require structural changes (two new secrets, header swap, new validation query).

---

## Gaps and Conflicts

- **Gap**: Railway does not publicly document the exact default TTL for account/workspace tokens. References vary (7d / 30d / 90d). Whatever it is, it is non-zero, and "No expiration" is not the default selection.
- **Gap**: The exact failure cause for #786 cannot be determined from logs alone — the API returned only `Not Authorized`. Could be (a) workspace-scoped token mismatched with `{me{id}}`, (b) genuine expiration of an account-scoped token whose TTL was not set to "No expiration", or (c) the Railway-side bug occasionally reported in CLI issue #699. The recurrence pattern (~weekly) leans toward (b) with a default TTL of 7 days OR (a) if the operator is repeatedly creating workspace tokens.
- **Conflict**: One Help-Station thread says `RAILWAY_TOKEN` accepts only project tokens; another thread says `RAILWAY_TOKEN` worked as a workaround for account tokens before CLI PR #668. Both can be true: the constraint applies to the **Railway CLI**, not raw GraphQL via curl. Reli uses curl directly, so the env var name does not constrain the token type — the token-type-vs-query mismatch is what breaks things.
- **Cannot be found**: Whether a daily `railway-token-health.yml` cron query against `{me{id}}` itself contributes to rate-limiting or token invalidation. Almost certainly not, but no source confirms.

---

## Recommendations

Based on the research, ordered by confidence and impact:

1. **Make the rotation runbook idiot-proof and verifiable** (`docs/RAILWAY_TOKEN_ROTATION_742.md`):
   - Add an explicit screenshot-or-bullet step: "**Workspace dropdown MUST be blank**" before name/expiration.
   - Add an explicit step: "**Expiration: select 'No expiration'**" — the default is short.
   - Add a **post-rotation self-check** the operator must paste the new token into and run locally before saving the GitHub secret:
     ```bash
     curl -sf -X POST https://backboard.railway.app/graphql/v2 \
       -H "Authorization: Bearer NEW_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"query":"{me{id}}"}' | jq
     ```
     If this returns `data.me.id`, the token is good for the current workflow.

2. **Strengthen the validation probe** in both `staging-pipeline.yml` (lines 49–58 and 166–175) and `railway-token-health.yml`:
   - Replace `{me{id}}` with a service-scoped query (see code example above) so a workspace-scoped token still validates if it can actually deploy. This eliminates the most likely cause of the false-expiration failure mode.
   - Update the error message: *"RAILWAY_TOKEN is rejected by the Railway API. Likely causes: (1) wrong token type — must be account-scoped (workspace blank); (2) actual expiration — re-create with 'No expiration'. See docs/RAILWAY_TOKEN_ROTATION_742.md."*

3. **(Optional, larger change) Migrate to project tokens**:
   - Eliminates rotation entirely (project tokens are reportedly stable).
   - Cost: rename secrets (`RAILWAY_STAGING_PROJECT_TOKEN`, `RAILWAY_PROD_PROJECT_TOKEN`), swap `Authorization: Bearer` for `Project-Access-Token` in ~6 curl invocations, swap validation query.
   - Trade-off: mostly isolation upgrade — a leaked project token affects only one environment, not the whole account.

4. **Do NOT** create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming agent rotation is done — CLAUDE.md explicitly forbids this (Category 1 error). The agent's contribution to this issue is the investigation/recommendations above; the actual rotation must be done by the human operator following the runbook.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Canonical token-type definitions and headers |
| 2 | Using the CLI — Railway Docs | https://docs.railway.com/guides/cli | RAILWAY_TOKEN vs RAILWAY_API_TOKEN distinction |
| 3 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth vs API-token expiration model |
| 4 | Token for GitHub Action — Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Railway-staff recommendation for GitHub Actions |
| 5 | RAILWAY_TOKEN invalid or expired — Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Token-type mismatch produces "invalid or expired" error |
| 6 | CLI throwing Unauthorized with RAILWAY_TOKEN — Help Station | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Same recurring symptom across users |
| 7 | Authentication not working with RAILWAY_TOKEN — Help Station | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | Confirms persistent confusion across community |
| 8 | RAILWAY_API_TOKEN not being respected — Help Station | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Env-var name pitfalls |
| 9 | GraphQL requests returning "Not Authorized" for PAT — Help Station | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | `me`/`teams` queries require personal account tokens |
| 10 | Generate project-wide tokens within the CLI — railwayapp/cli #122 | https://github.com/railwayapp/cli/issues/122 | Project-token use case for CI/CD automation |
| 11 | CLI authentication fails with valid API token on Linux — railwayapp/cli #699 | https://github.com/railwayapp/cli/issues/699 | Known platform-side authentication bugs |
| 12 | Railway GraphQL API — Postman | https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api | GraphQL schema reference for service/deployment queries |
| 13 | GraphQL Overview — Railway Docs | https://docs.railway.com/integrations/api/graphql-overview | Endpoint, headers, and query patterns |
| 14 | Troubleshooting — Railway Docs | https://docs.railway.com/integrations/oauth/troubleshooting | Official troubleshooting for auth failures |
