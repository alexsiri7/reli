# Web Research: fix #832 (RAILWAY_TOKEN invalid or expired)

**Researched**: 2026-05-01T05:00Z
**Workflow ID**: 75035b4ef8a9c5429c2d4e9d689a12a6
**Issue**: #832 — Main CI red: Deploy to staging — `RAILWAY_TOKEN is invalid or expired: Not Authorized`

---

## Summary

The CI failure is the same recurring pattern that has produced six prior issues (#733, #739, #742, #821, #824, #825, #828, #829, #831 etc.): the `RAILWAY_TOKEN` GitHub Actions secret returns `Not Authorized` from `backboard.railway.app`. Web research confirms (a) `RAILWAY_TOKEN` only accepts a **project token** (not an account or workspace token), and (b) Railway's own docs do **not** publicly document a "no expiration" option for project tokens — contradicting an assumption baked into `docs/RAILWAY_TOKEN_ROTATION_742.md`. The repeating failures suggest the rotated tokens are still being created with a finite TTL or are being invalidated by another mechanism (account/workspace re-scoping, token rotation, revocation).

The fix is human-only: rotate the token at https://railway.com/account/tokens (or in the project's Settings → Tokens) and update the GitHub secret. Per `CLAUDE.md`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` "done" doc — only file the issue and direct the human to the runbook.

---

## Findings

### 1. RAILWAY_TOKEN must be a *project* token

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Official Railway community help forum, answers from Railway staff.
**Relevant to**: Why rotated tokens may still fail with "Not Authorized" even when freshly created.

**Key Information**:
- "RAILWAY_TOKEN now only accepts *project token*."
- An account-level token (created from `railway.com/account/tokens`) will fail with `invalid or expired` even if just generated. The error message is the same regardless of underlying cause.
- Recreating an account token does not fix the problem; the operator must generate the token from **Project Settings → Tokens**, not the account page.
- If both `RAILWAY_API_TOKEN` and `RAILWAY_TOKEN` are set, they can conflict.

**Note for #832**: `docs/RAILWAY_TOKEN_ROTATION_742.md` directs the operator to `https://railway.com/account/tokens` — this is the **account tokens** page. If the runbook is being followed literally, the rotated tokens may be account tokens, which `RAILWAY_TOKEN` rejects. This could explain the recurring failures.

---

### 2. Token taxonomy and headers

**Source**: [Public API — Railway Docs](https://docs.railway.com/integrations/api), [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway docs.
**Relevant to**: Picking the right token type and env var for GitHub Actions deploys.

**Key Information**:
- Railway has **four** token kinds:
  1. **Account tokens** — broadest scope; all resources/workspaces.
  2. **Workspace tokens** — single workspace.
  3. **Project tokens** — single environment in a project.
  4. **OAuth tokens** — user-granted permissions.
- Project tokens use the `Project-Access-Token` header. Account/workspace/OAuth tokens use `Authorization: Bearer …`.
- For CI: set `RAILWAY_TOKEN` for project-scoped actions, `RAILWAY_API_TOKEN` for account-scoped actions. If both are set, **`RAILWAY_TOKEN` takes precedence**.

**Implication for the validation step in `.github/workflows/staging-pipeline.yml`**: that step uses `Authorization: Bearer …` against `backboard.railway.app/graphql/v2 { me { id } }`. The `me` query is an *account-level* query — a project token would be rejected here even if it works for `railway up`. If the validator is sending a project token via `Bearer`, it is testing the wrong API surface. This is worth verifying when the human is rotating, because the validator's "Not Authorized" may not mean the deploy token is broken.

---

### 3. Token expiration policies (what Railway documents vs. doesn't)

**Source**: [Login & Tokens — Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [OAuth Troubleshooting — Railway Docs](https://docs.railway.com/integrations/oauth/troubleshooting)
**Authority**: Official Railway docs.
**Relevant to**: Whether the rotated token is supposed to last forever.

**Key Information**:
- **OAuth access tokens**: 1 hour.
- **OAuth refresh tokens**: 1 year from issuance, rotated; using a rotated token immediately revokes the entire authorization (security tripwire).
- Railway's docs do **not** publicly document an expiration policy for manually-created project, workspace, or account tokens. They also do not document a "No expiration" option.
- Suddenly-failing tokens are typically caused by: rotation (using an old refresh token), missing OAuth scopes, or user re-authentication being required (refresh token unused for a year).

**Conflict with internal runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md` instructs operators to set "Expiration: No expiration (critical — do not accept default TTL)". Web research found **no public Railway docs corroborating that this option exists** in the project tokens UI. The runbook may be either (a) referencing a UI option that exists but is undocumented, or (b) wrong. If (b), every rotation since #742 has installed a token with a finite TTL, which would explain the steady ~weekly cadence of recurrences.

---

### 4. Recommended GitHub Actions setup

**Source**: [Using Github Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions), [GitHub Actions PR Environment — Railway Docs](https://docs.railway.com/guides/github-actions-pr-environment)
**Authority**: Official Railway blog/docs.
**Relevant to**: Confirming the workflow's secret/wiring is canonical.

**Key Information**:
- Generate the token from the **project dashboard** Settings → Tokens.
- Store as `RAILWAY_TOKEN` in repo secrets. Pass as env to the Railway CLI step:
  ```yaml
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
  ```
- `railway up --service <SERVICE_ID>` is the standard deploy command. The service ID is not secret.
- The blog post does **not** address rotation cadence or expiration.

---

### 5. Other "Not Authorized" causes worth considering

**Source**: [Authentication not working with RAILWAY_TOKEN — Railway Help Station](https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7), [Workspaces — Railway Docs](https://docs.railway.com/reference/teams)
**Authority**: Railway docs / staff-monitored community forum.
**Relevant to**: Alternative root causes beyond "TTL expired".

**Key Information**:
- A workspace-scoped token can be created accidentally by leaving the "workspace" field set when generating an account token. To get an *account-scoped* token, leave the workspace blank.
- Transferring a project to a different workspace can invalidate project tokens that were scoped to the prior workspace.
- Token revocation (manual or automatic, e.g. >100 refresh tokens for one user) silently invalidates without notice.
- Membership changes to a Railway team can revoke previously-issued tokens.

These are plausible alternative explanations if the operator is certain the previous rotations selected a long-lived token.

---

## Code Examples

The repo's current validation step (referenced in the failing job log) approximately:

```bash
# From .github/workflows/staging-pipeline.yml (per failed run logs)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  echo "::error::RAILWAY_TOKEN is invalid or expired: ..."
fi
```

Per finding #2, `{ me { id } }` is an account-level query. If `RAILWAY_TOKEN` is a project token (which Railway requires for `railway up`), this preflight can fail even when the actual deploy would succeed. **This may not be the root cause of #832, but it is worth confirming during human investigation** — re-running the deploy with the validator step skipped would distinguish "token actually broken" from "wrong preflight check".

---

## Gaps and Conflicts

- **Gap**: Railway does not publicly document the expiration policy of manually-created project/workspace/account tokens. Whether a "No expiration" option exists in the project token UI cannot be verified from public docs.
- **Gap**: No public Railway changelog entry was found explaining why a previously-working token would start returning `Not Authorized` on a regular cadence.
- **Conflict**: Internal runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) asserts a "No expiration" option exists; Railway's public docs do not corroborate. The repeating failure pattern (#733 → … → #832, ≈monthly) is consistent with a finite TTL still being applied on each rotation.
- **Gap**: The validator step's choice of `me { id }` for a project token preflight is not addressed by any public Railway guidance found.

---

## Recommendations

Strictly following `CLAUDE.md` ("Agents cannot rotate the Railway API token. … Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done."), the agent's job here is to file the issue / mail mayor and direct the human to the runbook. The recommendations below are for the **human** operator and for any future bead that explicitly modifies the workflow.

1. **Rotate the token from the *project* dashboard, not the account page.** Use Project Settings → Tokens. This addresses finding #1 — `RAILWAY_TOKEN` rejects account tokens.
2. **When rotating, explicitly select the longest-lived option Railway offers** (no expiration if the UI exposes it; otherwise the maximum TTL). If "No expiration" is not visible, update `docs/RAILWAY_TOKEN_ROTATION_742.md` to reflect reality so future operators don't think they're doing something they aren't.
3. **Consider replacing the `{ me { id } }` preflight** with a project-scoped query (or with a `railway whoami` / `railway status` invocation against the project token), so the validator tests the same API surface the deploy uses. This is a separate bead — out of scope for #832 per the polecat scope discipline; mail mayor if not already tracked.
4. **Investigate workspace/team membership changes** as an alternative root cause. If this token is shared via a workspace and someone transferred or re-invited recently, the token would silently invalidate (finding #5).
5. **Do NOT** create `.github/RAILWAY_TOKEN_ROTATION_*.md`. The current task is documenting the recurrence and pointing at `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | RAILWAY_TOKEN invalid or expired (Help Station) | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Confirms RAILWAY_TOKEN only accepts project tokens; account tokens fail with same error |
| 2 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Token taxonomy (account/workspace/project/OAuth), header conventions, RAILWAY_TOKEN precedence |
| 3 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token lifetimes (1h access / 1y refresh); does NOT document project-token TTL |
| 4 | OAuth Troubleshooting — Railway Docs | https://docs.railway.com/integrations/oauth/troubleshooting | "Not Authorized" causes: expired access token, rotated refresh token, scope mismatch |
| 5 | Token for GitHub Action (Help Station) | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Confirms project token is the right type for GH Actions |
| 6 | Using Github Actions with Railway — Railway Blog | https://blog.railway.com/p/github-actions | Canonical wiring of `RAILWAY_TOKEN` secret + `railway up` |
| 7 | Authentication not working with RAILWAY_TOKEN (Help Station) | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | Workspace-scoping pitfall; tokens silently revoked on team/workspace changes |
| 8 | Workspaces — Railway Docs | https://docs.railway.com/reference/teams | Workspace scoping rules relevant to "Not Authorized" recurrences |
| 9 | GitHub Actions PR Environment — Railway Docs | https://docs.railway.com/guides/github-actions-pr-environment | Reference for canonical Railway-CLI-in-CI patterns |
| 10 | RAILWAY_API_TOKEN not being respected (Central Station) | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Confirms `RAILWAY_TOKEN` precedence and conflict scenarios |
