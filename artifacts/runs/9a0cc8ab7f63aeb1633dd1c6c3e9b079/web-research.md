# Web Research: fix #779

**Researched**: 2026-04-30T09:30:00Z
**Workflow ID**: 9a0cc8ab7f63aeb1633dd1c6c3e9b079
**Issue**: [#779 — Prod deploy failed on main](https://github.com/alexsiri7/reli/issues/779)

---

## Summary

Issue #779 is the **13th** occurrence of the same failure: `RAILWAY_TOKEN is invalid or expired: Not Authorized` from the `Validate Railway secrets` step in `staging-pipeline.yml`. Web research confirms (a) Railway's public documentation does NOT publish a TTL for project / account / workspace tokens, only for OAuth access tokens (1 hour) and OAuth refresh tokens (1 year), and (b) the official long-term remedy other platforms recommend — GitHub OIDC federation — is **not** offered by Railway today. The runbook the repo already references (`docs/RAILWAY_TOKEN_ROTATION_742.md`) remains the only mitigation, and the action required is human, not agent-fixable.

---

## Findings

### 1. Railway token taxonomy (official docs)

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Choosing the right token type, scoping, and what `RAILWAY_TOKEN` actually represents

**Key Information**:

Railway exposes four authentication mechanisms:

| Type | Scope | Intended use | Env var |
|------|-------|-------------|---------|
| Account Token | All resources & workspaces | Personal scripts, local dev | `RAILWAY_API_TOKEN` |
| Workspace Token | Single workspace | **Team CI/CD, shared automation** | `RAILWAY_API_TOKEN` |
| Project Token | Single environment in a project | Deployments, service-specific automation | `RAILWAY_TOKEN` |
| OAuth | User-granted permissions | Third-party apps | n/a |

- Account & workspace tokens are created at https://railway.com/account/tokens.
- Project tokens are created from a project's Settings → Tokens page.
- The CLI rule: `RAILWAY_TOKEN=xxx railway up` for project-scoped deploys; `RAILWAY_API_TOKEN` for account/workspace operations. If both are set, **`RAILWAY_TOKEN` takes precedence**.

The current repo uses `RAILWAY_TOKEN` and validates against the `{ me { id } }` GraphQL query. Per the community thread below, `me { id }` requires an account-scoped (or personal-access) token, not a project token — so the validator is technically asking the wrong thing of a project token, though Railway's API does accept many account-token GraphQL queries when a workspace-scoped token is supplied.

---

### 2. Token expiration — what Railway publishes

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: The repo's existing assumption that "tokens must be created with 'No expiration'"

**Key Information**:

- Verbatim: *"Access tokens expire after one hour."* — this is for **OAuth** access tokens, NOT for the Account/Workspace/Project tokens used by CI.
- Refresh tokens (OAuth-only): *"a fresh one-year lifetime from the time of issuance"*, with automatic rotation; only the most recent refresh token is valid.
- **The docs are silent on expiration for Account, Workspace, and Project tokens.** No public statement of TTL, no documented "No expiration" toggle.

**Implication**: The claim in `docs/RAILWAY_TOKEN_ROTATION_742.md` that *"the default TTL may be short (e.g., 1 day or 7 days). The new token must be created with 'No expiration'"* is **not verifiable from the public Railway documentation as of April 2026.** Either Railway's UI behaves differently from its docs (possible — the UI might offer an expiration picker), or this claim is folklore from a prior incident. Worth confirming on the dashboard during the next rotation.

---

### 3. "Not Authorized" / token rejection causes (community)

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway-hosted community forum; mix of users + staff
**Relevant to**: Why a previously-working token starts failing with "Not Authorized"

**Key Information**:

- A common cause is **wrong workspace scoping** at creation time. Tokens that were created with a default workspace pre-selected can be rejected for cross-workspace queries; the working configuration is to leave the workspace field set to **"No workspace"**.
- A second cause: querying `me { id }` with a workspace-scoped token. Per a thread cited by Railway staff, `query { me { id email } }` *"requires a personal access token"*; workspace tokens are limited to queries about that workspace.
- "Not Authorized" is also Railway's response when a token has been **revoked** server-side (manually, via dashboard regeneration, or by Railway's anti-abuse systems). The thread does not document an automatic-expiry case for non-OAuth tokens.

---

