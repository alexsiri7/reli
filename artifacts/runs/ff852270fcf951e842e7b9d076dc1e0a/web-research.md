# Web Research: fix #901

**Researched**: 2026-05-02T16:00:00Z
**Workflow ID**: ff852270fcf951e842e7b9d076dc1e0a
**Issue**: alexsiri7/reli#901 — "Main CI red: Deploy to staging" (RAILWAY_TOKEN is invalid or expired: Not Authorized)

---

## Summary

This is the 59th recurring `RAILWAY_TOKEN` expiration in alexsiri7/reli (the 19th today alone). The repo's CLAUDE.md is unambiguous: **agents cannot rotate the Railway API token** — that requires a human at https://railway.com/account/tokens. The standing remediation is to file an issue and point the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`. Web research surfaces one important *non-rotation* finding: the current workflow uses `Authorization: Bearer` against the Railway GraphQL API, which is the auth scheme for **account/workspace tokens** (set as `RAILWAY_API_TOKEN`), not for **project tokens** (which Railway's docs and community reserve for the env var name `RAILWAY_TOKEN` and which use the `Project-Access-Token` header). This naming/scheme mismatch may itself be a contributor to the chronic expiration cycle and is worth flagging — but per Polecat scope discipline, that change is **out of scope for this bead** and should be raised separately with mayor.

---

## Findings

### 1. Railway Token Types & Headers

**Source**: [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli)
**Authority**: Official Railway documentation
**Relevant to**: Why the token keeps "expiring" / failing auth even after rotation

**Key Information**:

- **Project Token**: Scoped to a single environment within a project. Set via `RAILWAY_TOKEN` env var. Used by the Railway CLI for project-level deploy actions.
- **Account Token / Workspace Token**: Broader scope, can authenticate "all CLI actions across all resources and workspaces." Set via `RAILWAY_API_TOKEN` env var.
- **Header difference (critical)**: Project tokens use the `Project-Access-Token` HTTP header. Account, workspace, and OAuth tokens use `Authorization: Bearer`.
- Railway recommends Project Tokens for most CI/CD deploys because they have minimum-necessary scope.

---

### 2. "RAILWAY_TOKEN invalid or expired" Root Cause (Community Q&A)

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Official Railway community help forum, with confirmed-working answer
**Relevant to**: Whether our recurring failure is *expiration* or a *token-type mismatch*

**Key Information**:

- Direct quote: *"RAILWAY_TOKEN now only accepts project token; if u put the normal account token… it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- Resolution recommended by the forum: create a **project token** (Project Settings → Tokens), not an account token, and assign it to `RAILWAY_TOKEN`.
- Conflicting tip in the same thread: if both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` are set, `RAILWAY_TOKEN` takes precedence — having both can mask the real failure.

**Caveat**: This is community guidance, not an SLA — and it specifically applies to the **Railway CLI**. Our workflow does not use the CLI; it calls the GraphQL API directly with `Authorization: Bearer $RAILWAY_TOKEN`, which is the *account-token* auth scheme. So the forum's "use a project token" advice does not transfer 1:1 — see the Conflicts section below.

---

### 3. Railway GraphQL API Authentication

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: What auth scheme `.github/workflows/staging-pipeline.yml` is actually using

**Key Information**:

- The Railway GraphQL endpoint at `https://backboard.railway.app/graphql/v2` accepts both account and project tokens, but with different headers.
- `{ me { id } }` (the query our workflow uses to *validate* the token at line 52 of `staging-pipeline.yml`) is an **account-scoped query**. A pure project token would not necessarily return a user from `me`.
- For an account token used over the GraphQL API, the canonical env-var name is `RAILWAY_API_TOKEN`.

---

### 4. OAuth Access-Token Expiration (NOT what we hit)

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Ruling out one "obvious" hypothesis

**Key Information**:

- OAuth **access tokens** expire after 1 hour; OAuth **refresh tokens** expire after 1 year.
- This is the OAuth flow only — it does **not** apply to manually-created project or account tokens from the dashboard, which is what GitHub Actions uses.
- So: our token is not expiring on a 1-hour OAuth clock. Either it has a TTL set at creation time, the workspace was rotated/revoked, or the wrong token *type* was used (see #2 above).

---

### 5. Existing Rotation Runbook

**Source**: `docs/RAILWAY_TOKEN_ROTATION_742.md` (in-repo)
**Authority**: Project's own runbook, established at issue #742
**Relevant to**: What the human should actually do

**Key Information**:

- Tells the operator to create a token at https://railway.com/account/tokens (account-tokens page) named `github-actions-permanent`, with **"No expiration"** selected.
- Then `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and re-run the failed workflow.
- The runbook itself notes: *"Previous rotations may have used these defaults. The new token must be created with 'No expiration'."*
- Recurrence count visible from `git log` is now ~59 — so either "No expiration" is not actually permanent, the option is being missed during rotation, or a second factor (token type / revocation) is causing this independent of TTL.

---

## Code Examples

The current validation snippet in `.github/workflows/staging-pipeline.yml:49-58` (for context, not for change in this bead):

```yaml
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

The `Authorization: Bearer` + `me{id}` combination is the **account-token** pattern per Railway docs ([Public API](https://docs.railway.com/integrations/api)).

---

## Gaps and Conflicts

- **Gap**: Railway docs do not publicly document the menu of TTL options ("No expiration", 1d, 7d, 30d, etc.) on the account-tokens page. The runbook claim that "No expiration" is available is uncorroborated by web sources reachable here. If the Railway UI silently changed (e.g., maximum TTL is now 90d on a Hobby plan), every "permanent" rotation would still expire — which would fit the observed recurrence pattern.
- **Conflict**: Community guidance ("use a project token, not an account token, with `RAILWAY_TOKEN`") collides with the workflow's actual usage (`Authorization: Bearer` + `me{id}` query, which require an *account* token). Following the community advice naively would break deploy in a different way.
- **Gap**: No public Railway statement was found about a token revocation/rotation event in May 2026 that would explain the 19-in-one-day clustering. The [Jan 2026 incident report](https://blog.railway.com/p/incident-report-january-26-2026) is unrelated. If Railway did mass-rotate, that should be visible on their status page or a follow-up post — could not confirm either way.
- **Gap**: Whether `RAILWAY_API_TOKEN` is also set as a GitHub secret (which would silently break things per #2) — not visible from web search; would need `gh secret list` to confirm. Out of scope for web research.

---

## Recommendations

Listed in increasing scope. **Only #1 is in scope for this bead** per CLAUDE.md and Polecat discipline.

1. **In scope — file the issue and stop.** The fix for #901 itself is for the human to follow `docs/RAILWAY_TOKEN_ROTATION_742.md`: create a new account token at https://railway.com/account/tokens with "No expiration", set it via `gh secret set RAILWAY_TOKEN`, and re-run the failed run (`gh run rerun 25252013103 --repo alexsiri7/reli --failed`). Per CLAUDE.md, the agent must NOT create a new `RAILWAY_TOKEN_ROTATION_*.md` claiming the rotation is done, and must NOT attempt the rotation itself (Category 1 error).

2. **Out of scope — escalate to mayor.** The 59-occurrence pattern strongly suggests root cause is *not* "operator forgets to pick No expiration." Two likelier candidates worth a separate bead:
   - **Verify the "No expiration" option still exists on the Railway account-tokens UI** (and screenshot it for the runbook). If Railway has imposed a maximum TTL, the current runbook is unactionable as written.
   - **Confirm token type matches header.** The workflow uses `Authorization: Bearer` + `{me{id}}`, which is the account-token pattern, but the secret is named `RAILWAY_TOKEN` (which the Railway CLI and community treat as project-token-only). Renaming the secret to `RAILWAY_API_TOKEN` would (a) make the intent self-documenting and (b) eliminate the risk that someone "rotates" by pasting in a project token (which would 401 immediately and look like expiration).
   - Both should be raised via `gt mail send mayor/ --subject "Railway token: investigate root cause of 59x expiration cycle"`.

3. **Out of scope — do not attempt.** Switching to a project token + `Project-Access-Token` header would require rewriting all GraphQL calls in the workflow to drop `me{id}` and use project-scoped queries instead. This is a non-trivial change and must come from a human-authored bead.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Using the CLI | https://docs.railway.com/guides/cli | Official: `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` semantics |
| 2 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Official: GraphQL auth headers per token type |
| 3 | Railway Docs — Login & Tokens (OAuth) | https://docs.railway.com/integrations/oauth/login-and-tokens | Rules out OAuth 1-hour expiration as the cause |
| 4 | Railway Docs — Troubleshooting | https://docs.railway.com/integrations/oauth/troubleshooting | Official troubleshooting for auth failures |
| 5 | Railway Docs — CLI Reference | https://docs.railway.com/cli | Confirms env-var-vs-token-type mapping |
| 6 | Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community: "RAILWAY_TOKEN only accepts project tokens" |
| 7 | Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Community CI/CD pattern |
| 8 | Help Station — Authentication not working with RAILWAY_TOKEN | https://station.railway.com/questions/authentication-not-working-with-railway-b3f522c7 | Common failure modes |
| 9 | Help Station — CLI throwing "Unauthorized" with RAILWAY_TOKEN | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Confirms "Unauthorized" is the standard error string |
| 10 | Help Station — RAILWAY_API_TOKEN not being respected | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Two-token precedence behavior |
| 11 | railwayapp/cli#699 | https://github.com/railwayapp/cli/issues/699 | Known auth failures on Linux runners |
| 12 | railwayapp/cli#425 | https://github.com/railwayapp/cli/issues/425 | "Not authorized" on `railway down` from Actions |
| 13 | Railway blog — Jan 28-29 2026 incident | https://blog.railway.com/p/incident-report-january-26-2026 | Ruled out as cause (different incident) |
| 14 | In-repo runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | The exact remediation steps for the human |
