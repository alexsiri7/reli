# Web Research: fix #790 (RAILWAY_TOKEN expired — 17th occurrence)

**Researched**: 2026-04-30T00:00:00Z
**Workflow ID**: 9d7f0fcf7ce6ae42e454432d6d9a4bfb

---

## Summary

Issue #790 is the 17th recurrence of the staging-pipeline failing at the "Validate Railway secrets" step with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Web research on Railway's official docs and community forum confirms that (a) Railway exposes four token types with different scopes and headers, (b) `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` mean different things to the Railway CLI, and (c) the `{me{id}}` validation query used by `staging-pipeline.yml` only works for **account/workspace** tokens with `Authorization: Bearer`, *not* for project tokens (which would need the `Project-Access-Token` header). The published docs do not mention any TTL field, "no expiration" toggle, or auto-rotation, so the recurring expirations are not explained by the documentation alone — they most likely indicate either token-type mismatch or manual revocation/rotation.

---

## Findings

### 1. Railway has four token types with distinct scopes and headers

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Picking the right token type for CI

**Key Information**:

- **Account tokens** — broadest scope, "all your resources and workspaces"; intended for "personal scripts, local development."
- **Workspace tokens** — scoped to a single workspace; intended for "team CI/CD, shared automation"; safe to share with teammates.
- **Project tokens** — scoped to a specific environment within a project; for "deployments, service-specific automation."
- **OAuth access tokens** — for third-party apps via Login with Railway.

Authentication headers differ:

- Account / Workspace / OAuth tokens → `Authorization: Bearer <TOKEN>`
- Project tokens → `Project-Access-Token: <TOKEN>` (NOT `Authorization: Bearer`)

The docs do **not** mention TTL, expiration windows, or a "no expiration" creation option for any token type.

---

### 2. `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` are not interchangeable

