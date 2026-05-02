# Web Research: fix #850

**Researched**: 2026-05-02T00:00:00Z
**Workflow ID**: ada4a84b65f08b01b649caa2de5524dc
**Issue**: #850 — Prod deploy failed on main (38th `RAILWAY_TOKEN` expiration; 4 prior pickups on this issue alone)

---

## Summary

Issue #850 is the 38th recurrence of the `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure in `.github/workflows/staging-pipeline.yml`. Research shows two likely durable-fix paths: (1) ensure the secret holds a **project-scoped token** (created in Project → Settings → Tokens), because Railway's `RAILWAY_TOKEN` env var rejects account/workspace tokens with the exact "invalid or expired" message even immediately after creation; and (2) Railway does not document OIDC federation, so the long-lived secret cannot be eliminated — but project tokens, when correctly scoped, do not appear to have a documented automatic expiration. The 38-failure cadence strongly suggests something other than natural TTL is at play (wrong token type, account-level revocation, or token leakage triggering automatic invalidation).

**Per CLAUDE.md, this agent cannot rotate the token.** The artifact below informs the human operator's next rotation and proposes structural fixes to break the recurrence cycle.

---

## Findings

### 1. Railway token types and which one `RAILWAY_TOKEN` accepts

**Source**: [Railway Public API Documentation](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Root-cause hypothesis for the recurrence pattern

**Key Information**:

- Railway exposes four token types: **Account Token** (all resources/workspaces), **Workspace Token** (single workspace, recommended for "Team CI/CD, shared automation"), **Project Token** (single environment in a project, recommended for "Deployments, service-specific automation"), and **OAuth**.
- Project tokens use a different HTTP header — `Project-Access-Token: <TOKEN>` — instead of `Authorization: Bearer <TOKEN>`.
- Account/workspace tokens are created from the **account settings** tokens page; project tokens are created from the **project settings** tokens page.
- The public docs do **not** document expiration/TTL for account, workspace, or project tokens. (TTL is only documented for OAuth: access tokens 1 hour, refresh tokens 1 year.)

---

### 2. `RAILWAY_TOKEN` only accepts project tokens — account tokens always show "invalid or expired"

**Source**: [Railway Help Station — "RAILWAY_TOKEN invalid or expired"](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Community Q&A with confirmed working resolution
**Relevant to**: Most likely root cause — wrong token type, not actual expiration

**Key Information** (direct quote):

> "RAILWAY_TOKEN now only accepts *project token*, if u put the normal account token (the one u make in account settings) it literally says 'invalid or expired' even if u just made it 2 seconds ago."

**Recommended fix from the same thread**:

> "go to your PROJECT (not account page) → settings → tokens → generate new project token there copy that shit put it as RAILWAY_TOKEN"

Additional advice: remove or rename any `RAILWAY_API_TOKEN` env var if present, as it can interfere.

> If both environment variables are set, `RAILWAY_TOKEN` takes precedence.
> — [Railway Docs — Using the CLI](https://docs.railway.com/guides/cli)

---

### 3. The repository's deploy workflow validates the token via the GraphQL API directly

**Source**: Local file `.github/workflows/staging-pipeline.yml` (per failed-run log of run 25227458546)
**Relevant to**: The validation method may itself reject project tokens

**Key Information**:

The "Validate Railway secrets" step in the failing run does:

```bash
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: ***" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}'
```

This uses `Authorization: Bearer <token>` and queries `{me{id}}`. Per the API docs (Finding #1), **project tokens use the `Project-Access-Token` header, not `Authorization: Bearer`**, and `me` is an account-scoped query that a project token may not be allowed to resolve. So even a freshly minted project token could fail this validation.

This means the existing validation step may force the use of an account/workspace token — but Railway's CLI-side `RAILWAY_TOKEN` only accepts project tokens (Finding #2). The validation step and the deploy step may require **different** token types.

---

### 4. Railway's official recommendation for GitHub Actions

**Source**: [Railway Blog — Using GitHub Actions with Railway](https://blog.railway.com/p/github-actions)
**Authority**: Railway official blog
**Relevant to**: The supported, intended deploy pattern

**Key Information**:

- Railway recommends **project tokens** for GitHub Actions deployment.
- Project tokens are created in **project dashboard → Settings → Tokens** ("Project tokens allow the CLI to access all the environment variables associated with a specific project and environment").
- Example workflow uses the Railway CLI Docker image, stores `RAILWAY_TOKEN` as a repo secret, and runs `railway up --service=${{ env.SVC_ID }}`.
- The token "must be kept secret"; the service ID can be public.

> "If you are using a team project, you need to ensure that the token specified is scoped to your account, not a workspace."
> — Railway moderator, [Token for GitHub Action thread](https://station.railway.com/questions/token-for-git-hub-action-53342720)

---

### 5. Other known failure modes

**Source**: [Railway Help Station — CLI throwing Unauthorized with RAILWAY_TOKEN](https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1)
**Relevant to**: Alternative root causes besides expiration

**Key Information**:

- Local config corruption (`~/.railway/config.json`) can produce identical-looking unauthorized errors. Not relevant for GitHub-Actions-hosted runners (no persistent home).
- Different commands require different scopes: `railway whoami` and `railway link` need an account-scoped token; `railway up` works with a project token.
- A historical CLI bug (now fixed) caused `RAILWAY_API_TOKEN` to not be recognized properly.

---

### 6. Modern best practice: OIDC federation (not currently supported by Railway)

**Source**: [GitHub OpenID Connect Documentation](https://docs.github.com/en/actions/concepts/security/openid-connect), [Best Practices for Managing Secrets in GitHub Actions](https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions)
**Authority**: GitHub official docs + recognized industry guide
**Relevant to**: Strategic option for eliminating the rotation toil entirely

**Key Information**:

- The 2026 best practice is **OIDC federation**: no long-lived secrets, every workflow run gets a short-lived, tightly-scoped credential, automatically rotated per run.
- Supported natively by AWS, Azure, GCP, HashiCorp Vault.
- **Railway does not document OIDC support** for the CLI as of this research. Confirmed via [search](https://docs.railway.com/cli/deploying) — Railway's published path remains long-lived project tokens.
- Without OIDC, the fallback best practices are: 30–90 day rotation cadence with calendar reminders, environment-based access controls, and external secret managers (HashiCorp Vault, Infisical) for centralized rotation.

---

### 7. Why "no expiration" guidance in the existing runbook may be unreliable

**Source**: Cross-reference of [Railway Public API docs](https://docs.railway.com/integrations/api) and [Login & Tokens docs](https://docs.railway.com/integrations/oauth/login-and-tokens) and the existing `docs/RAILWAY_TOKEN_ROTATION_742.md`
**Relevant to**: Why prior rotations have not stuck

**Key Information**:

- The existing runbook (`RAILWAY_TOKEN_ROTATION_742.md`) tells operators: "Expiration: No expiration (critical — do not accept default TTL)".
- Railway's public docs (as fetched) **do not show a TTL/expiration selector** for account, workspace, or project tokens — only OAuth tokens have documented TTLs.
- That implies one of three possibilities: (a) the dashboard has a TTL selector that isn't documented; (b) the runbook's premise is incorrect and tokens aren't expiring on a TTL; (c) Railway invalidates tokens for other reasons (suspected leakage, rate limit, account state).
- The 38-recurrence pattern is inconsistent with a stable TTL. If the TTL were 7 or 30 days the cadence would be regular; the actual cadence (multiple pickups within a few days for the same issue) suggests the token is being invalidated, not naturally expiring.

---

## Code Examples

### Recommended deploy workflow shape per Railway's blog

```yaml
# From Railway Blog — Using GitHub Actions
# https://blog.railway.com/p/github-actions
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    container: ghcr.io/railwayapp/cli:latest
    env:
      RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
      SVC_ID: <service-id>
    steps:
      - uses: actions/checkout@v4
      - run: railway up --service=${SVC_ID}
```

Note: this uses the CLI directly (which knows to use the `Project-Access-Token` header) rather than calling the GraphQL `me{id}` query against the project token, which would not work.

---

## Gaps and Conflicts

- **Railway does not publicly document the TTL/expiration options for project, account, or workspace tokens.** The "No expiration" instruction in the existing runbook is not corroborated by the public docs and may be stale or incorrect.
- **Railway does not document OIDC federation** for CLI auth. If supported, it is undocumented; treat as unavailable until confirmed via Railway support.
- **No public information on why tokens are being invalidated** server-side beyond expiration. Possibilities (unverified): account ownership change, workspace permission revocation, suspected leakage detection, billing state. The blog post on Railway's [January 2026 incident](https://blog.railway.com/p/incident-report-january-26-2026) was returned by search but doesn't appear directly applicable.
- **The repo's validation step uses `Authorization: Bearer` + `me{id}` query**, which is incompatible with project tokens. A project token will fail this pre-check even when valid for `railway up`. This is a likely contributor to the recurrence — operators may be rotating to a project token (correct for `railway up`) which then fails the validator (which needs an account/workspace token), and the rotation is judged "broken".

---

## Recommendations

For the human operator who will perform the rotation:

1. **Confirm the token type before pasting.** Per [Railway community](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20), `RAILWAY_TOKEN` must be a **project token** created at *Project → Settings → Tokens*, not an account/workspace token. Account tokens are silently rejected with the exact "invalid or expired" message we are seeing.

2. **Consider switching to a workspace token + `RAILWAY_API_TOKEN`** if the workflow needs `me{id}`-style account validation. The Railway docs say workspace tokens are the recommended type for "Team CI/CD". This would mean changing both the secret name and the workflow.

3. **Reconsider the validation step.** The current pre-check (`curl … -H "Authorization: Bearer" … me{id}`) is incompatible with project tokens. Either:
   - Replace the validation with a project-scoped query using the `Project-Access-Token: <token>` header, or
   - Skip the pre-check and let `railway up` itself fail loud, or
   - Use a workspace token and `Authorization: Bearer` consistently. (Out-of-scope for this issue per Polecat discipline — should be a separate bead/issue.)

4. **Do not trust "No expiration" as a permanent fix.** The 38-occurrence pattern indicates something else is invalidating the token. After rotation, watch the logs of the next failure: capture the exact `errors[0].message` from the GraphQL response (`Not Authorized` vs. `Token expired` vs. `Project access denied` are different signals).

5. **Long-term: file an enhancement issue** to investigate workspace tokens or external secret-manager integration. Per CLAUDE.md, send mail to mayor for any out-of-scope finding rather than fixing it within the current bead.

For this agent's scope (issue #850):

- Per CLAUDE.md, **do not create a `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming success**.
- The investigation document (already produced for prior occurrences) should reference `docs/RAILWAY_TOKEN_ROTATION_742.md` and add the new findings above as updated context.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API Docs | https://docs.railway.com/integrations/api | Token types, scopes, headers |
| 2 | Railway CLI Guide | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` precedence |
| 3 | Railway Blog — GitHub Actions | https://blog.railway.com/p/github-actions | Official deploy pattern using project tokens |
| 4 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Project-token-only acceptance for `RAILWAY_TOKEN` |
| 5 | Railway Help Station — CLI Unauthorized with RAILWAY_TOKEN | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Alternative failure modes |
| 6 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Workspace vs account token nuance |
| 7 | Railway Login & Tokens Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth TTL (1h access, 1yr refresh) |
| 8 | Railway Deploying with the CLI | https://docs.railway.com/cli/deploying | Project token usage with `railway up` |
| 9 | GitHub OpenID Connect Docs | https://docs.github.com/en/actions/concepts/security/openid-connect | OIDC alternative to long-lived tokens |
| 10 | Best Practices for Managing Secrets in GitHub Actions | https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions | 30–90 day rotation cadence, external secret managers |
| 11 | Railway Incident Report Jan 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Returned by search; no direct token-invalidation link |
