# Web Research: fix #793 — 18th RAILWAY_TOKEN expiration

**Researched**: 2026-04-30T13:30:00Z
**Workflow ID**: 5678b1a376aa1270bc085e05ffb69d15
**Issue**: alexsiri7/reli#793 — "Main CI red: Deploy to staging" (`RAILWAY_TOKEN is invalid or expired: Not Authorized`)

---

## Summary

Issue #793 is the 18th occurrence of the same RAILWAY_TOKEN expiration pattern (issues #742, #751, #755, #762, #766, #769, #771, #773, #774, #777, #779, #781, #783, #785, #786, #789, #790 preceded it — the existing runbook at `docs/RAILWAY_TOKEN_ROTATION_742.md` advises rotating to a token with "No expiration"). Web research surfaces three architectural facts that the runbook does **not** capture: (1) Railway's three token types — Account, Workspace, Project — have **distinct authentication headers and scopes**, and `RAILWAY_TOKEN` in CI contexts is widely reported to "only accept project tokens" reliably; (2) the `staging-pipeline.yml` validation step uses `Authorization: Bearer` + `{me{id}}`, which is an **Account/Workspace-token shape** — incompatible with project tokens (which use `Project-Access-Token` header and have no `me` access); (3) Railway does **not** currently offer GitHub OIDC trust, so eliminating the long-lived secret entirely is not yet an option.

The most actionable architectural insight: switching to a project token would change both the secret and the validation/deploy code paths — it is a workflow refactor, not a secret swap.

---

## Findings

### 1. Railway has three token types with different headers and scopes

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Choosing a long-lived token type that fits the staging-pipeline.yml usage

**Key Information**:

| Token Type | Header | Scope |
|---|---|---|
| Account | `Authorization: Bearer <TOKEN>` | All resources & workspaces the user can access |
| Workspace | `Authorization: Bearer <TOKEN>` | Single workspace, all its resources |
| Project | `Project-Access-Token: <TOKEN>` | Single environment within a project |

- Project tokens are **not** Bearer tokens and **cannot** answer the `{me{id}}` query — that query is account/user-scoped.
- The current `.github/workflows/staging-pipeline.yml` validation step (lines 49–52) uses `Authorization: Bearer` + `{me{id}}` — which means the secret in `RAILWAY_TOKEN` today is an **Account or Workspace token**, not a Project token.

---

### 2. Community consensus: `RAILWAY_TOKEN` in CI works most reliably as a Project token

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community help forum (user reports + recurring resolution pattern)
**Relevant to**: Why the same token keeps failing with "Not Authorized" — even after rotation

**Key Information**:

- Direct quote from a user: *"RAILWAY_TOKEN now only accepts **project token**, if u put the normal account token (created in account settings), it literally says 'invalid or expired' even if just created."*
- Conflicting CLI conventions: `RAILWAY_API_TOKEN` is for account/workspace tokens; `RAILWAY_TOKEN` is treated as a project token by the CLI.
- Workspace tokens fail to perform user-scoped actions like `me{id}` and "linking to projects outside the token's workspace."
- Multiple community reports describe persistent rotation pain when an account/workspace token is used for project-scoped automation — **rotation does not fix the root mismatch**.

**Caveat**: The Reli workflow uses raw GraphQL (not the CLI), so the `RAILWAY_TOKEN` env var name is just a convention here. The current Bearer + `{me{id}}` shape *does* require an account/workspace token. The community advice ("use a project token") would require changing the workflow code, not just the secret.

---

