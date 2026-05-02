# Web Research: fix #912

**Researched**: 2026-05-02T18:50:00Z
**Workflow ID**: dff05fb47bc6d33f0d9282dfe5d882c0
**Issue**: alexsiri7/reli#912 — "Prod deploy failed on main"

---

## Summary

Issue #912 is yet another `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure from the staging-pipeline validation step (commit `fdf6393`, run `25258939832`). Per `CLAUDE.md`, agents cannot rotate the token; this research targets the underlying Railway token model so the human rotator (and the existing runbook at `docs/RAILWAY_TOKEN_ROTATION_742.md`) can stop the recurrence loop. The two most actionable findings: (1) Railway's official GraphQL endpoint is `backboard.railway.com`, not the `backboard.railway.app` URL hard-coded in `.github/workflows/staging-pipeline.yml`; (2) Railway's `RAILWAY_TOKEN` env var historically refuses account tokens — it expects a **project token** (or workspace/team token for newer setups), and the "invalid or expired" string is also surfaced when the wrong *type* of token is used, not only when a token is past its TTL.

---

## Findings

### 1. Correct GraphQL endpoint is `backboard.railway.com`, not `.app`

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: The `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml`, which currently `curl`s `https://backboard.railway.app/graphql/v2`.

**Key information**:
- Railway docs and the Help Station explicitly state the API endpoint is `https://backboard.railway.com/graphql/v2` (`.com`, not `.app`).
- Multiple users in the Railway Help Station have reported "Not Authorized" responses when hitting the `.app` host — and resolved them by switching to `.com`.
- The validation step's JSON parsing succeeds and prints a Railway error message, so the `.app` host likely still resolves (cookie-domain or stale CDN), but it is not the documented endpoint and may be the cause of intermittent rejection of otherwise-valid tokens.

> "GraphQL requests returning 'Not Authorized' for PAT" — switching the endpoint from `.app` to `.com` is the canonical fix.
> — [Railway Help Station](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)

---

### 2. `RAILWAY_TOKEN` expects a project token, not an account token

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20), [Token for GitHub Action](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway Help Station (Railway-staffed community Q&A) and corroborated user reports
**Relevant to**: Whether the rotated token is the *right kind* of token. The current runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) tells the operator to create the token at `https://railway.com/account/tokens` — that is the **account** tokens page.

**Key information**:
- Railway has three token types stored in the `Authorization: Bearer` header:
  - **Account (personal) token** — broadest scope, all workspaces. Created at `account/tokens`.
  - **Workspace (team) token** — scoped to one workspace. Created at the workspace level.
  - **Project token** — scoped to one project + environment. Sent via `Project-Access-Token` header (not `Authorization`). Created in the project's Settings → Tokens.
- A Railway Help Station thread states bluntly: *"RAILWAY_TOKEN now only accepts project token. If u put the normal account token… it literally says 'invalid or expired'."* This means our recurring error string can fire when the rotator (correctly) creates a no-expiry token but creates the **wrong type**.
- For multi-environment / shared-team CI, Railway docs recommend the **workspace token** if you need cross-project access; the **project token** if you only deploy one service.
- For the Railway CLI specifically, account-scope is exposed as `RAILWAY_API_TOKEN`; project-scope is `RAILWAY_TOKEN`. The validation `curl` in our workflow uses the `me { id }` query — that query *requires* an account or workspace token; project tokens cannot satisfy `me`.

**Implication**: Our validation query (`{me{id}}`) and the deploy step may need *different* tokens, or the validation needs to switch to a query that all token types can answer (e.g. `projects { edges { node { id } } }`).

---

### 3. Token expiration model: account tokens can be created with no expiration; OAuth access tokens always expire in 1 hour

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens), [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why this issue keeps recurring. The repo has had **63+ RAILWAY_TOKEN expirations** as of 2026-05-02 (per recent commit history).

**Key information**:
- **OAuth access tokens** (interactive login flow) expire after **1 hour**. Refresh tokens last **1 year** and rotate.
- **Account / workspace / project tokens** (created in the dashboard) can be configured with a TTL or "No expiration" at creation time, per the existing repo runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`, which dates back to issue #742).
- The Railway dashboard's *default* TTL for new tokens has changed over time; some users report 30/60/90-day defaults landing on accounts that previously had no expiry. **The expiration choice must be re-verified at every rotation.**
- Railway's [Jan 28–29 2026 incident report](https://blog.railway.com/p/incident-report-january-26-2026) discusses account/auth issues but is not directly relevant to TTL changes.

---

### 4. GitHub does not allow PAT rotation automation (analogous constraint)

**Source**: [Rotate Personal Access Tokens — community/discussions/24366](https://github.com/orgs/community/discussions/24366)
**Authority**: GitHub Community discussion, GitHub Docs on PAT policy
**Relevant to**: Whether we can ever automate Railway token rotation from inside CI. Confirms the constraint in `CLAUDE.md` ("Agents cannot rotate the Railway API token").

**Key information**:
- "There is no way to automate PAT rotation, as a PAT cannot manage PATs." The Railway model is similar — a token cannot mint a new token without an interactive auth step.
- Practical mitigation is **maximizing token lifetime** (no-expiry account/workspace token) plus **calendar reminders / scheduled cleanup agents**, not automation of the rotation itself.

---

### 5. Recommended Railway token type for CI/CD (2026)

**Source**: [Using Github Actions with Railway (Railway Blog)](https://blog.railway.com/p/github-actions), [GitHub Actions PR Environment guide](https://docs.railway.com/guides/github-actions-pr-environment)
**Authority**: Official Railway blog and docs
**Relevant to**: Future-proofing the rotation runbook.

**Key information**:
- Railway's blog tutorial creates a **project token** in `Project Settings → Tokens` and stores it as a repo secret.
- For deployments scoped to one service in one project (which matches our staging deploy), a **project token** is the recommended minimum-privilege choice.
- However, project tokens use `Project-Access-Token: <token>` as the request header — *not* `Authorization: Bearer`. Our `staging-pipeline.yml` uses `Authorization: ***`. If we switch to a project token, the validation curl (and any downstream Railway API call) must change headers.

---

## Code Examples

The current validation step (from the failed run log):

```bash
# From .github/workflows/staging-pipeline.yml (Validate Railway secrets step)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: ***" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  exit 1
fi
```

If the rotator switches to a workspace token (the current Railway-recommended path for CI on the `Authorization: Bearer` header), the URL must also be corrected:

```bash
# Suggested change — from [docs.railway.com/integrations/api](https://docs.railway.com/integrations/api)
curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}'
```

If the rotator switches to a **project token** (the model the Railway blog tutorial uses), the validation query must change because project tokens cannot answer `me`:

```bash
# Project tokens use a different header and cannot run `me { id }`.
curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

