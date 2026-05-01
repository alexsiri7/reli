---
name: Web Research — fix #841 (2nd pickup)
description: 35th `RAILWAY_TOKEN` "Not Authorized" cycle; verifies prior research and adds late-breaking sources for the 2nd pickup of issue #841
type: project
---

# Web Research: fix #841 (2nd pickup)

**Researched**: 2026-05-01T15:05:00Z
**Workflow ID**: `cad662fda0d3b96c2e4bd299f4480e15`
**Issue**: #841 — "Prod deploy failed on main" (Railway staging deploy fails with `RAILWAY_TOKEN is invalid or expired: Not Authorized`)
**Pickup**: 2nd of #841 (35th overall recurrence; sibling #836 closed at 13:00:16Z, sibling #833 closed at 09:30:10Z)

---

## Summary

This is a 2nd pickup of #841 — the same root cause as the 1st pickup is still in effect: a single human action (rotate `RAILWAY_TOKEN`) is needed; the validator at `.github/workflows/staging-pipeline.yml:32-58` has continued to reject the secret on every push since 03:35Z. Re-running the targeted searches three hours later returns the **same authoritative explanations** (Project vs Account/Workspace token; Project-Access-Token vs Authorization: Bearer; workspace-blank requirement), with **four additional credible sources** found that were not cited in the 1st pickup's web-research.md: an official Railway **Incident Report (Jan 28-29, 2026)** confirming a recent GitHub OAuth rate-limit incident on Railway's side, an official **OAuth Troubleshooting** doc, a recent Help Station thread on `Project Token Not Found` errors in CI, and Railway's official **GitHub Actions PR Environment** guide naming `RAILWAY_API_TOKEN` (a stronger re-validation than the 1st pickup's `Deploying with the CLI` citation). None of the new sources change the recommendation; they reinforce it.

This artifact **builds on** the prior pickup's research (`artifacts/runs/8531a0fb983e22588f40e6f43484ee47/web-research.md`, 15 sources, authored 12:03Z), re-validates currency, and records the additional findings. Per polecat scope discipline, the structural fix has already been mailed-to-mayor in prior cycles — it is **not** re-mailed here.

---

## What Changed Since the 1st Pickup (Δ in 3 hours)

