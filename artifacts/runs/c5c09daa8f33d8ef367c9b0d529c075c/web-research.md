# Web Research: fix #801 — Prod deploy failed (RAILWAY_TOKEN expired, 20th occurrence)

**Researched**: 2026-04-30T18:00:00Z
**Workflow ID**: c5c09daa8f33d8ef367c9b0d529c075c

---

## Summary

Issue #801 is the **20th** occurrence of the same `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure. The existing runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) tells operators to create the token with **"No expiration"**, but the failure has recurred 17 times since that runbook was written — strong evidence that either (a) the "No expiration" option is not being applied, or (b) the wrong token *type* is being created. Research suggests the root cause is most likely **token-type mismatch**: the workflow's validation step calls the GraphQL `{me{id}}` query, which only succeeds with an **account-scoped or workspace-scoped token**, not a project token, and Railway's own help-station threads confirm that "RAILWAY_TOKEN" labelled as "invalid or expired" frequently means *wrong type*, not *expired*.

---

## Findings

### 1. Railway has three token types with very different semantics

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens) and [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Choosing the right token for `staging-pipeline.yml`

**Key Information**:

- **Account token** — broadest scope, covers all your resources and workspaces
- **Workspace (team) token** — scoped to a workspace; "best for Team CI/CD, shared automation" per Railway docs; can be shared with teammates
- **Project token** — scoped to a single environment within one project; created from the project's Settings → Tokens page
- All three are sent via `Authorization: Bearer <token>` against the GraphQL endpoint
- Railway explicitly recommends **workspace tokens** for team CI/CD pipelines

---

### 2. "RAILWAY_TOKEN invalid or expired" is often a wrong-type error, not an expiration

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community help station thread with user-confirmed resolution
**Relevant to**: Why the same failure keeps recurring after rotation

**Confidence**: Medium — primary claim rests on a single community quote (`bytekeim`); see § "Gaps and Conflicts" below for what the official docs do and don't confirm.

**Key Information**:

- User `bytekeim` (post quoted in the thread): *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token...it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- This is the **opposite** of what the [Token for GitHub Action thread](https://station.railway.com/questions/token-for-git-hub-action-53342720) says, where a Railway employee writes: *"use a Railway API token scoped to the user account, not a project token, for the GitHub Action."*
- The contradiction resolves once you separate **CLI-based** workflows (use project token via `RAILWAY_TOKEN`) from **direct GraphQL API** workflows (use account/workspace token, header still `Authorization: Bearer`).
- The `staging-pipeline.yml` in this repo calls the GraphQL API directly with `curl` (not the CLI), so it needs an **account or workspace token**, not a project token.

---

### 3. The `{me{id}}` validation query will only succeed with an account/workspace token

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api) and [Introduction to GraphQL | Railway Docs](https://docs.railway.com/integrations/api/graphql-overview)
**Authority**: Official Railway documentation
**Relevant to**: `.github/workflows/staging-pipeline.yml` lines 49-55 (the validation step that fails)

**Key Information**:

- Project tokens have no associated user identity — they authenticate as the project, not as a user
- `{me{id}}` returns the authenticated user, which only exists for account and workspace tokens
- If someone rotates the secret with a **project token**, the validation step will fail with `Not Authorized` even though the token is brand-new and otherwise valid
- This means the current error message ("invalid or expired") is misleading when the underlying problem is wrong-type

---

### 4. Documented Railway token-expiration semantics (and an important silent-revocation case)

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens) and [Troubleshooting | Railway Docs](https://docs.railway.com/integrations/oauth/troubleshooting)
**Authority**: Official Railway documentation
**Relevant to**: Whether tokens *can* genuinely expire after rotation

**Key Information**:

- OAuth **access tokens** expire after 1 hour (irrelevant — these are not what's stored in `RAILWAY_TOKEN`)
- OAuth **refresh tokens** have a 1-year lifetime, are rotated on use, and using a stale rotated token *immediately revokes the entire authorization*
- Account/workspace/project tokens: the public docs **do not document an expiration TTL** for these tokens. They also do not document a "No expiration" toggle (contradicting the claim in the existing rotation runbook).
- Silent-revocation footgun: requesting more than 100 refresh tokens for the same user causes the oldest to be revoked without notice
- No public docs confirm or deny whether long-lived account/workspace tokens are silently expired by Railway after some interval

---

### 5. Railway CI/CD ecosystem signal

**Source**: [Using Github Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions) and [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway blog + Railway employee response
**Relevant to**: What the established pattern looks like

**Key Information**:

- Railway's own GitHub Actions blog example uses the `ghcr.io/railwayapp/cli:latest` container with a **project token** in `RAILWAY_TOKEN` and runs `railway up --service=...`
- The reli pipeline does NOT follow this pattern — it shells out to the GraphQL API directly with `curl`
- A Railway employee in the help-station thread said RAILWAY_API_TOKEN had pickup issues historically that have since been fixed; the env-var name distinction matters for the **CLI**, not for direct curl-to-GraphQL calls (where the variable is just a shell variable)

---

### 6. Existing reli docs that are likely incorrect

**Source**: `docs/RAILWAY_TOKEN_ROTATION_742.md` (this repo)
**Authority**: Internal runbook, written at occurrence #3
**Relevant to**: Direct contradiction with public Railway docs

**Key Information**:

- Says: *"The new token must be created with 'No expiration'."*
- Says: *"When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days)."*
- Public Railway documentation does not describe either a per-token TTL selector or a "No expiration" option for account/workspace/project tokens. It is plausible this advice was never accurate, which would explain why the issue keeps recurring after rotation.

---

## Code Examples

### Token-type-correct validation query (account/workspace token)

```graphql
# From https://docs.railway.com/integrations/api
# Works with: account token, workspace token
# Header: Authorization: Bearer <token>
query { me { id } }
```

### Project-token-compatible validation query

```graphql
# From https://docs.railway.com/integrations/api/graphql-overview
# Works with: project token (no `me` resolver available)
# Header: Authorization: Bearer <project_token> (or Project-Access-Token in some flows)
query { projectToken { projectId environmentId } }
```

Switching the validation step to `{ projectToken { projectId } }` would let the workflow accept project tokens too, but is **not** recommended here because subsequent deploy/health steps in `staging-pipeline.yml` may need workspace-scoped operations.

---

## Gaps and Conflicts

- **Conflict**: One Railway help-station thread says `RAILWAY_TOKEN` only accepts project tokens; another (with a Railway employee) says use an account-scoped token. Resolved by distinguishing CLI vs direct-GraphQL paths — the reli workflow is direct-GraphQL, so account/workspace token is correct.
- **Gap**: Public docs do not confirm whether long-lived account/workspace tokens silently expire on a schedule, or whether there's a UI option to set "No expiration" at creation. The internal runbook claims this option exists; this could not be corroborated against official docs.
- **Gap**: No published guidance on whether deleting and recreating a workspace member or session invalidates issued workspace tokens (a possible silent-revocation cause if the human operator's session is rotating).
- **Gap**: No public Railway changelog entry was found announcing a token-expiration policy change that would explain the recurrence cadence in this repo.

---

## Recommendations

Based on research, the next operator (human) rotating the token should:

1. **Use a workspace token, not a project token, and not an account token tied to a single user session.** Workspace tokens are Railway's documented recommendation for "Team CI/CD, shared automation" and survive an individual user's session changes. The validation `{me{id}}` query works with workspace tokens.
2. **Verify the token type at creation time**, not just paste-and-pray. Railway's token creation UI labels each token with its scope. If "No expiration" is genuinely not an option for the chosen type, the runbook is wrong and needs updating.
3. **Update `docs/RAILWAY_TOKEN_ROTATION_742.md`** to: (a) specify *workspace token* explicitly, (b) drop the unverified "No expiration" instruction unless a screenshot of that UI option is in hand, (c) add a verification step that runs the same `curl` validation locally before pasting into GitHub secrets.
4. **Consider switching from direct-GraphQL `curl` to the official `railwayapp/cli:latest` container pattern** documented on Railway's blog. This is the path Railway tests against, reducing the chance that a behavior change on their side silently breaks reli.
5. **Do not** create another `docs/RAILWAY_TOKEN_ROTATION_*.md` file claiming the rotation is done — per CLAUDE.md, that is a Category 1 error. The existing investigation-only pattern (issues #789-#799) is correct.

What an agent **cannot** do per repo policy: rotate the token itself. This research artifact is meant to inform the human who can.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token semantics, refresh-token rotation, silent revocation |
| 2 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Three token types and their scopes; workspace token is "best for Team CI/CD" |
| 3 | Railway Docs — Introduction to GraphQL | https://docs.railway.com/integrations/api/graphql-overview | GraphQL endpoint and `me` query usage |
| 4 | Railway Docs — Troubleshooting | https://docs.railway.com/integrations/oauth/troubleshooting | 100-token silent revocation rule |
| 5 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Wrong-type errors masquerade as "expired" |
| 6 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Railway employee says use account-scoped token for GH Actions; CLI vs direct-API distinction |
| 7 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Official CLI-container pattern for GH Actions deployments |
| 8 | Railway Docs — GitHub Actions Self-Hosted Runners | https://docs.railway.com/guides/github-actions-runners | Confirms Railway uses fine-grained PATs for runner registration (different concern, but rules out OIDC) |
| 9 | Railway CLI Issue #699 — auth fails with valid token on Linux | https://github.com/railwayapp/cli/issues/699 | Known auth-edge-cases on the CLI side |
| 10 | Railway Help Station — RAILWAY_API_TOKEN not being respected | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Historical CLI env-var pickup issue (now fixed) |
