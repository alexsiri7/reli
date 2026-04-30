# Web Research: fix #762

**Researched**: 2026-04-30T07:05:00Z
**Workflow ID**: 0c44823de5470e5c9687e943e83f9414

---

## Summary

Issue #762 is the **8th recurrence** of the same root cause (lineage
`#733 → #739 → #742 → #755 → #762`, plus 3 internal re-fires of #762
itself = 8 total): the `RAILWAY_TOKEN` GitHub Actions secret has expired
and the staging-pipeline workflow's `Validate Railway secrets` step fails
with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Authoritative Railway sources (docs + community) confirm two
distinct failure modes for this exact error string — **token expiry** and
**token-type mismatch** (account vs project). Railway's public documentation
does **not** describe a "no expiration" option for project tokens, so the
runbook claim in `docs/RAILWAY_TOKEN_ROTATION_742.md` that this option exists
needs verification at the dashboard. Per repo policy (CLAUDE.md → "Railway
Token Rotation"), agents cannot rotate the token; this research informs the
human-facing instructions and any longer-term hardening.

---

## Findings

### 1. The exact error has two known causes (token expiry vs token-type mismatch)

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway's official community Q&A site, with answers from Railway
team / contributors.
**Relevant to**: Diagnosing why the token "expired" so quickly (5 times now).

**Key Information**:
- A user reported "RAILWAY_TOKEN environment variable is set but may be invalid
  or expired" *immediately* after creating a fresh token.
- Community fix: Railway changed `RAILWAY_TOKEN` to **only accept project
  tokens**. Account-settings tokens produce the "invalid or expired" message
  even when freshly minted.
- Direct quote: "RAILWAY_TOKEN now only accepts *project token*."
- Side note: "RAILWAY_TOKEN wins and screws everything up if it's wrong" — i.e.
  if both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` are set, the project-scoped
  one takes precedence and can mask an otherwise-working account token.

---

### 2. Railway's three token types and where each is created

**Source**: [Public API → Tokens | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation.
**Relevant to**: Confirming we are using the right token type for the
staging-pipeline workflow.

**Key Information**:
- **Project tokens** — "Scoped to a specific environment within a project and
  can only be used to authenticate requests to that environment." Created in
  **project settings → Tokens** (not account settings).
- **Workspace tokens** — Access all resources in a selected workspace. Created
  at <https://railway.com/account/tokens>.
- **Account tokens** — Broadest scope. Created at the same account/tokens page,
  with the Workspace field left blank.
- Auth headers differ:
  - Account/workspace/OAuth: `Authorization: Bearer <TOKEN>`
  - Project tokens: `Project-Access-Token: <TOKEN>`
- **Reli's workflow uses `Authorization: Bearer $RAILWAY_TOKEN`** in
  `.github/workflows/staging-pipeline.yml:50`, which corresponds to the
  account/workspace header — **not** the project-token header. This is a
  config mismatch worth flagging if the dashboard issues a project token.

---

### 3. GitHub Actions guidance: which env var to use

**Source A**: [Using Github Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions)
**Source B**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Source C**: [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli)

**Authority**: Railway's own blog plus official CLI docs and community Q&A.
**Relevant to**: Choosing between `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` for
this workflow.

**Key Information**:
- Railway's official blog post recommends **project tokens** for simple deploy
  workflows: "create a new project token on the Settings page of your project
  dashboard within the Tokens submenu," then expose it as `RAILWAY_TOKEN` in
  GitHub Actions.
- Railway CLI docs: "Set `RAILWAY_TOKEN` for project-level actions" /
  "Set `RAILWAY_API_TOKEN` for account-level actions."
- Community advice for **workspace-level operations** (e.g., creating PR
  preview environments, listing projects, `railway whoami`) requires an
  **account-scoped** token via `RAILWAY_API_TOKEN`. Project tokens cannot
  perform those operations.
- For Reli's deploy-and-poll-deployment-status pipeline (no PR-environment
  bootstrap), a project token via `RAILWAY_TOKEN` is the documented fit — but
  the workflow currently calls the GraphQL API with a `Bearer` header (see
  finding 2), which is the account-token contract.

---

### 4. Railway's published docs do NOT describe a "no expiration" option

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
+ [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation.
**Relevant to**: Validating the runbook claim in
`docs/RAILWAY_TOKEN_ROTATION_742.md` that operators should pick "No
expiration".

**Key Information**:
- The publicly-readable docs we fetched describe token *types* and *creation
  locations* but contain **no information about expiration policy, default
  TTL, or a "never expires" option** for any token class.
- Login & Tokens page (OAuth path) mentions OAuth access tokens expire in 1h
  and OAuth refresh tokens in 1y — but this is OAuth, not the dashboard
  project/account tokens used by GitHub Actions.
- **Gap**: We could not corroborate the existing runbook's claim that an
  operator can pick "No expiration" when creating a token. The dashboard UI
  may expose this option even though it's undocumented; the human rotating
  the token should confirm visually and report back so the runbook can be
  amended if false.

---

### 5. Industry best practice: rotate, scope, and automate

**Source A**: [Best Practices for Managing Secrets in GitHub Actions — Blacksmith](https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions)
**Source B**: [8 GitHub Actions Secrets Management Best Practices — StepSecurity](https://www.stepsecurity.io/blog/github-actions-secrets-management-best-practices)
**Source C**: [Automated secrets rotation with Doppler and GitHub Actions](https://www.doppler.com/blog/automated-secrets-rotation-with-doppler-and-github-actions)
**Source D**: [What's coming to our GitHub Actions 2026 security roadmap — GitHub Blog](https://github.blog/news-insights/product-news/whats-coming-to-our-github-actions-2026-security-roadmap/)

**Authority**: Multiple respected security/DevOps sources plus GitHub's own
roadmap.
**Relevant to**: Long-term fix to stop having this incident every few weeks.

**Key Information**:
- Recommended cadence: critical secrets every 30 days, high-risk every 60 days,
  others every 90 days. Reli has already rotated 8 times in recent history, so
  cadence is not the problem — *human availability* is. The recurrence rate is
  in fact higher than even the most aggressive industry guideline, which
  strengthens the case that manual rotation is the wrong primitive here.
- External secret managers (Doppler, HashiCorp Vault, Infisical) can inject
  rotated secrets into GitHub Actions at runtime, removing the need for a
  manual `gh secret set` step. Doppler integrates with Railway specifically
  ([Doppler Docs — Railway](https://docs.doppler.com/docs/railway)).
- GitHub's 2026 roadmap is introducing **scoped secrets** that bind credentials
  to explicit execution contexts — useful once available, but not actionable
  today.

---

### 6. Reli already has a token-health workflow — verify it's running

**Source**: Local repo file `.github/workflows/railway-token-health.yml`
(referenced by directory listing).
**Relevant to**: Why the token expiration was discovered by the prod-deploy
failure rather than a pre-emptive alarm.

**Key Information**:
- A workflow named `railway-token-health.yml` exists in the repo. If it is on
  a cron and posts to issues/Slack, it is the natural place to catch impending
  expiry **before** prod deploys break.
- Worth investigating in the implementation phase: is it scheduled? Does it
  test the same `Authorization: Bearer` call as `staging-pipeline.yml`? Does
  it open an issue when the token has < N days remaining (if Railway exposes
  `expiresAt` in its API)?

---

## Code Examples

The official Railway blog example for GitHub Actions deployment (closely
matches Reli's current shape):

```yaml
# From https://blog.railway.com/p/github-actions
jobs:
  deploy:
    runs-on: ubuntu-latest
    container: ghcr.io/railwayapp/cli:latest
    steps:
      - uses: actions/checkout@v3
      - run: railway up --service=${{ secrets.SVC_ID }}
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
```

Reli's workflow does **not** use the `railway` CLI — it calls GraphQL via
`curl` with `Authorization: Bearer $RAILWAY_TOKEN`. That's a valid alternative
for account/workspace tokens but not the documented contract for project
tokens (which use `Project-Access-Token: <TOKEN>`).

---

## Gaps and Conflicts

- **Token expiration policy is undocumented publicly.** Railway's official
  docs (`/integrations/api`, `/guides/cli`, blog) describe types and creation
  paths but never state a default TTL or whether "No expiration" is an
  available option in the dashboard UI. We cannot prove or disprove the
  runbook's "No expiration" instruction from public sources alone — only the
  human at the dashboard can verify.
- **Token-type guidance conflicts:** Railway's blog says "use a project token
  for GitHub Actions deploys" while the [Token for GitHub Action](https://station.railway.com/questions/token-for-git-hub-action-53342720)
  community thread leans toward `RAILWAY_API_TOKEN` (account-scoped) for
  workflows that do anything beyond a single-service `up`. Reli's workflow
  performs a few GraphQL calls (deployment trigger + status polling), so the
  "right" answer depends on whether project tokens can authenticate those
  exact GraphQL queries via `Authorization: Bearer` — not clear from docs.
- **Why does it keep expiring?** No source quantifies the default TTL.
  Possibilities, ranked by prior-art likelihood:
  1. The token is being created with a UI default TTL (7/30/90 days), not
     "No expiration" — could be a UI default that's easy to miss.
  2. Token type mismatch: an account-settings token is being pasted as
     `RAILWAY_TOKEN`, which Railway now rejects ("not authorized") regardless
     of TTL — this would *look* like expiry.
  3. Account password change or workspace permissions revocation invalidates
     existing tokens (mentioned in passing across multiple Help Station
     threads but never quantified).
- We did not find an authoritative API endpoint to query a token's
  `expiresAt` for proactive monitoring.

---

## Recommendations

1. **Do not attempt to rotate the token.** Per CLAUDE.md ("Railway Token
   Rotation"), creating a `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming
   success would be a Category 1 error. The investigation/handoff path is:
   send mail to mayor + point the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

2. **Have the human verify two things at the dashboard**, since both could
   explain the recurring expiry:
   - **Token type:** mint a **Workspace token** at
     <https://railway.com/account/tokens>. This is the canonical answer
     across `investigation.md` Step 1 and the PR body Human Action Checklist
     because `staging-pipeline.yml:50` uses the `Authorization: Bearer`
     header (Finding 2), which is the account/workspace contract — project
     tokens require the `Project-Access-Token` header and will fail the
     `me{id}` probe. Note the **known failure mode** in Finding 1: a Railway
     community thread reports that `RAILWAY_TOKEN` may have been tightened
     to project-only. If a fresh Workspace token still returns
     `Not Authorized`, the remediation is to switch the workflow header to
     `Project-Access-Token` in a separate bead — *not* to mint a project
     token against the current Bearer header.
   - **TTL setting:** confirm the dashboard exposes a "No expiration" option
     and that it is selected. If only fixed TTLs are offered (e.g., 7/30/90
     days), the runbook's instruction is wrong and the issue will recur on a
     schedule we can predict — that prediction belongs in the runbook.

3. **Consider auditing `railway-token-health.yml`** as a follow-up bead (out
   of scope for this fix per Polecat Scope Discipline — mail mayor instead of
   touching it). If it's not on a daily-or-tighter schedule, or if it doesn't
   exercise the same `Bearer` header path that `staging-pipeline.yml` uses,
   it can't pre-empt these failures.

4. **Long-term hardening (out of scope, mention to mayor):** integrate Doppler
   or Infisical to inject the Railway token into Actions at runtime so
   rotation doesn't require GitHub-secret edits. Doppler has a documented
   Railway integration. This converts the recurring incident from "human
   pages on cold expiry" to "automated rotate-and-publish."

5. **Follow-up issue (file after #762 closes, per `investigation.md` scope):**
   update `docs/RAILWAY_TOKEN_ROTATION_742.md` to:
   - Specify token-creation location (Workspace token from
     <https://railway.com/account/tokens> for the current `Bearer` header
     contract — see Finding 2 — pending dashboard verification by the human).
   - Note the two failure modes (TTL expiry vs type mismatch) and how to
     distinguish them from the error string alone (i.e., you can't — both say
     "Not Authorized").
   - Record whether a "No expiration" option actually exists, based on the
     human's observation during the next rotation.

   This recommendation is **out of scope for this PR** per
   `investigation.md` § "Scope Boundaries" (the canonical runbook is not
   touched by the investigation bead). It is enumerated here as a deferred
   follow-up to be filed once #762 closes, parallel to the items in
   `investigation.md` § "Suggested Follow-up Issues".

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Help Station — RAILWAY_TOKEN invalid or expired | <https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20> | Confirms `RAILWAY_TOKEN` only accepts project tokens; same error string covers two failure modes |
| 2 | Railway Docs — Public API / Tokens | <https://docs.railway.com/integrations/api> | Authoritative description of project vs workspace vs account tokens and their auth headers |
| 3 | Railway Docs — Using the CLI | <https://docs.railway.com/guides/cli> | Confirms `RAILWAY_TOKEN` (project) vs `RAILWAY_API_TOKEN` (account) split |
| 4 | Railway Blog — Using GitHub Actions with Railway | <https://blog.railway.com/p/github-actions> | Official deploy workflow recipe; recommends project tokens for simple deploys |
| 5 | Railway Help Station — Token for GitHub Action | <https://station.railway.com/questions/token-for-git-hub-action-53342720> | Counter-recommendation to use account tokens for workspace-level CI ops |
| 6 | Railway Help Station — RAILWAY_TOKEN not working on cli | <https://station.railway.com/questions/railway-token-not-working-a-c5805264> | Additional community confirmation of token-type sensitivity |
| 7 | Railway Docs — Login & Tokens (OAuth) | <https://docs.railway.com/integrations/oauth/login-and-tokens> | Documents OAuth TTLs (1h/1y) — *not* applicable to dashboard tokens but useful for ruling out |
| 8 | Blacksmith — Best Practices for Managing Secrets in GitHub Actions | <https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions> | Cadence guidance (30/60/90 days) |
| 9 | StepSecurity — 8 GitHub Actions Secrets Management Best Practices | <https://www.stepsecurity.io/blog/github-actions-secrets-management-best-practices> | Scoping, audit-log monitoring, rotation cadence |
| 10 | Doppler — Automated secrets rotation with Doppler and GitHub Actions | <https://www.doppler.com/blog/automated-secrets-rotation-with-doppler-and-github-actions> | Concrete automation path to remove the manual-rotation toil |
| 11 | Doppler Docs — Railway integration | <https://docs.doppler.com/docs/railway> | Confirms a Railway-specific Doppler integration exists |
| 12 | GitHub Blog — 2026 Actions security roadmap | <https://github.blog/news-insights/product-news/whats-coming-to-our-github-actions-2026-security-roadmap/> | Forward-looking: scoped secrets are coming |