---

## Gaps and Conflicts

- **Conflict**: The repo runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` directs the human to `https://railway.com/account/tokens` (account-token page), but Railway's Help Station says `RAILWAY_TOKEN` env var only accepts **project tokens**. The runbook may be the *source* of the recurrence — every rotation creates an account token at the account page, which Railway then rejects with "Not Authorized".
- **Gap**: Could not confirm from web sources whether the *literal* dashboard UI in 2026 still defaults to a short TTL on account-token creation; the runbook claim ("default may be 1 day or 7 days") is plausible but not corroborated by current Railway docs.
- **Gap**: Could not find any Railway-side tooling for *programmatic* token rotation. This confirms `CLAUDE.md` policy that agents cannot rotate.
- **Outdated risk**: The repo runbook is named `..._742.md` and references prior incidents #733, #739 — it has not been updated despite ~60 subsequent recurrences. Strong signal it is no longer load-bearing.

---

## Recommendations

Based on the research, the agent picking up #912 should **not attempt rotation** (per `CLAUDE.md`). Instead, file a precise issue / mail to mayor that gives the human enough information to break the recurrence loop:

1. **Tell the human to create a workspace (team) token, not an account token.** Workspace tokens are Railway's current recommended type for shared CI/CD on the `Authorization: Bearer` header, are scoped (least privilege vs account), and answer the `me { id }` validation query our workflow uses. Project tokens would also work but require workflow changes (different header + different validation query).
2. **Tell the human to fix the endpoint host to `.com`.** `https://backboard.railway.app/graphql/v2` is undocumented; `https://backboard.railway.com/graphql/v2` is canonical. This is a separate fix from rotation and could be done in a code PR.
3. **Tell the human to explicitly select "No expiration"** in the token-creation modal. The runbook already says this; the 63-incident streak suggests it is being missed in practice.
4. **Schedule a one-time cleanup agent** (`/schedule`) in ~14 days to verify the rotation held (no new `RAILWAY_TOKEN is invalid or expired` issues since #912). If a 64th recurrence appears, the workspace-token theory is wrong and we need to escalate to Railway support.
5. **Do not** create another `.github/RAILWAY_TOKEN_ROTATION_*.md` file. The repo already has `docs/RAILWAY_TOKEN_ROTATION_742.md`; adding more rotation docs is the Category 1 error called out in `CLAUDE.md`.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs | https://docs.railway.com/integrations/api | Canonical endpoint URL, token-type matrix |
| 2 | Railway Login & Tokens docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTLs, refresh-token model |
| 3 | Railway Help Station — "RAILWAY_TOKEN invalid or expired" | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Establishes that token-type mismatch surfaces same error string as expiry |
| 4 | Railway Help Station — "Token for GitHub Action" | https://station.railway.com/questions/token-for-git-hub-action-53342720 | RAILWAY_TOKEN vs RAILWAY_API_TOKEN distinction |
| 5 | Railway Help Station — "GraphQL Not Authorized for PAT" | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | `.app` vs `.com` endpoint switch |
| 6 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Project-token-based GitHub Actions tutorial |
| 7 | Railway docs — GitHub Actions PR Environment | https://docs.railway.com/guides/github-actions-pr-environment | Reference flow for token in repo secrets |
| 8 | GitHub community — Rotate PATs discussion #24366 | https://github.com/orgs/community/discussions/24366 | Confirms general "tokens can't mint tokens" constraint, validates CLAUDE.md policy |
| 9 | Railway Incident Report — Jan 28–29, 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Background on recent Railway auth incidents (not the cause here) |
| 10 | Existing repo runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Current rotation procedure (should be updated per Recommendation #1) |