**Source**: [Using the CLI — Railway Docs](https://docs.railway.com/guides/cli)
**Authority**: Official Railway documentation
**Relevant to**: Whether the env var name in `staging-pipeline.yml` matches the token type that's actually being pasted in

**Key Information**:

- `RAILWAY_TOKEN` is for **project-level** actions (project token).
- `RAILWAY_API_TOKEN` is for **account-level** actions (account or workspace token).
- If both are set, `RAILWAY_TOKEN` takes precedence (per community thread; see Finding #4).

Implication for reli: the GitHub secret is named `RAILWAY_TOKEN`, but the CI's validation query (`{me{id}}`) only resolves under an account/workspace token. Whether this *actually* works depends on what kind of token has been pasted into the secret. If a project token is pasted into `RAILWAY_TOKEN`, the `{me{id}}` query against `Authorization: Bearer` will fail with "Not Authorized" — exactly the error in #790.

---

### 3. The `{me{id}}` query is account-scoped — project tokens cannot resolve it

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: The validation step at `staging-pipeline.yml:49,52`

**Key Information**:

- The `me` GraphQL query "returns account-scoped data and cannot be used with workspace or project tokens."
- Reli's CI validates the token with: `curl -X POST .../graphql/v2 -H "Authorization: Bearer $RAILWAY_TOKEN" -d '{"query":"{me{id}}"}'`
- Confirmed in `staging-pipeline.yml` lines 49–52 and repeated at 71, 81, 166, 169, 188, 198.

This means the validation only succeeds for an **account token** (workspace empty) — not for a workspace token (which the official docs say is the *recommended* type for "team CI/CD"), and not for a project token at all under the Bearer header.

---

### 4. Community confirms `RAILWAY_TOKEN now only accepts project tokens` for `railway up` — but the GraphQL `me` query path is the opposite

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community Q&A (user `bytekeim`)
**Relevant to**: A subtle conflict between CLI behaviour and direct API behaviour

**Key Information**:

- For the **Railway CLI**, the env var `RAILWAY_TOKEN` is documented to accept only a *project token*; pasting an account token there returns "invalid or expired."
- For the **GraphQL API** with `Authorization: Bearer`, the opposite is true — only account/workspace tokens authenticate `me`.
- Practical guidance from the thread: if both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` are set, `RAILWAY_TOKEN` "wins and screws everything up if it's wrong."

So the secret named `RAILWAY_TOKEN` in our repo must contain a **value that resolves `{me{id}}` via Bearer auth** — i.e., an account token. The naming of the secret is misleading by Railway's CLI conventions, even though it is correct for the API call we actually make.

---

### 5. The "Not Authorized" GraphQL error has more than one cause

**Source**: [Unable to Generate API Token with Deployment Permissions — Railway Help Station](https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12), [GraphQL requests returning "Not Authorized" for PAT](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Railway community Q&A
**Relevant to**: Diagnosing whether the token is genuinely expired vs. wrong-type

**Key Information**:

- "Not Authorized" can mean: (a) token revoked/expired, (b) token type mismatch (project token sent with `Authorization: Bearer`), (c) token scope wrong (workspace token used for account-level resource), (d) GitHub-OAuth Pro accounts that can only create project tokens, not personal ones.
- A sole "Not Authorized" string from Railway's GraphQL API does **not** distinguish (a) from (b)/(c).

Implication: the recurring framing of "the token expired" may be wrong some of the time. The ones rotating the secret should also confirm the **token type** is account-scoped each time, not just rotate blindly.

---

### 6. No documented TTL, no documented "no expiration" toggle

**Source**: cross-referenced [Public API](https://docs.railway.com/integrations/api), [Using the CLI](https://docs.railway.com/guides/cli), [Login & Tokens](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation (multiple pages)
**Relevant to**: The current rotation runbook's claim that you can choose "Expiration: No expiration"

**Key Information**:

- None of the official Railway docs reviewed mention a TTL field, expiration date picker, or "No expiration" option when creating account/workspace/project tokens.
- The only documented expirations are for **OAuth access tokens** (1 hour) and **OAuth refresh tokens** (1 year) — neither of which apply to PATs/workspace tokens used in CI.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` instructs the rotator to "Expiration: No expiration (critical — do not accept default TTL)." If that field has been removed or relabeled in Railway's UI since 2026, the runbook may be stale.

---

### 7. Workspace tokens are the documented "right answer" for team CI/CD

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Long-term fix to break the recurrence cycle

**Key Information**:

- Per official docs: workspace tokens are "ideal for team CI/CD, shared automation" — they survive a single user leaving the team, can be shared, and are scoped narrower than account tokens.
- Account tokens are explicitly described as "personal scripts, local development" — i.e., a single-human credential, which is exactly what makes recurring rotation painful.
- Whether a workspace token authenticates the `{me{id}}` query over `Authorization: Bearer` is **not unambiguously settled** by the public docs reviewed for this artifact (see Finding 3 for the conflicting claim that `me` "cannot be used with workspace or project tokens"). Do not switch token type during a live expiry without a parallel test against the validation probe — tracked as a P2 follow-up.

---

## Code Examples

### Validation pattern currently used (account/workspace token)

```yaml
# From .github/workflows/staging-pipeline.yml:49–52
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

### What a project-token validation would look like (NOT compatible with `me{id}`)

```bash
# From https://docs.railway.com/integrations/api
curl -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $PROJECT_TOKEN" \
  -d '{"query":"{ project { id name } }"}'
```

---

## Gaps and Conflicts

- **Gap**: Official Railway docs do not document any TTL or "No expiration" UI for account/workspace tokens. Cannot confirm from public sources whether such a field still exists in the dashboard, was renamed, or was removed.
- **Gap**: No public source explains *why* a non-OAuth Railway token would expire on a recurring schedule. Possible causes consistent with the evidence: (a) account-token TTL silently changed by Railway, (b) the rotator is creating workspace tokens that have a workspace-level rotation policy, (c) someone with dashboard access is manually revoking the token, (d) Pro/GitHub-OAuth account quirks limiting which token types can be created.
- **Conflict**: Community user says `RAILWAY_TOKEN` only accepts project tokens (CLI behaviour); official docs and our `{me{id}}` validation only work with account/workspace tokens. Both are true — they describe different code paths (CLI vs raw GraphQL).

---

## Recommendations

1. **Do not attempt to rotate the token from this agent.** Per `CLAUDE.md`, the rotation requires human access to railway.com and creating a `RAILWAY_TOKEN_ROTATION_*.md` file claiming otherwise is a Category 1 error. File a GitHub issue / mail mayor and direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`. (This is unchanged from the established procedure for #779, #781, #783, #785, #786.)

2. **When the human rotates next time, have them confirm the token *type*, not just freshness.** The runbook should require: (a) workspace **empty** at creation (=> account-scoped) or workspace = the team workspace (=> workspace-scoped), not a project token; (b) test the new token against `{"query":"{me{id}}"}` *before* saving the secret.

3. **Consider switching from an account token to a workspace token long-term.** Official Railway docs identify workspace tokens as the canonical answer for team CI/CD. Account tokens belong to a single human and that human's session/credentials are the most likely thing to be invalidated repeatedly. The `{me{id}}` validation query continues to work without changes.

4. **Make the validation step distinguish "expired" from "wrong type."** Today the CI prints whatever the GraphQL API returns ("Not Authorized"). A small enhancement: surface `RESP` raw on failure so the next investigator can tell instantly whether it's a 401 vs a permission error vs a genuine expiry. (Out of scope for this bead — file as a separate suggestion.)

5. **Audit the runbook.** Verify with the next human rotator whether the Railway dashboard still presents a "No expiration" option. If the field is gone or has been replaced (e.g., with a maximum TTL), update `docs/RAILWAY_TOKEN_ROTATION_742.md` to match reality. The recurring expirations are circumstantial evidence that the runbook's promise ("create with No expiration → never rotates") is no longer reliable.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Authoritative spec of the four token types, headers, and `me` query scope |
| 2 | Using the CLI — Railway Docs | https://docs.railway.com/guides/cli | Documents `RAILWAY_TOKEN` (project) vs `RAILWAY_API_TOKEN` (account) split |
| 3 | Using GitHub Actions with Railway (blog) | https://blog.railway.com/p/github-actions | Official walkthrough; confirms tokens go in GitHub secrets, no TTL discussion |
| 4 | RAILWAY_TOKEN invalid or expired — Help Station | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community confirmation that token-type mismatch produces this exact error |
| 5 | Unable to Generate API Token with Deployment Permissions | https://station.railway.com/questions/unable-to-generate-api-token-with-deploy-4d2ccc12 | "Not Authorized" alternative causes (Pro/OAuth accounts cannot mint personal tokens) |
| 6 | GraphQL requests returning "Not Authorized" for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Confirms the error string is non-specific |
| 7 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth 1h/1y expiry — does NOT apply to PAT/workspace tokens |
| 8 | Token for GitHub Action — Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Community Q&A on token selection for GH Actions |
| 9 | RAILWAY_API_TOKEN not being respected — Help Station | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Confirms `RAILWAY_TOKEN` precedence behaviour in CLI |
| 10 | Local runbook | docs/RAILWAY_TOKEN_ROTATION_742.md | The existing rotation procedure — possibly stale on the "No expiration" claim |