### 3. Railway docs do not advertise a "No expiration" account/workspace token

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens) and [Public API](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Whether the runbook's "No expiration" advice (`docs/RAILWAY_TOKEN_ROTATION_742.md`) is still attainable in the current dashboard

**Key Information**:

- Public docs describe OAuth access tokens (1 hour) and refresh tokens (1 year) but **do not document an expiration policy or a "No expiration" option** for Account, Workspace, or Project tokens created via the dashboard.
- WebFetch of the official tokens page returned: *"This critical information is absent from the source material."*
- The runbook's claim that "No expiration" is the fix is unverified in current Railway docs — possible explanations: (a) the dashboard option exists but is undocumented, (b) the option was removed, (c) Railway silently caps long-lived tokens.
- Recurring pattern across 18 issues strongly suggests the current token is being created with a finite TTL, whether by user choice or by platform default.

---

### 4. Railway does not yet support GitHub OIDC trust

**Source**: [OpenID Connect — GitHub Docs](https://docs.github.com/en/actions/concepts/security/openid-connect), [Configuring OIDC in cloud providers](https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers)
**Authority**: GitHub official documentation; absence-of-evidence corroborated by the Railway docs and blog
**Relevant to**: Whether the long-lived-secret problem can be eliminated entirely

**Key Information**:

- GitHub OIDC issues short-lived, per-job tokens that the cloud provider validates — "no long-lived secrets, every token is scoped, auditable, and automatically rotated per workflow run."
- Officially supported targets: AWS, Azure, GCP, HashiCorp Vault. **Railway is not in this list.**
- For Railway to support OIDC it would need to host an OIDC token-exchange endpoint that trusts `token.actions.githubusercontent.com`. No such endpoint is documented today.
- **Implication**: The 18-issue recurrence cannot be cured by switching to OIDC at this time. The architectural options are (a) better long-lived token hygiene, (b) automated rotation tooling, (c) lobbying Railway for OIDC.

---

### 5. Railway CLI may ignore `RAILWAY_TOKEN` in some flag combinations

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720), [Using Github Actions with Railway](https://blog.railway.com/p/github-actions)
**Authority**: Railway community + official Railway blog
**Relevant to**: Future-proofing if the workflow ever moves from raw GraphQL to the Railway CLI

**Key Information**:

- Railway's own blog recommends **project tokens** for GitHub Actions deploys.
- Community guidance: when using the CLI, omit `--project` and use `--service <name>` only — passing `--project` or a project ID can cause the CLI to fall back to interactive login despite `RAILWAY_TOKEN` being set.
- Setting both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` can cause precedence conflicts; Railway recommends clearing one.

---

## Code Examples

### Current Reli validation shape (Account/Workspace-token style)

```yaml
# From .github/workflows/staging-pipeline.yml:49-52 (current, requires account/workspace token)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

### Project-token equivalent (would require code change, not just secret swap)

```bash
# From Railway docs (https://docs.railway.com/integrations/api) — project token uses a different header
# and cannot run me{id} (it's not user-scoped). A project-scoped probe query would replace it, e.g.:
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

(Exact validation query for project tokens not confirmed in docs; this is illustrative.)

---

## Gaps and Conflicts

- **Gap**: Railway docs do not publicly document expiration options or a "No expiration" toggle for dashboard-created tokens. The existing runbook's "Expiration: No expiration (critical)" instruction is not corroborated by any official page I could reach.
- **Gap**: No definitive statement on whether Account, Workspace, or Project tokens have a different default TTL from one another in the current dashboard.
- **Gap**: No data on whether Railway has rolled out a forced rotation policy that would explain the steady drumbeat of expirations. (One alternative explanation: each rotation has unintentionally re-created a *short-lived* token.)
- **Conflict**: Community says "RAILWAY_TOKEN only accepts project tokens" — but the current Reli workflow demonstrably uses an account/workspace token successfully (it passes for some duration before each expiration). The community claim is CLI-context-specific; raw GraphQL accepts whichever token type the header matches.
- **Conflict**: Railway's official blog recommends project tokens for GitHub Actions, but the staging-pipeline.yml architecture (Bearer + `me{id}`) was written for an account/workspace token. One of the two is wrong for this codebase.

---

## Recommendations

These are research-derived recommendations for the human/mayor — **agents cannot rotate the Railway token** (per `CLAUDE.md`). Phrased as architectural options the maintainer can choose between, not implementation steps.

1. **Verify the dashboard "No expiration" option exists today.** When the human next rotates, they should screenshot the expiration dropdown. If "No expiration" is genuinely available and being missed, the runbook fix is sound. If it's no longer offered, the runbook needs updating and option (2) becomes mandatory.

2. **If "No expiration" is unavailable, automate rotation.** Build a small scheduled job (or use `gh secret set` from a privileged runner) to refresh `RAILWAY_TOKEN` before each TTL boundary. The 18-issue history justifies the engineering cost.

3. **Do not refactor to a project token without changing the workflow code.** The current Bearer + `{me{id}}` validator is account/workspace-shaped. Swapping the secret type alone will keep failing with "Not Authorized." A real switch means: change the header (`Authorization: Bearer` → `Project-Access-Token`), replace the `{me{id}}` probe with a project-scoped query, and re-test all three Railway API calls in the workflow (validate, set image, trigger deploy). This is a workflow-level change, not a one-line secret update.

4. **Track Railway OIDC support as a long-term fix.** OIDC would eliminate this issue class entirely but is not currently offered by Railway. Worth a feature request to Railway; not actionable inside Reli today.

5. **Avoid creating yet another `.github/RAILWAY_TOKEN_ROTATION_*.md` file.** `CLAUDE.md` explicitly forbids this — agents falsely claiming rotation is done is a Category 1 error. The right output for issue #793 is filing/escalating to the human and pointing at `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Authoritative spec of the three token types and their headers |
| 2 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTLs (1h access / 1y refresh); does not cover dashboard token expiration |
| 3 | Using the CLI — Railway Docs | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env var conventions |
| 4 | RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community: "RAILWAY_TOKEN only accepts project tokens" |
| 5 | Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | CLI flag pitfalls (`--project` ignoring `RAILWAY_TOKEN`) |
| 6 | RAILWAY_API_TOKEN not Working | https://station.railway.com/questions/railway-api-token-not-working-2083f58a | Token type confusion in CI |
| 7 | Using Github Actions with Railway | https://blog.railway.com/p/github-actions | Official blog: project tokens recommended for GitHub Actions |
| 8 | GitHub Actions PR Environment | https://docs.railway.com/tutorials/github-actions-pr-environment | Sample workflow shape using project tokens |
| 9 | OpenID Connect — GitHub Docs | https://docs.github.com/en/actions/concepts/security/openid-connect | OIDC eliminates long-lived secrets; per-job rotation |
| 10 | Configuring OIDC in cloud providers | https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers | List of OIDC-supported providers (Railway not on it) |
| 11 | Secure deployments with OIDC GA — GitHub Blog | https://github.blog/security/supply-chain-security/secure-deployments-openid-connect-github-actions-generally-available/ | Background on OIDC GA, partner support |
| 12 | The end of GitHub PATs — Chainguard | https://www.chainguard.dev/unchained/the-end-of-github-pats-you-cant-leak-what-you-dont-have | Industry direction away from long-lived tokens |
