# Web Research: fix #907

**Researched**: 2026-05-02T00:00:00Z
**Workflow ID**: 82f3717c5ef377464cba9b91fd484398
**Issue**: [#907 — Main CI red: Deploy to staging](https://github.com/alexsiri7/reli/issues/907)

---

## Summary

Issue #907 is the latest in a long string of `RAILWAY_TOKEN is invalid or expired: Not Authorized` failures (61st by commit count, 21st today, most recently #903/#904). Per `CLAUDE.md`, agents cannot rotate this token — that requires human access to railway.com. Web research confirms the GitHub Actions workflow at `.github/workflows/staging-pipeline.yml` uses an `Authorization: Bearer` style token (account or workspace token, not a project token, which would use `Project-Access-Token`). The recurring nature plus Railway community evidence points to either a short-TTL token being re-issued each rotation **or** the token being created with the wrong workspace scope; Railway's official docs do not publish a TTL for non-OAuth tokens, so the existing runbook's "No expiration" advice cannot be verified from public docs.

---

## Findings

### 1. Railway has four token types with different headers and scopes

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Diagnosing whether the workflow uses the right token type

**Key Information**:

- Four token types: **account**, **workspace**, **project**, **OAuth**.
- **Account, workspace, OAuth** tokens authenticate with: `Authorization: Bearer <TOKEN>`.
- **Project** tokens authenticate with: `Project-Access-Token: <TOKEN>` (different header).
- Best-use guidance:
  - Account → personal scripts, local dev (don't share)
  - Workspace → team CI/CD, shared automation (sharable)
  - Project → deployments, service-specific automation
- Reli's failing step uses `Authorization: ***` (Bearer) → so it is an **account or workspace token**, not a project token. This is consistent with reaching the `{me{id}}` GraphQL query (which a project token cannot answer).

---

### 2. Railway's official docs do NOT publish a TTL for non-OAuth tokens

**Sources**:
- [Login & Tokens — Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
- [Public API — Railway Docs](https://docs.railway.com/integrations/api)

**Authority**: Official Railway documentation
**Relevant to**: Whether "No expiration" is actually selectable, and whether account/workspace tokens silently expire

**Key Information**:

- **OAuth access tokens** expire after **1 hour**; **refresh tokens** last **1 year** with rotation.
- The OAuth doc explicitly does NOT cover account, workspace, or project tokens — those are described in `integrations/api`, which gives no expiration timing or TTL options.
- The internal runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) claims tokens have a default short TTL ("1 day or 7 days") and that "No expiration" must be selected. **This claim is not corroborated by Railway's public documentation** as of 2026-05-02 — it may be accurate (UI-only guidance not in docs) or stale.
- **Gap**: Without an authoritative TTL document, we cannot tell whether the token is timing out, being revoked, or being created incorrectly.

---

### 3. "Not Authorized" is often a token *scope/creation* problem, not pure expiration

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway community help (resolution accepted)
**Relevant to**: Whether the recurring failure is caused by re-creating tokens at the wrong scope

**Key Information**:

- The accepted resolution: tokens **must** be created from **Account Settings → Tokens** via the user banner sidebar, with the workspace field set to **"No workspace"**.
- Tokens created from project or team settings pages are reported to fail with `Not Authorized` even when fresh.
- This matches Reli's symptom (`Not Authorized` in `{me{id}}`) and would explain why every rotation fails again after some interval if the rotator picks the wrong creation flow.

---

### 4. Project tokens cannot answer `{me{id}}` — they cannot be the fix here

**Source**: [Unable to Generate API Token with Deployment Permissions — Railway Help](https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12)
**Authority**: Railway community help
**Relevant to**: Choosing token type for `staging-pipeline.yml`

**Key Information**:

- Project tokens (UUID format) "can read project information but cannot trigger deployments".
- For mutations (deploys, env changes) the **account token** (or team/workspace token) is needed — and it must use the `Authorization: Bearer` header.
- Reli's preflight (`{me{id}}`) requires the Bearer/account-style token by design — switching to a project token would break the preflight.

---

### 5. Railway officially recommends project tokens for GitHub Actions deploys

**Sources**:
- [Using GitHub Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions)
- [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)

**Authority**: Official Railway blog + community help
**Relevant to**: Long-term architecture — could the deployment step use a project token to escape this loop?

**Key Information**:

- Railway recommends a **project token** in `RAILWAY_TOKEN` for deploys (not for `me` queries).
- "If you are using a team project, you need to ensure that the token specified is scoped to your account, not a workspace" — but for *just* a deploy step (`railway up` etc.) a project token is enough.
- **Implication for Reli**: the preflight that calls `{me{id}}` is what *requires* an account/workspace token (and therefore the rotation loop). The deploy itself could in principle run on a project token, which is harder to misconfigure and never queries `me`.

---

### 6. Endpoint domain consistency

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Sanity-check the workflow URL

**Key Information**:

- The current canonical GraphQL endpoint is `https://backboard.railway.com/graphql/v2`.
- Reli's workflow uses `https://backboard.railway.app/graphql/v2`. Community reports note `.app` vs `.com` confusion has surfaced 401-style failures historically. This is **not the root cause here** (the request reaches the API and returns a structured `Not Authorized`, so the host is responding), but worth flagging on the next rotation.

---

## Code Examples

```yaml
# Current Reli preflight (from .github/workflows/staging-pipeline.yml; failing in run 25256579563)
# Source: log excerpt fetched via `gh run view 25256579563 --log-failed`
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

The `{me{id}}` query is the constraint — only account/workspace tokens can satisfy it. From [Public API — Railway Docs](https://docs.railway.com/integrations/api):

```
Authorization: Bearer <ACCOUNT_OR_WORKSPACE_TOKEN>   # required for {me{id}}
Project-Access-Token: <PROJECT_TOKEN>                # cannot answer {me{id}}
```

---

## Gaps and Conflicts

- **Gap (authoritative TTL)**: Railway's public docs do not publish an expiration policy for account/workspace/project tokens. Only OAuth access tokens (1 h) and refresh tokens (1 y) are documented. We therefore cannot independently verify the existing runbook's claim that the UI defaults to a short TTL.
- **Gap (root cause of recurrence)**: 21+ failures in a single day suggest something more aggressive than a TTL — possibilities include (a) automatic revocation when a workspace token is rotated elsewhere, (b) a scheduled/external rotator stepping on the secret, (c) repeated creation under the wrong scope. None of these can be confirmed without Railway dashboard access.
- **Conflict (token recommendation vs current design)**: Railway's blog recommends a project token for GitHub Actions, but Reli's preflight (`{me{id}}`) explicitly cannot work with a project token. The two are reconcilable only by changing the preflight.
- **Outdated content**: A community thread referenced `backboard.railway.app` while current docs use `backboard.railway.com`. Either still resolves, but mixing them invites future surprise.

---

## Recommendations

These are research-level recommendations for the human implementer (per `CLAUDE.md`, agents must not perform the rotation):

1. **For this incident (#907)**: human rotates `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`. When creating the new token in Railway dashboard, follow the community-validated steps from the "Not Authorized" thread: navigate via the **user banner sidebar → Account Settings → Tokens**, set workspace to **"No workspace"** (or to a stable workspace if intentionally team-scoped). Avoid creating from project or team settings pages.
2. **Structural fix to escape the loop**: split the preflight from the deploy.
   - Keep the `me`-query preflight only if you need to verify the human's account token.
   - Consider switching the *deploy* step to a **project token** (`Project-Access-Token` header), which is purpose-built for deployment automation and avoids account-level reauthorization. The preflight could then be dropped or weakened to a project-scoped query, eliminating the `{me{id}}` dependency.
3. **Update `staging-pipeline.yml`** to call `https://backboard.railway.com/graphql/v2` instead of `.app`, matching current Railway docs. Cosmetic but removes a known footgun.
4. **Do not** create yet another `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming the rotation has been done — `CLAUDE.md` flags this as a Category 1 error. The action for this PR is to file/escalate, not to claim completion.
5. **Track the recurrence**: 21 occurrences in one day is a system-level anomaly, not a token-lifetime issue. Worth a separate mail-to-mayor flagging that the rotation cadence has gone from "occasional" to "hourly" — something changed.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Token types, headers, scopes |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTLs (1 h / 1 y); silence on other tokens |
| 3 | Railway Blog — GitHub Actions | https://blog.railway.com/p/github-actions | Recommended token type for CI/CD deploys |
| 4 | Railway Help — "Not Authorized" for Public API/MCP | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Resolution: create from Account Settings, "No workspace" |
| 5 | Railway Help — Unable to generate token with deploy permissions | https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12 | Project tokens can't perform mutations / `me` queries |
| 6 | Railway Help — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account vs workspace scoping for team projects |
| 7 | Railway Help — Deploy from GitHub "Not Authorized" | https://station.railway.com/questions/when-trying-to-deploy-from-github-i-jus-d6b9f03a | Symptom corroboration |
| 8 | GitHub — railwayapp/cli #699 | https://github.com/railwayapp/cli/issues/699 | Linux CLI auth failures with valid tokens (background) |
| 9 | GitHub — railwayapp/cli #105 | https://github.com/railwayapp/cli/issues/105 | RAILWAY_TOKEN scope limitations (background) |
| 10 | Internal runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Project's existing rotation procedure |
