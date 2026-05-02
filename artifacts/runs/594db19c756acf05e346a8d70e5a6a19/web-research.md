# Web Research: fix #894

**Researched**: 2026-05-02T (UTC)
**Workflow ID**: 594db19c756acf05e346a8d70e5a6a19
**Issue**: [#894 — Prod deploy failed on main](https://github.com/alexsiri7/reli/issues/894)

---

## Summary

Issue #894 is the **56th** instance of `RAILWAY_TOKEN is invalid or expired: Not Authorized` failing the `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml`. The recurring nature suggests a structural problem, not a one-off rotation. Web research surfaces two relevant findings: (1) Railway has multiple token types (account, workspace, project, OAuth) with different scopes, and the `RAILWAY_TOKEN` env var name has a strict mapping — only **project tokens** are accepted in `RAILWAY_TOKEN`, while account/workspace tokens belong in `RAILWAY_API_TOKEN`; (2) the long-term fix for "rotate every N days" pain in CI is OIDC-based short-lived credentials, but Railway does not currently offer GitHub-OIDC federation, so the practical mitigation is choosing a non-expiring token type and adding pre-flight rotation alerts.

Per repo policy (`CLAUDE.md` → Railway Token Rotation), agents cannot rotate the token. This research is meant to inform the human who performs rotation about whether the token type itself can be changed to reduce recurrence.

---

## Findings

### 1. Railway has four distinct token types — choosing the right one matters

**Source**: [Railway Public API — Tokens](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Root cause — wrong token type may explain recurring expirations

**Key Information**:

- Four token types exist: **Account token**, **Workspace token**, **Project token**, **OAuth access token**.
- **Account token**: access to all your resources and workspaces (broadest scope, tied to a single human user).
- **Workspace token**: access to a single workspace; doc says "Best For: Team CI/CD, shared automation" and explicitly states "you can share this token with your teammates."
- **Project token**: scoped to a specific environment within a project; only authenticates requests to that environment.
- The currently configured secret in `staging-pipeline.yml:34,62,151,179` is named `RAILWAY_TOKEN` but the workflow queries `{me{id}}` against `backboard.railway.app/graphql/v2` — `me` is an account-level field, which means the token in use is **not** a pure project token; it must have account scope.

---

### 2. `RAILWAY_TOKEN` env var name only accepts project tokens with the CLI

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community Q&A (official help station)
**Relevant to**: Possible misconfiguration — env var/token-type mismatch

**Key Information**:

- Direct community quote: *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token...it literally says 'invalid or expired'"*.
- Account tokens go in `RAILWAY_API_TOKEN`, project tokens go in `RAILWAY_TOKEN` (per [Using the CLI](https://docs.railway.com/guides/cli)).
- Having both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` set simultaneously can cause conflicts.
- Reli's workflow does **not** use the Railway CLI — it makes raw `curl` calls to the GraphQL API with `Authorization: Bearer $RAILWAY_TOKEN`. For raw API calls, the env var name is just shell convention; what matters is the token's scope. So this constraint does **not** apply to Reli's current setup, but it would matter if the workflow ever migrated to the CLI.

---

### 3. Token expiration policies — what the docs do and do not say

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Whether *any* token type avoids expiration

**Key Information**:

- OAuth **access tokens** explicitly expire after **1 hour**; OAuth **refresh tokens** have a **1-year lifetime from issuance** and are rotated.
- For **account, workspace, and project tokens**, the public docs **do not state an explicit expiration policy**. Community reports suggest these are intended to be long-lived but in practice users do see "expired" errors that may be tied to other invalidation events (token revocation on user permission changes, workspace membership changes, security incidents, or undocumented TTLs).
- January 2026 Railway incident report ([blog.railway.com/p/incident-report-january-26-2026](https://blog.railway.com/p/incident-report-january-26-2026)) describes auth failures from rate-limit pressure (GitHub OAuth 2k/hr cap exceeded during sign-up surge) — *this is a different failure mode* but worth mentioning since transient `Not Authorized` could also stem from upstream incidents rather than true expiration.

**Gap**: There is no authoritative source stating "workspace tokens never expire." The closest thing is the workspace-token "Best For Team CI/CD" framing, which implies long-lived intent.

---

### 4. The systemic answer for CI rotation pain is OIDC — but Railway doesn't support it

**Source**: [GitHub OIDC docs](https://docs.github.com/en/actions/concepts/security/openid-connect), [StepSecurity best practices](https://www.stepsecurity.io/blog/github-actions-security-best-practices)
**Authority**: Official GitHub docs + recognized security vendor
**Relevant to**: Long-term elimination of token-rotation toil

**Key Information**:

- OIDC eliminates long-lived secrets entirely: the cloud provider issues a short-lived token per workflow run, automatically scoped and rotated.
- GitHub Actions natively supports OIDC for **AWS, Azure, GCP, HashiCorp Vault**, and other providers offering official login actions.
- Railway is **not** in the list of providers with documented GitHub-OIDC federation as of this research. So OIDC is not currently a drop-in option for Reli's deploy flow.
- Alternative: external secret manager (HashiCorp Vault, Infisical, Doppler) with auto-rotation hooks — overkill for this single-token problem.

---

### 5. Workspace token is the doc-recommended type for shared/team CI

**Source**: [Railway Public API — Tokens](https://docs.railway.com/integrations/api), [Token for GitHub Action — Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official docs + Railway community
**Relevant to**: Concrete change that may reduce recurrence

**Key Information**:

- Doc explicitly labels workspace tokens "Best For: Team CI/CD, shared automation."
- Help-station thread: *"use a Railway API token scoped to the user account, not a project token, for the GitHub Action, set in the `RAILWAY_API_TOKEN` environment variable... when creating the token in the accounts page, you must leave the workspace blank to create an account-scoped token; setting it to your default workspace creates a workspace-scoped token instead."*
- Trade-off: a workspace token is shared, so when the workspace owner changes membership/permissions or rotates credentials, deploys break. An account token tied to a specific human is even more fragile (breaks if that human leaves or rotates their password).

---

## Code Examples

Reli's current validation pattern (from `staging-pipeline.yml:49-58`):

```bash
# From .github/workflows/staging-pipeline.yml
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
fi
```

The `{me{id}}` probe confirms the secret is being used as an **account-scoped** token (project tokens have no `me` field). This means the token type is account or workspace — not project.

Reference workflow pattern using project token + Railway CLI (from [bervProject/railway-deploy](https://github.com/bervProject/railway-deploy)):

```yaml
# From https://github.com/bervProject/railway-deploy
- run: npm i -g @railway/cli
- run: railway up --service=backend
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}  # project token here
```

---

## Gaps and Conflicts

- **Gap**: Railway public docs do not state explicit expiration TTLs for account, workspace, or project tokens. Empirically, this repo has rotated 56 times — strong signal that *something* is invalidating the token periodically (TTL, security policy, or revocation on workspace events). Without official confirmation, we cannot assert any specific token type "never expires."
- **Gap**: No public Railway docs on GitHub-OIDC federation — appears unsupported as of May 2026.
- **Conflict**: Some sources say `RAILWAY_TOKEN` requires a project token; the Reli workflow uses an account-scoped token in `RAILWAY_TOKEN` and it has historically *worked* (just expired). Reconciliation: the env-var name only matters when using the **Railway CLI**, which enforces the mapping. Reli uses raw `curl` against the GraphQL API where the bearer token is just a bearer token — the var-name constraint does not apply.
- **Possible non-rotation cause**: Some recurring "expired" reports correlate with Railway-side rate-limiting or auth incidents, not actual token expiry. With 56 occurrences, rate-limiting is unlikely to be the dominant cause, but it could account for a subset.

---

## Recommendations

Based on research:

1. **Verify which token type is in `RAILWAY_TOKEN` today.** The probe `{me{id}}` works → token is account or workspace scope. If it's an **account token tied to a single user**, switching to a **workspace token** scoped to the team workspace is the doc-recommended improvement and removes the dependency on one human's account state.
2. **Don't migrate the env-var name unless adopting the Railway CLI.** The workflow uses raw GraphQL; renaming `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` would only matter if/when CLI usage is added.
3. **Avoid claiming OIDC will fix this.** Railway has no documented GitHub-OIDC federation. Suggesting OIDC migration would be misleading.
4. **For this specific issue (#894):** follow `CLAUDE.md` Railway Token Rotation policy — file the issue (already done, that's #894), point the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`, do **not** create another `RAILWAY_TOKEN_ROTATION_*.md` "claim of completion" file. Implementation work that *would* reduce recurrence (switch token type, add pre-expiry monitoring) is out of scope for the rotation itself and should be tracked separately if the human wants it.
5. **Pre-expiry monitoring** is feasible and in-scope for an agent: a scheduled workflow that runs `{me{id}}` daily and opens an issue when it starts failing, rather than waiting for a deploy to fail. (Repo already has `railway-token-health.yml` — suggesting this monitoring may exist; worth verifying.)

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API (Tokens) | https://docs.railway.com/integrations/api | Token types and intended use |
| 2 | Railway CLI Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTLs (1h access / 1y refresh) |
| 3 | Using the CLI | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env-var mapping |
| 4 | RAILWAY_TOKEN invalid or expired (Help Station) | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Token-type/env-var mismatch as common root cause |
| 5 | Token for GitHub Action (Help Station) | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account-scoped token guidance for shared CI |
| 6 | Railway incident report Jan 28-29 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Upstream auth failures unrelated to token expiry |
| 7 | GitHub Actions OIDC docs | https://docs.github.com/en/actions/concepts/security/openid-connect | Long-term zero-rotation pattern (not yet supported by Railway) |
| 8 | StepSecurity — GitHub Actions security best practices | https://www.stepsecurity.io/blog/github-actions-security-best-practices | Industry best-practice framing for secret rotation |
| 9 | bervProject/railway-deploy | https://github.com/bervProject/railway-deploy | Reference workflow using Railway CLI + project token |
| 10 | Using GitHub Actions with Railway (blog) | https://blog.railway.com/p/github-actions | Official Railway-published GitHub Actions guidance |