| Signal | 1st pickup (12:03Z) | 2nd pickup (15:05Z) | Delta |
|--------|---------------------|---------------------|-------|
| Sibling #833 | open | **CLOSED** at 09:30:10Z | already closed at 1st pickup |
| Sibling #836 | open | **CLOSED** at 13:00:16Z | newly closed (PR #840 merge) |
| Failed runs on `main` | 8 (since 03:35Z) | 9 (added run `25215295472` on SHA `c42a83b` at 13:04:42Z — the merge of PR #842, the 1st pickup) | +1 |
| `RAILWAY_TOKEN` rotated | no | no | unchanged — still expired/wrong-class |
| Web-research findings | 15 sources | 15 prior + 4 new (19 total) | +4 |
| Recommendation | rotate per runbook with caveats | unchanged | — |

---

## Findings (Δ Only)

The 12 prior findings remain accurate as of 15:05Z. Re-runs of the same three queries returned the same top sources verbatim; the Help Station threads cited in the 1st pickup are still live and unedited; the open upstream CLI bug `railwayapp/cli#699` is still open. The three new findings below were surfaced by today's broader searches.

### N1. Railway had a GitHub OAuth rate-limit incident in late January 2026

**Source**: [Incident Report: January 28-29, 2026 — Railway Blog](https://blog.railway.com/p/incident-report-january-26-2026)
**Authority**: Official Railway post-mortem
**Relevant to**: Provides background on a recent class of "auth feels broken" incidents on Railway's side
**Surfaced by**: WebSearch query `"RAILWAY_TOKEN \"invalid or expired\" GitHub Actions 2026"`

**Key Information**:

- Railway experienced **intermittent GitHub authentication failures** in late January 2026, traced to hitting GitHub's OAuth token rate limit. Users saw authentication-error symptoms during that window.
- This is **not** the cause of reli's current 35× recurrence (the symptom shape is different — reli's failure is at the validator step's `{me{id}}` probe, not at OAuth hand-off — and the incident dates pre-date the current cycle by ~3 months).
- **Useful for the runbook**: it documents that "Not Authorized" against Railway can have transient platform-side causes; future investigations should rule out a Railway status-page incident before assuming a token rotation is the only fix.

---

### N2. Official Railway OAuth Troubleshooting doc exists

**Source**: [Troubleshooting | Railway Docs](https://docs.railway.com/integrations/oauth/troubleshooting)
**Authority**: Official Railway documentation
**Relevant to**: A canonical landing page for Railway-side auth troubleshooting that the reli runbook does not currently link to
**Surfaced by**: WebSearch query `"RAILWAY_TOKEN \"invalid or expired\" GitHub Actions 2026"`

**Key Information**:

- Documents OAuth-side failure modes; complements the Login & Tokens page already cited in the 1st pickup.
- The reli rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) does not link to this page. **Suggested for the runbook update** that is already in mayor's queue.

---

### N3. "Project Token Not Found" thread — third distinct symptom shape in CI

**Source**: [Error: Project Token Not Found When Deploying with Railway CLI in GitHub Actions — Railway Help Station](https://station.railway.com/questions/error-project-token-not-found-when-dep-391b52a3)
**Authority**: Railway's official user forum
**Relevant to**: Documents a **third** failure-shape (`Project Token Not Found`) distinct from `invalid or expired` and `Not Authorized`
**Surfaced by**: WebSearch query `"RAILWAY_TOKEN \"invalid or expired\" GitHub Actions 2026"`

**Key Information**:

- Reinforces the prior pickup's central finding that token-type confusion is endemic to Railway's GitHub Actions story.
- The reli validator only emits one diagnostic (`RAILWAY_TOKEN is invalid or expired`), conflating at least three upstream failure shapes:
  1. Wrong token type (account token in `RAILWAY_TOKEN`)
  2. Wrong scope (workspace-scoped token; expected account-scoped)
  3. Genuine expiration / revocation
- **Useful for the validator-rewrite bead** that is already in mayor's queue: a clearer diagnostic would let humans skip straight to the right fix.

---

### N4. (Re-validation) GitHub Actions PR Environment — Railway Guides

**Source**: [GitHub Actions PR Environment | Railway Guides](https://docs.railway.com/guides/github-actions-pr-environment)
**Authority**: Official Railway documentation
**Relevant to**: Officially names `RAILWAY_API_TOKEN` and the workspace-blank requirement; **stronger** doc citation than the 1st pickup's `Deploying with the CLI` page
**Surfaced by**: WebSearch query `"Railway CLI RAILWAY_API_TOKEN account scoped token GitHub Actions"`

**Key Information**:

- Direct quote (paraphrased from search result): *"If you are using a project in a workspace, you need to ensure that the token specified is scoped to your account, not just the workspace."*
- Confirms (4 months later) that Railway's official guide for GitHub Actions still uses `RAILWAY_API_TOKEN` with an account-scoped token, **not** `RAILWAY_TOKEN`.
- Strengthens 1st-pickup recommendation #1 (env-var rename) — same conclusion, better citation.

---

## Code Examples

No new code samples surfaced beyond what the 1st pickup already documented. The wire-level header difference and the recommended GitHub Actions snippet remain authoritative; see `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/web-research.md` §"Code Examples".

---

## Gaps and Conflicts

- **Same gap as 1st pickup**: Railway's public docs still describe **no TTL** for Project / Account / Workspace tokens. The reli runbook's "1-day or 7-day default TTL" claim remains unverified. Repeated expirations are still more plausibly explained by token-type/scope mismatch than by an undocumented TTL.
- **No new conflicts** identified. The 1st pickup's gap analysis stands.
- **Currency check**: All Help Station threads cited by the 1st pickup are still live and not visibly edited. The upstream CLI bug `railwayapp/cli#699` is still open as of last fetch.

---

## Recommendations (Δ Only)

The 1st pickup's 6-item recommendation list stands without modification. **One small addition** for the runbook update bead in mayor's queue:

7. **Link `docs/RAILWAY_TOKEN_ROTATION_742.md` to the official [Railway OAuth Troubleshooting page](https://docs.railway.com/integrations/oauth/troubleshooting)** so future humans have one extra escalation path before pursuing a rotation.

The structural fix items (validator clarity, env-var rename, OIDC, scheduled validation cron) are **already in mayor's queue from prior cycles**. Per `CLAUDE.md > Polecat Scope Discipline`, this pickup does not re-mail them.

---

## Action for the Human (Unblock #841)

A single human action will close #841 — same as the 1st pickup, restated with current run/SHA:

```bash
# 1. (Pre-save verification) — must return non-null id
curl -sf -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer <NEW_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}' | jq '.data.me.id'

# 2. Save to GitHub Actions
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli  # paste the verified token

# 3. Re-run the latest failed deploy
gh run rerun 25215295472 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
```

> ⚠️ **Do NOT** create `.github/RAILWAY_TOKEN_ROTATION_841.md` — Category 1 error per `CLAUDE.md > Railway Token Rotation`.
> ⚠️ **Do NOT** select a workspace at `/account/tokens` — leave the Workspace field blank.

---

## Sources

The 15 sources from the 1st pickup remain canonical. Four new sources added below; new rows numbered 16-19.

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1-15 | (See `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/web-research.md` §Sources) | — | Carry-over from 1st pickup |
| 16 | Incident Report: January 28-29, 2026 — Railway Blog | https://blog.railway.com/p/incident-report-january-26-2026 | Documents a Railway-side OAuth rate-limit incident; rule out platform-side issues before rotating |
| 17 | Troubleshooting (OAuth) — Railway Docs | https://docs.railway.com/integrations/oauth/troubleshooting | Official auth-troubleshooting page; not currently linked from reli runbook |
| 18 | Project Token Not Found in GitHub Actions — Railway Help Station | https://station.railway.com/questions/error-project-token-not-found-when-dep-391b52a3 | Documents a 3rd CI failure shape; supports the validator-rewrite bead |
| 19 | GitHub Actions PR Environment — Railway Guides | https://docs.railway.com/guides/github-actions-pr-environment | Official guide naming `RAILWAY_API_TOKEN` + workspace-blank; stronger citation than the 1st pickup's `Deploying with the CLI` page |

---

*Researched by Claude (Opus 4.7, 1M context) • workflow `cad662fda0d3b96c2e4bd299f4480e15` • 2026-05-01T15:05:00Z*
