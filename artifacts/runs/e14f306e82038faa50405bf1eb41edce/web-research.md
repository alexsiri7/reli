# Web Research: fix #829

**Researched**: 2026-05-01T04:05:00Z
**Workflow ID**: e14f306e82038faa50405bf1eb41edce

---

## Summary

Issue #829 is the 31st recurrence of `RAILWAY_TOKEN is invalid or expired: Not Authorized` blocking the staging deploy on `main` (SHA `afbf134`). Web research confirms there is no programmatic, agent-accessible way to rotate the token: it must be re-created in the Railway dashboard by a human and re-uploaded to the GitHub `RAILWAY_TOKEN` secret. Two structural fixes worth surfacing to the human: (1) the token used for the `{me{id}}` validation step must be an **account/workspace-scoped** token (project tokens fail this query), and (2) Railway tokens default to a TTL — if the new token is created **with no expiration**, the recurrence pattern stops.

---

## Findings

### 1. Railway uses three distinct token types — only some authenticate `{me{id}}`

**Source**: [Railway Help Station — "GraphQL requests returning Not Authorized for PAT"](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52), [Railway Help Station — "API Token Not Authorized for Public API and MCP"](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Official Railway community Q&A site, answers from Railway team / verified users
**Relevant to**: The `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml` that ran the `{me{id}}` GraphQL probe and got `Not Authorized`.

**Key Information**:

- Railway has three token scopes: **Personal Access Token (PAT)**, **Workspace/Team Token**, and **Project Token**.
- Personal/workspace tokens authenticate via `Authorization: Bearer <token>` against `https://backboard.railway.app/graphql/v2`.
- **Project tokens do NOT use the `Authorization` header — they use a separate `Project-Access-Token` header.** Sending a project token via `Authorization: Bearer` returns `Not Authorized`.
- Project tokens cannot query the `me` object, cannot query `service` directly, and cannot create preview environments. They are scoped to one project + environment.
- For CI that needs to *trigger deployments* (not just read), workspace or account-scoped tokens are the canonical choice.

### 2. Railway tokens have a default TTL — "No expiration" is opt-in

**Source**: [Railway Help Station — "RAILWAY_TOKEN invalid or expired"](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20), [Railway Help Station — "Token for GitHub Action"](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway community Q&A; corroborates the local runbook in `docs/RAILWAY_TOKEN_ROTATION_742.md`.
**Relevant to**: The recurrence pattern — this issue has fired 31 times, suggesting each rotation has been done with a finite TTL.

**Key Information**:

- Tokens created from `https://railway.com/account/tokens` accept an explicit expiration setting; the form defaults to a finite TTL (commonly 7 or 30 days depending on the workspace policy).
- Selecting **"No expiration"** when creating the token is required for CI use that should not need periodic human rotation.
- The error string `RAILWAY_TOKEN is invalid or expired: Not Authorized` is emitted both for actual expiration AND for token-type mismatches (account vs. project), so the next rotation must verify both.
- Railway's OAuth access tokens are unrelated and expire after 1 hour — those are not what the GitHub Actions workflow uses.

### 3. The local repo already has a rotation runbook keyed off issue #742

**Source**: `docs/RAILWAY_TOKEN_ROTATION_742.md` (in this repo)
**Authority**: First-party runbook authored during prior incident.
**Relevant to**: Direct human action — the resolution path for #829.

**Key Information**:

- Steps:
  1. Create a new token at `https://railway.com/account/tokens` named `github-actions-permanent`, with **Expiration: No expiration** (called out as "critical").
  2. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`, paste new token.
  3. Re-run the failed CI: `gh run list --repo alexsiri7/reli --status failure --limit 1 --json databaseId --jq '.[0].databaseId' | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed`.
- The runbook records this as the "third occurrence" — the recent commit history (`afbf134`, `cd886a7`, `89e361a`, ...) shows this is now the 31st, so the no-expiration step has not been followed in subsequent rotations.

### 4. Per project policy, agents cannot perform the rotation

**Source**: `CLAUDE.md` § "Railway Token Rotation" (in this repo)
**Authority**: Project instructions, owner-authored.
**Relevant to**: What this agent is allowed to do for #829.

**Key Information**:

- "Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com."
- Explicit: "Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done."
- Required action: file an issue or send mail to mayor with the error details, point human at `docs/RAILWAY_TOKEN_ROTATION_742.md`. Issue #829 is already filed — that obligation is met.
- "Creating documentation that claims success on an action you cannot perform is a Category 1 error."

### 5. Structural alternatives to a long-lived `RAILWAY_TOKEN`

**Source**: [Railway Docs — Deploying with the CLI](https://docs.railway.com/cli/deploying), [Railway Blog — Using GitHub Actions with Railway](https://blog.railway.com/p/github-actions), [Setup Railway CLI Action](https://github.com/marketplace/actions/setup-railway-cli)
**Authority**: Official Railway docs and Railway-published blog post.
**Relevant to**: Whether the recurrence loop can be broken architecturally rather than just by setting "no expiration" once.

**Key Information**:

- The current workflow uses a **raw GraphQL `curl`** to `{me{id}}` for token validation, which forces the token to be account/workspace-scoped. If the deploy step itself only needs to push a build to one project+environment, switching the deploy to a **project token + `railway up`** would scope the blast radius and eliminate the `{me{id}}` validation requirement.
- Railway also offers **GitHub Actions self-hosted runners** ([docs](https://docs.railway.com/guides/github-actions-runners)) which authenticate at the workspace level and can avoid embedding a long-lived token in GitHub secrets entirely. Heavier lift; mentioned for completeness.
- No GitHub OIDC trust-relationship integration with Railway was found in the docs as of this research — so OIDC-based ephemeral auth (the standard fix for "rotating CI token forever") is not available here.

---

## Code Examples

The current validation block from the failed run (reconstructed from the log in `gh run view 25199559238 --log-failed`):

```bash
# From .github/workflows/staging-pipeline.yml — "Validate Railway secrets" step
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

Note the `Bearer` prefix — this is the workspace/account-token style. Switching to a project token here would require changing both the header (`Project-Access-Token: ...`) and the probe query (`{me{id}}` would not work; use a project-scoped query instead).

---

## Gaps and Conflicts

- **No primary documentation** of the exact "No expiration" UI option in current Railway dashboard screenshots was found via search. The local runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) is the strongest evidence the option exists; corroborated indirectly by community Q&A but not by an official docs page returned in this search.
- **Conflict** between two community sources on which env var GitHub Actions needs: one ([token-for-git-hub-action](https://station.railway.com/questions/token-for-git-hub-action-53342720)) recommends `RAILWAY_API_TOKEN` for account-scoped tokens; another ([railway-token-invalid-or-expired](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)) says "RAILWAY_TOKEN now only accepts project token" and that conflicting `RAILWAY_API_TOKEN` should be removed. The reli workflow uses `RAILWAY_TOKEN` with what is functionally an account-scoped token (since it queries `{me{id}}`). This works today (when not expired) but contradicts the second source's guidance — likely Railway's CLI behavior diverged from the raw GraphQL endpoint's behavior. Worth flagging to the human during rotation.
- No public Railway-side OIDC / GitHub federated identity feature was surfaced in search results — so the "remove long-lived secrets entirely" pattern available with AWS/GCP is not currently applicable to Railway.

---

## Recommendations

1. **For the immediate #829 fix (human action required)**: file the recurrence with the human and reference `docs/RAILWAY_TOKEN_ROTATION_742.md`. When the human rotates, the **single most important step** is selecting **"No expiration"** at token creation — this is the variable that explains why this issue has now recurred 31 times. Per `CLAUDE.md`, this agent must not claim to perform the rotation itself.

2. **Verify the new token type at rotation time**: the token must answer `{me{id}}` successfully via `Authorization: Bearer <token>`. That means it must be a **personal access token** or **workspace/team token** — *not* a project token. A project token will silently fail the validation step with the same "Not Authorized" error and look like another expiration.

3. **Worth raising as a follow-up (out of scope for this bead)**: the `{me{id}}` probe is a cheap correctness test but it forces the broadest possible token scope. If the deploy step only needs to push to one project, refactoring the workflow to use a project token + `railway up` would reduce blast radius and remove the dependency on an account-level token. This is a workflow design change, not part of fixing #829, so per Polecat Scope Discipline it should go via mail to mayor rather than into this PR.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Help — "RAILWAY_TOKEN invalid or expired" | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Direct match for the error string; covers token-type mismatch root cause |
| 2 | Railway Help — GraphQL "Not Authorized" for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Explains which token types can authenticate against the GraphQL API |
| 3 | Railway Help — API Token "Not Authorized" for Public API | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Header rules: project token uses `Project-Access-Token`, not `Authorization` |
| 4 | Railway Help — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Recommends account/workspace-scoped tokens for GH Actions |
| 5 | Railway Docs — Deploying with the CLI | https://docs.railway.com/cli/deploying | Canonical `railway up` deploy patterns |
| 6 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Setup pattern: token in repo secret, referenced via `${{ secrets.RAILWAY_TOKEN }}` |
| 7 | Railway Docs — CLI guide | https://docs.railway.com/guides/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env var precedence |
| 8 | Railway Docs — Login & Tokens (OAuth) | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth access tokens (1 hour) — separate from CI tokens; ruled out as cause |
| 9 | Railway Docs — GitHub Actions Self-Hosted Runners | https://docs.railway.com/guides/github-actions-runners | Alternative auth pattern (heavier lift, noted for completeness) |
| 10 | Setup Railway CLI Action | https://github.com/marketplace/actions/setup-railway-cli | Reference Action for the canonical workflow shape |
| 11 | Local runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | First-party rotation steps, including "No expiration" requirement |
| 12 | Local project rules | `CLAUDE.md` § Railway Token Rotation | Boundary: agent cannot rotate; must not claim to have done so |
