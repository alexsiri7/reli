# Web Research: fix #766 — Main CI red, RAILWAY_TOKEN expired (7th recurrence)

**Researched**: 2026-04-30T07:30:00Z
**Workflow ID**: a122778df09411f8f384b7dd9567d920
**Issue**: [#766 — Main CI red: Deploy to staging](https://github.com/alexsiri7/reli/issues/766)
**Failing run**: [25148434478](https://github.com/alexsiri7/reli/actions/runs/25148434478)
**Failing SHA**: `7433450`

---

## Summary

Issue #766 is the **7th identical recurrence** of `RAILWAY_TOKEN is invalid or expired: Not Authorized` (prior: #733, #739, #742, #755, #762, plus monitor noise around #758/#759). The Railway pre-flight at `.github/workflows/staging-pipeline.yml:49-58` queries `{me{id}}` with `Authorization: Bearer $RAILWAY_TOKEN`, which **only an Account Token can satisfy** — workspace and project tokens cannot answer `me`. Railway's official docs publish no TTL for any token type, but the dashboard exposes an expiration field when minting a token, and `docs/RAILWAY_TOKEN_ROTATION_742.md` is correct that selecting **"No expiration"** is the durable fix. The previous investigation (issue #762, run `7aff677993bdaf14206873cdd7ba86aa`) recommended a *workspace* token — that would break this workflow's `me{id}` probe. The correct token type for this repo is **Account Token** with No expiration.

---

## Findings

### 1. Railway token model — three types, distinct headers, distinct query scopes

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation (railway.com)
**Relevant to**: Choosing the correct token type for the validate step at `.github/workflows/staging-pipeline.yml:49-58`.

**Key information**:

- Railway has four token classes: **Account Token**, **Workspace Token**, **Project Token**, **OAuth Token**.
- Account Token — *"tied to your Railway account. This is the broadest scope. The token can perform any API action you are authorized to do across all your resources and workspaces."*
- Workspace Token — *"scoped to that workspace. A workspace token has access to all the workspace's resources, and cannot be used to access your personal resources or other workspaces on Railway."*
- Project Token — *"scoped to a specific environment within a project and can only be used to authenticate requests to that environment."*
- **Header convention is different per type**: Account, workspace, and OAuth tokens use `Authorization: Bearer <TOKEN>`; **project tokens use `Project-Access-Token: <TOKEN>`** (NOT `Authorization: Bearer`).
- **The `me { id }` GraphQL query works only with Account Tokens**: the docs explicitly state that `me` "cannot be used with a workspace or project token because the data returned is scoped to your personal account."
- All token types authenticate against `https://backboard.railway.com/graphql/v2`.

**Direct implication for this repo**: `staging-pipeline.yml:49-52` does `curl … "Authorization: Bearer $RAILWAY_TOKEN" … '{"query":"{me{id}}"}'`. That payload is incompatible with workspace and project tokens. The secret in `RAILWAY_TOKEN` **must be an Account Token** — minted at https://railway.com/account/tokens with **"No workspace"** selected — or the validate step will fail even with a brand-new, non-expired token.

---

### 2. Railway docs publish NO token TTL for Account/Workspace/Project tokens — only OAuth tokens have a documented lifetime

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens) and [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Whether tokens are guaranteed to expire on a fixed schedule (they aren't — TTL is operator-chosen at mint time).

**Key information**:

- For Account, Workspace, and Project tokens: **the docs contain no information about expiration policies, TTL, lifetime, or rotation requirements.**
- For OAuth: *"Access tokens expire after one hour."* Refresh tokens are rotated and *"the new refresh token has a fresh one-year lifetime from the time of issuance."* These are NOT the type used in CI here.
- The "expiration" the Reli runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md:18-21`) refers to is a **dashboard-side TTL field set at token-creation time**, not a server-side mandatory rotation. Per the runbook: *"When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days). Previous rotations may have used these defaults. The new token must be created with 'No expiration'."*
- Implication: The recurring failure cadence (~once every few weeks across #733/#739/#742/#755/#762/#766) is consistent with rotators repeatedly accepting the dashboard's default TTL instead of explicitly selecting "No expiration."

---

### 3. Community confirmation: `RAILWAY_TOKEN` env var name is conventionally tied to project tokens, but raw curl bypasses CLI conventions

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720) and [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community help (semi-official; staff and power users participate); two independent threads with the same finding.
**Relevant to**: Avoiding token-type confusion when rotating; understanding why this repo's `RAILWAY_TOKEN` secret name does not constrain token type.

**Key information**:

- Railway CLI convention: `RAILWAY_TOKEN` is **for project tokens**; `RAILWAY_API_TOKEN` is **for account/personal tokens**. Quote: *"RAILWAY_TOKEN now only accepts project token, if u put the normal account token...it literally says 'invalid or expired'"* — but this is a CLI-imposed constraint, **not an HTTP-API constraint**.
- This Reli workflow does NOT use `railway` CLI; it makes raw `curl` POSTs to `backboard.railway.app/graphql/v2`. The env-var **name** is just a label — the only thing that matters is what value is pasted in. With `Authorization: Bearer`, the payload is interpreted by the API as an Account/Workspace token; project tokens would need `Project-Access-Token` header instead.
- Common rotation mistake noted on the help station: minting a token in *project settings* (which produces a project token) and pasting it where an account token is expected — this would also produce `Not Authorized`. The new token must be minted at **https://railway.com/account/tokens** (account-level page), not from a project's settings.

---

### 4. Endpoint host: `backboard.railway.app` vs `backboard.railway.com` — both resolve, current docs prefer `.com`

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), corroborated by a Help Station thread noting *"the correct API endpoint is `https://backboard.railway.com/graphql/v2`, not `https://backboard.railway.app/graphql/v2`"*.
**Authority**: Official Railway docs (canonical) plus community confirmation.
**Relevant to**: The workflow currently uses `backboard.railway.app` (lines 49, 71, plus the prod-deploy job copy and `railway-token-health.yml`) — historically valid, but `.com` is what current docs use after Railway's domain migration.

**Key information**:

- Reli's workflow: `https://backboard.railway.app/graphql/v2` (still functional — verified by the fact that the failing run *did* get a JSON `Not Authorized` response from the API rather than a DNS/TLS error).
- Current docs: `https://backboard.railway.com/graphql/v2`.
- **This is NOT the cause of #766** (the request reached the API and got rejected with a 401-equivalent, not a connection failure). But it is technical debt worth noting for the same out-of-scope follow-up the prior investigation flagged.

---

### 5. Workspace tokens are Railway's recommended choice for shared/team CI — but only when the workflow does not use account-scoped queries

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api) (token-comparison table)
**Authority**: Official Railway documentation
**Relevant to**: Disambiguating the previous investigation's recommendation, which said "use a workspace token."

**Key information**:

- Railway publishes a recommendation table where Workspace Token is listed as *"Best For: Team CI/CD, shared automation."*
- However — this generic guidance assumes the workflow uses workspace-scoped operations. **Reli's pre-flight uses `me { id }`, which is account-scoped.** Switching to a workspace token would make a freshly-rotated, non-expired token still fail the validate step with `Not Authorized` (because the account-scoped `me` field is empty for workspace-token contexts).
- **Conclusion**: The previous investigation's "use a workspace token" recommendation (in `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md:86`) is incorrect for this workflow as written. The choice is binary: either (a) keep `me{id}` and use an Account Token, or (b) switch the validate step to a workspace-compatible query and use a Workspace Token. Option (a) is the minimum-change fix.

---

## Code Examples

The Railway docs' canonical example for authenticating to the GraphQL API matches the pattern Reli uses, with the corrected hostname:

```bash
# From https://docs.railway.com/integrations/api (Account Token example)
curl -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ me { id } }"}'
```

For project tokens, the header changes (NOT applicable here, included for contrast):

```bash
# From https://docs.railway.com/integrations/api (Project Token example)
curl -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_PROJECT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"..."}'
```

---

## Gaps and Conflicts

- **Gap — published TTL**: Railway's docs do not publish maximum lifetimes for Account/Workspace/Project tokens. The "No expiration" option is observable in the dashboard UI but is not described in the public docs. Web search did not return a Railway changelog or blog post stating whether "No expiration" tokens can be revoked server-side after some hidden ceiling.
- **Gap — UI screenshots for current dashboard**: The dashboard token-creation UI as of April 2026 was not captured in publicly indexed docs; reliance on the runbook's textual description of *"Expiration: No expiration (critical — do not accept default TTL)"* is the best available source.
- **Conflict — prior investigation's token-type advice**: `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md:86` recommends "Workspace token — narrowest viable scope for `me{id}` probes." This contradicts the Railway docs (Finding #1), which state `me` is incompatible with workspace tokens. **Resolution**: prefer the official docs — use an Account Token until the validate step is rewritten.
- **Gap — automation**: No documented Railway feature lets a script auto-rotate Account Tokens before expiry; the rotation is necessarily a human action via dashboard, which matches the CLAUDE.md Category-1 prohibition on agents claiming rotation completion.

---

## Recommendations

Based on research, ordered by impact:

1. **Mint an Account Token with "No expiration", not a Workspace token.** The validate step's `me{id}` query rejects workspace and project tokens by design (Finding #1). The token must be created at https://railway.com/account/tokens with **"No workspace"** selected and **Expiration: No expiration**. This both fixes #766 and prevents recurrence #8 — provided no one accidentally accepts the default TTL again.

2. **Correct the prior investigation's token-type guidance before it becomes load-bearing.** The active runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` correctly says "create at https://railway.com/account/tokens" — do not let the workspace-token suggestion in `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md:86` propagate into the runbook. (Out-of-scope for the bead per Polecat — flag to mayor.)

3. **Treat #766 as identical to #762 mechanically.** Same root cause, same evidence chain, same fix. The repository is healthy; the fix is a human secret rotation. Per CLAUDE.md, do **not** create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming the rotation is done — file the issue/route to mayor and point at `docs/RAILWAY_TOKEN_ROTATION_742.md` as the canonical runbook.

4. **(Out of scope, route to mayor)**: Two latent issues that don't block #766 but accumulate risk:
   - Endpoint host `backboard.railway.app` → `backboard.railway.com` migration (Finding #4).
   - Validate-step query design: if the project ever needs to switch to a Workspace token to reduce blast radius, the `me{id}` probe needs to be replaced with a workspace-scoped query (e.g., a small `projects` query the token has visibility into).

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API (Tokens) | https://docs.railway.com/integrations/api | Authoritative token-type definitions, headers, and `me{id}` scope rule |
| 2 | Railway Docs — Login & Tokens (OAuth) | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth TTL details; confirms no documented TTL for Account/Workspace/Project tokens |
| 3 | Railway Docs — Using the CLI | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env-var convention |
| 4 | Railway Docs — Deploying with the CLI | https://docs.railway.com/cli/deploying | Project-token usage in CI |
| 5 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Recommended GH Actions setup; confirms token-as-secret pattern |
| 6 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account-vs-project token confusion in CI; CLI bug history |
| 7 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Identical error message; confirms token-type mismatch as a common cause |
| 8 | Railway Help Station — API Token "Not Authorized" | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | **"No workspace"** must be selected when minting account tokens |
| 9 | Railway Help Station — GraphQL Not Authorized for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | GraphQL endpoint behavior with PATs |
| 10 | Local — `docs/RAILWAY_TOKEN_ROTATION_742.md` | (in-repo) | Canonical rotation runbook; correctly specifies "No expiration" |
| 11 | Local — `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md` | (in-repo) | Prior #762 investigation; contains workspace-token recommendation that conflicts with Finding #1 |