### 4. Official guidance for GitHub Actions

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720) and [Using Github Actions with Railway (Railway blog)](https://blog.railway.com/p/github-actions)
**Authority**: Railway staff (Brody) + Railway-authored blog
**Relevant to**: Whether the repo's current token choice is the recommended one

**Key Information**:

- **Railway blog (project token)**: *"Project tokens allow the CLI to access all the environment variables associated with a specific project and environment."* Recommended setup: create project token → store as GitHub secret `RAILWAY_TOKEN` → expose in workflow env.
- **Railway staff (account/workspace token)**: *"You need to use an account scoped token, please see our docs on creating a PR environment from within a GitHub action."* — required when the action operates across projects/environments (e.g., creating ephemeral PR environments).
- **Conflict**: Railway's own guidance is split: project token for single-service deploy, account/workspace token for multi-environment automation. For a simple staging deploy, project token is sufficient and is what this repo uses.

---

### 5. The structural fix the rest of the industry uses: OIDC

**Source**: [Best Practices for Managing Secrets in GitHub Actions — Blacksmith](https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions), [OpenID Connect — GitHub Docs](https://docs.github.com/en/actions/concepts/security/openid-connect)
**Authority**: GitHub's official docs + reputable DevOps blog
**Relevant to**: Whether token-rotation pain can be eliminated entirely

**Key Information**:

- Industry recommendation: *"rotate GitHub Actions secrets regularly (30-90 days) and use OIDC over long-lived tokens."*
- OIDC trust: GitHub mints a short-lived JWT per workflow run; the cloud provider validates the JWT and issues a credential valid only for that job. *"This eliminates the need for secret rotation since credentials automatically rotate with every run."*
- AWS, Azure, GCP, OCI all support GitHub OIDC federation today.
- **Railway**: there is **no documented OIDC federation support** for GitHub Actions in Railway's docs as of April 2026 (searches against `docs.railway.com`, the Railway blog, and Help Station yielded nothing). This means the structural fix is unavailable — Railway requires a long-lived secret.

---

### 6. Token defense-in-depth options that ARE available

**Source**: [Login with Railway — OAuth | Railway Docs](https://docs.railway.com/integrations/oauth)
**Authority**: Official Railway documentation
**Relevant to**: Possible structural mitigations short of OIDC

**Key Information**:

- The OAuth flow with `offline_access` scope yields a refresh-token pair that auto-rotates on each refresh, so a workflow could in principle exchange a stored refresh token for a fresh access token at the start of each job. This still requires a long-lived secret (the refresh token), but the access token used in API calls would always be fresh.
- This is **non-trivial to set up** for CI use (OAuth was designed for user-facing apps, not headless workflows) and the docs don't show a CI example.
- Conclusion: not a clear win over the current PAT approach for this repo's scale.

---

## Code Examples

The current validator (from `.github/workflows/staging-pipeline.yml`, observed in failing run logs):

```bash
# From the failing run https://github.com/alexsiri7/reli/actions/runs/25156988688
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  exit 1
fi
```

**Note from research**: `me { id }` is documented as requiring a **personal access token** (per the community thread cited above). If the repo holds a project token, this validator is partially testing the wrong thing — the token might be valid for `railway up` even when `me { id }` returns Not Authorized. However, the current "Not Authorized" responses are happening in a context where Railway support consistently treats them as token-revoked, so in practice this is still a real failure, not a false positive.

---

## Gaps and Conflicts

- **Gap**: No public Railway documentation states a default TTL or expiration policy for Account / Workspace / Project tokens. The repo's runbook claims a "1 day or 7 days" default — this could not be confirmed against any official source.
- **Gap**: Railway does not advertise OIDC federation with GitHub Actions; no migration path away from long-lived secrets is currently published.
- **Conflict**: Railway's official blog recommends a **project token** for GitHub Actions; Railway staff in community threads recommend an **account/workspace-scoped token** for any multi-environment workflow. Both can be correct depending on workflow scope.
- **Gap**: Why this repo experiences token failures every few hours/days (13 occurrences in ~3 days, per `gh issue list`) is not explained by published Railway behavior. Possible explanations: token actually has a short expiry chosen at creation time; a separate process is regenerating tokens server-side; Railway is silently invalidating tokens that look automation-like. Only the human rotator can confirm by inspecting the Railway dashboard's token list.

---

## Recommendations

1. **Honor `CLAUDE.md`'s Railway Token Rotation policy.** Agents cannot rotate the token. Do **not** create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file. File the issue / send mail to mayor; point the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

2. **When the human next rotates, confirm the runbook's "No expiration" claim.** Railway's public docs don't publish this option. The human should screenshot whatever expiration choices the dashboard offers and update `docs/RAILWAY_TOKEN_ROTATION_742.md` with the actual UI behavior — folklore that can't be verified is dangerous.

3. **Consider switching the validator query.** `{ me { id } }` requires a personal/account-scoped token. If the repo intentionally uses a project token, replace with a project-scoped probe (e.g., `{ project(id: "...") { id name } }` against the staging project) to avoid masking real token-state with a wrong-scope rejection.

4. **Track a structural fix as a separate issue, not in this hotfix.** The recurrence rate (13 in 3 days) suggests a systemic root cause that will keep paging archon. Options to evaluate (out of scope for #779):
   - Open a Railway support ticket with the failing tokens' creation timestamps to learn whether server-side revocation is happening.
   - Watch Railway's changelog for OIDC federation support; until then, Railway cannot offer the rotation-free model AWS/Azure/GCP do.
   - As a stopgap, a scheduled GitHub Action could probe the token daily and open an issue *before* the next deploy fails, so rotations happen out-of-band rather than blocking prod.

5. **Don't fix scope creep in this bead.** Per `CLAUDE.md`'s polecat-scope rule, anything beyond researching the failure and escalating to human stays out of this PR.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs | https://docs.railway.com/integrations/api | Authoritative token-type taxonomy |
| 2 | Railway Login & Tokens (OAuth) | https://docs.railway.com/integrations/oauth/login-and-tokens | Only published TTL info (OAuth only, 1h / 1y) |
| 3 | Railway CLI guide | https://docs.railway.com/guides/cli | RAILWAY_TOKEN vs RAILWAY_API_TOKEN semantics |
| 4 | Railway blog — GitHub Actions | https://blog.railway.com/p/github-actions | Official "use project token" guidance |
| 5 | Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Staff guidance recommending account-scoped tokens for multi-env CI |
| 6 | Help Station — Not Authorized for PAT | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Workspace-scoping pitfalls; `me { id }` requires PAT |
| 7 | Help Station — GraphQL Not Authorized for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Common Not-Authorized failure modes |
| 8 | GitHub Docs — OIDC | https://docs.github.com/en/actions/concepts/security/openid-connect | The structural alternative that Railway doesn't yet support |
| 9 | Blacksmith — GitHub Actions secrets best practices | https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions | Industry rotation cadence (30–90 days) and OIDC recommendation |
| 10 | Failing CI run | https://github.com/alexsiri7/reli/actions/runs/25156988688 | Source of the exact failure logs |
| 11 | Repo runbook | docs/RAILWAY_TOKEN_ROTATION_742.md | Existing rotation procedure to direct the human to |
