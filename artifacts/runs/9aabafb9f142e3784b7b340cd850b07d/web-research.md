# Web Research: fix #808

**Researched**: 2026-04-30T19:30:00Z
**Workflow ID**: 9aabafb9f142e3784b7b340cd850b07d
**Issue**: [#808 — Prod deploy failed on main](https://github.com/alexsiri7/reli/issues/808)
**Failing run**: https://github.com/alexsiri7/reli/actions/runs/25184101688

---

## Summary

Issue #808 is the **22nd recurring `RAILWAY_TOKEN is invalid or expired: Not Authorized`** failure of the staging→production pipeline (predecessors: #798, #800, #801, #804, #805). Per CLAUDE.md, agents cannot rotate this token — that requires human access to railway.com. Research surfaces two structural drivers behind the chronic recurrence: (1) Railway offers **three token tiers** (account, workspace, project) with very different lifetimes and trust profiles, and (2) the workflow currently authenticates as a **user-scoped token** via `Authorization: Bearer` + `{me{id}}`, which suggests an account token rather than the workspace or project token Railway recommends for team CI/CD. Migrating to a **workspace token** (drop-in: same Bearer header, same `{me{id}}` query works, scoped to a workspace not a person) is the lowest-risk durable fix.

---

## Findings

### 1. Railway has three token tiers — current setup uses the most fragile one

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Root cause of the recurring expirations

**Key Information**:

The official token comparison table:

| Token Type | Scope | Best For |
|------------|-------|----------|
| Account token | "All your resources and workspaces" | "Personal scripts, local development" |
| Workspace token | "Single workspace" | **"Team CI/CD, shared automation"** |
| Project token | "Single environment in a project" | "Deployments, service-specific automation" |

Railway explicitly recommends **workspace tokens** for "Team CI/CD" — exactly this use case. The current pipeline is most likely using an **account token** (account tokens are user-bound and the most likely to be revoked/rotated when a user changes team, password, or session — explaining the 22-cycle churn).

---

### 2. Header format differs by token tier — it's a one-shot switch

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Whether the workflow can be migrated to a different token tier

**Key Information**:

Quoted directly from the docs:
> "Project tokens use the `Project-Access-Token` header, not the `Authorization: Bearer` header used by account, workspace, and OAuth tokens."

Implication for `.github/workflows/staging-pipeline.yml` and `.github/workflows/railway-token-health.yml`:

- **Migrate to workspace token** → drop-in. `Authorization: Bearer $RAILWAY_TOKEN` works, `{me{id}}` validation works (workspace tokens are tied to a workspace member). **Zero workflow code changes.**
- **Migrate to project token** → requires workflow edits: change `Authorization: Bearer` to `Project-Access-Token`, and replace `{me{id}}` validation (project tokens are not user-bound and cannot resolve `me`).

---

### 3. The failure mode "valid token rejected as invalid/expired" is a known token-type-mismatch trap

**Source**: [RAILWAY_TOKEN invalid or expired — Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community forum, answer from `bytekeim` (Railway moderator)
**Relevant to**: Why rotations sometimes "fix nothing" — the new token is rejected immediately

**Key Information**:

Direct quote:
> "RAILWAY_TOKEN now only accepts *project token*, if u put the normal account token … it literally says 'invalid or expired' even if u just made it 2 seconds ago."

This contradicts the docs above (which list `RAILWAY_TOKEN` as project-scoped *for the CLI*) and reveals an important nuance: the variable name `RAILWAY_TOKEN` is **CLI-scoped to project tokens**, while raw GraphQL calls (what this repo uses) accept Bearer-style account/workspace tokens regardless of variable name. Both this repo's workflows hit GraphQL directly via curl — so account/workspace tokens DO work here, but a future maintainer who reads "use a project token" advice and pastes one in WILL see "invalid or expired" because the curl uses `Authorization: Bearer` not `Project-Access-Token`.

**This is a footgun in the runbook.** `docs/RAILWAY_TOKEN_ROTATION_742.md` should explicitly state: "create a **workspace token**, not a project token, not an account token."

---

### 4. Token expiration: docs are silent on workspace/project lifetime

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Whether "no expiration" is even an option

**Key Information**:

- **OAuth access tokens**: "Access tokens expire after one hour."
- **OAuth refresh tokens**: "fresh one-year lifetime from the time of issuance"
- **Account / workspace / project tokens**: documentation **does not state any expiration policy**. Token creation UI in the dashboard offers TTL choices (1d/7d/30d/no expiration); the existing runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` notes "The new token must be created with 'No expiration'."

This means the chronic 22-cycle recurrence is likely **not** Railway-imposed expiration — it's either (a) account-token-tied-to-user revocation, (b) a default TTL being accepted at create time, or (c) a manual rotation routine someone is following on a schedule.

---

### 5. Existing community-maintained option for automated rotation

**Source**: [Deploy Railway Secret](https://railway.com/deploy/railway-secrets)
**Authority**: Railway-published deploy template (community-built, Railway-listed)
**Relevant to**: Whether automated rotation is realistic without human intervention

**Key Information**:

A self-hosted "Railway Secrets" dashboard exists that supports "manual and scheduled rotation, per-secret intervals, encrypted rollback history, and session-based admin access." This is overkill for a single token but worth knowing. Doesn't remove the need for a human to bootstrap; does remove the need for repeated manual rotation.

---

### 6. CLI vs raw GraphQL — current repo bypasses the CLI

**Source**: [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli), [Using GitHub Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions)
**Authority**: Official Railway docs and blog
**Relevant to**: Whether to consider switching strategy

**Key Information**:

The Railway-recommended GitHub Actions pattern uses `ghcr.io/railwayapp/cli:latest` as the job container and runs `railway up --service=$SVC_ID`. The current repo's workflow instead calls `backboard.railway.app/graphql/v2` directly via curl with hand-rolled GraphQL mutations (`serviceInstanceUpdate`, `serviceInstanceDeploy`).

Trade-off: the curl approach is lighter-weight (no container pull) and works with workspace tokens cleanly. The CLI approach is what Railway officially supports and might absorb future API changes more gracefully — but it's `RAILWAY_TOKEN` = project-token via the CLI's env-var convention, which would mean re-scoping.

**Recommendation**: stay on curl + workspace token. Current architecture is fine; just fix the token tier.

---

## Code Examples

### Current workflow (already correct for account/workspace tokens)

From `.github/workflows/staging-pipeline.yml:49-52`:

```bash
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

This is the right shape for a **workspace token**. No code change needed if the secret value is rotated to a workspace token instead of an account token.

### What would change if migrating to a project token (NOT recommended)

```bash
# Header would change:
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId } }"}')   # {me{id}} no longer works
```

(See [Public API | Railway Docs](https://docs.railway.com/integrations/api) for header documentation.)

---

## Gaps and Conflicts

- **Gap**: Railway docs do **not** publish an expiration policy for workspace or project tokens. Empirical evidence from this repo's history (22 rotations) suggests *something* is causing recurrence, but research cannot pinpoint whether it is Railway-side TTL, account-token-tied-to-session-revocation, or human-driven rotation. **Action**: ask in the Railway Help Station whether workspace tokens have a hidden TTL.
- **Conflict**: Community guidance ("RAILWAY_TOKEN only accepts project token") contradicts the GraphQL-direct-call pattern used in this repo (which accepts account/workspace Bearer tokens fine). The contradiction is resolved by noting that the community guidance refers to the **CLI's interpretation** of `RAILWAY_TOKEN`; raw GraphQL calls don't go through the CLI.
- **Outdated**: `docs/RAILWAY_TOKEN_ROTATION_742.md` doesn't specify which token tier to create. After 22 rotations this gap likely contributes to the recurrence — different humans pick different tier each time.

---

## Recommendations

Based on research, in order of priority:

1. **Rotate to a workspace token, not an account token** — this is the highest-leverage durable fix. Railway officially recommends workspace tokens for "Team CI/CD" ([source](https://docs.railway.com/integrations/api)). Workspace tokens are not bound to a single user account, eliminating the most likely root cause of recurring revocation. **No workflow code changes needed** — same `Authorization: Bearer` header, same `{me{id}}` validation. *(Human action — agent cannot do this.)*

2. **Update the rotation runbook** (`docs/RAILWAY_TOKEN_ROTATION_742.md`) to explicitly state:
   - Create a **workspace token** at https://railway.com/account/tokens (workspace tab), NOT an account token, NOT a project token.
   - Set expiration to "No expiration" at creation time.
   - Reasoning: each tier has different headers and lifetimes; picking the wrong tier wastes a rotation cycle.

3. **Do NOT switch to project tokens** for this pipeline. The header change (`Project-Access-Token` instead of `Authorization: Bearer`) plus the loss of `{me{id}}` as a validation primitive means a workflow rewrite. The marginal scope reduction isn't worth it given the 22-cycle history shows token tier confusion is the main cost.

4. **Do NOT attempt automated rotation from CI** — Railway's workspace tokens can't be programmatically created via API without an existing valid token (chicken-and-egg), and the third-party "Railway Secrets" dashboard adds infrastructure for what should be a once-and-done fix if the token is created with no expiration.

5. **Per CLAUDE.md, agent action for issue #808 itself**: file an investigation doc (don't claim rotation is done), confirm root cause is the same recurring token issue, and direct the human to the (updated) runbook.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API Docs | https://docs.railway.com/integrations/api | Official token tier table; header format rules |
| 2 | Railway Login & Tokens Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token expiration (1h/1y); silent on PAT TTLs |
| 3 | Railway CLI Docs | https://docs.railway.com/guides/cli | RAILWAY_TOKEN vs RAILWAY_API_TOKEN env var conventions |
| 4 | Railway Blog: GitHub Actions | https://blog.railway.com/p/github-actions | Recommended CLI-based GitHub Actions pattern |
| 5 | Help Station: token invalid/expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Token-type-mismatch failure mode quote (bytekeim) |
| 6 | Help Station: PAT GraphQL "Not Authorized" | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Confirms PAT vs workspace token distinction in errors |
| 7 | Railway Troubleshooting Docs | https://docs.railway.com/integrations/oauth/troubleshooting | OAuth-side troubleshooting (less relevant — PAT path) |
| 8 | Railway Secrets deploy template | https://railway.com/deploy/railway-secrets | Self-hosted automated rotation option (overkill here) |
| 9 | Railway GitHub Actions PR Environment | https://docs.railway.com/guides/github-actions-pr-environment | Token-scope guidance for workspace projects |
