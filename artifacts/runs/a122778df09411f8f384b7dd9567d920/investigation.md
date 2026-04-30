# Investigation: Main CI red — Deploy to staging (#766)

**Issue**: #766 (https://github.com/alexsiri7/reli/issues/766)
**Type**: BUG
**Investigated**: 2026-04-30T07:30:00Z
**Workflow ID**: a122778df09411f8f384b7dd9567d920

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Every push to `main` since 2026-04-27 fails at the `Validate Railway secrets` pre-flight gate; the 5 most recent `staging-pipeline.yml` runs (`25148434478`, `25145158555`, `25142788611`, `25126991550`, `25028112865`) are all `conclusion: failure`, and the daily `railway-token-health.yml` probe has been red for the last two runs (`25105119767` 2026-04-29, `25049349913` 2026-04-28). Nothing can ship to staging until the secret is rotated. |
| Complexity | LOW | No application or workflow YAML change is needed. The fix is a single GitHub Actions secret rotation following `docs/RAILWAY_TOKEN_ROTATION_742.md`. The only wrinkle is that the action requires a human with Railway dashboard access — agents cannot perform it (CLAUDE.md § "Railway Token Rotation"). |
| Confidence | HIGH | The pre-flight at `.github/workflows/staging-pipeline.yml:49-58` emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized` only when Railway's `me{id}` GraphQL probe rejects the bearer token. Run `25148434478` (the SHA cited in the issue, `7433450`) shows that exact error. The independent daily health probe reports the same failure, confirming the secret value itself — not workflow plumbing — is the cause. This is the **7th identical recurrence** (#727 → #733 → #739 → #742 → #755 → #762 → #751 → #766); pattern, mechanism, and fix are all known. |

---

## Problem Statement

Issue #766 was filed by `pipeline-health-cron.sh` on 2026-04-30T05:30 UTC after `staging-pipeline.yml` run [25148434478](https://github.com/alexsiri7/reli/actions/runs/25148434478) on commit `7433450` failed at the `Validate Railway secrets` pre-flight step with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. The `RAILWAY_TOKEN` GitHub Actions secret is expired again.

This is the **7th identical recurrence** of the same root cause. Sister issue #751 (PR #765, merged 2026-04-30 06:00 UTC) and #762 (PR #764, merged 2026-04-30 03:00 UTC) committed docs-only investigations against the same expired token but the secret has not yet been rotated; #766 was auto-filed against the next failing run after those merges. Every staging-pipeline run on `main` since 2026-04-27 has failed at the same step, and the daily Railway token health probe has been red since 2026-04-28.

**No code change is possible** — agents cannot rotate the token (CLAUDE.md § "Railway Token Rotation"). The deliverable is this investigation artifact; resolution requires a human to rotate the token via the existing runbook with **No expiration** explicitly selected and the **Account Token** type (NOT a Workspace token — see "Patterns to Follow" below for why the prior #762 investigation got this wrong).

---

## Analysis

### 3.0 First-Principles — Primitive Audit

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Railway pre-flight gate (`me{id}` probe) | `.github/workflows/staging-pipeline.yml:32-58` | **Yes** | Working exactly as designed — fails fast with a human-readable message when the token is invalid. No edits warranted. |
| Daily token health probe | `.github/workflows/railway-token-health.yml` | **Yes** | Already red on 2026-04-28 and 2026-04-29 — the early-warning signal fired correctly; the rotation simply has not been performed. PR #757 increased cadence from weekly to daily; further frequency increases would not help. |
| `RAILWAY_TOKEN` secret value (the actual bit that's broken) | GitHub Actions repo secret — **not in repo** | **No** | Token reached its expiry date. Repeatedly created with default finite TTL instead of "No expiration"; that is the recurrence engine. |
| Rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | **Yes** | Already documents the cause ("the default TTL may be short … The new token must be created with **No expiration**") and the procedure. |
| Agent-side guardrail against false rotation docs | `CLAUDE.md` § "Railway Token Rotation" | **Yes** | Explicit prohibition on creating `.github/RAILWAY_TOKEN_ROTATION_*.md` files claiming completion (Category 1 error). PRs #749, #750 violated this and were removed in commits `459f790` (PR #756) and `9b9ef96` (PR #754). |
| Prior #762 investigation's token-type guidance | `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md:86` | **No** | Recommends a Workspace token; web research (see `web-research.md` Finding #1) confirms `me{id}` only works with Account Tokens. Out of scope to fix inline (Polecat) — flagged to mayor. |

**Minimal change for #766:** commit this investigation artifact as the linkable docs file so Archon can transition the issue out of `archon:in-progress`. Do not edit `.github/`, do not edit `backend/`, do not create any rotation-completion document.

### 3.1 Root Cause — 5 Whys

```
WHY 1: Why was #766 filed?
↓ BECAUSE: pipeline-health-cron.sh detected staging-pipeline.yml run
   25148434478 with conclusion=failure and auto-filed.
   Evidence: issue body — "Run: https://github.com/alexsiri7/reli/actions/runs/25148434478
   ... Failed jobs: Deploy to staging"

WHY 2: Why did run 25148434478 fail?
↓ BECAUSE: The Deploy to staging job exited 1 at step
   `Validate Railway secrets` with `RAILWAY_TOKEN is invalid or expired:
   Not Authorized`.
   Evidence: `gh run view 25148434478 --log-failed` line:
   "##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized"

WHY 3: Why did the validate step fail?
↓ BECAUSE: The Railway GraphQL `me{id}` probe returned no `data.me.id`,
   causing the pre-flight bash to print the canonical error and exit 1.
   Evidence: `.github/workflows/staging-pipeline.yml:49-58` —
       RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
         -H "Authorization: Bearer $RAILWAY_TOKEN" ...)
       if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
         echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
         exit 1

WHY 4: Why did Railway reject the token?
↓ BECAUSE: The bearer in `secrets.RAILWAY_TOKEN` has reached its
   expiration date. Independent corroboration: the daily token-health
   probe (`railway-token-health.yml`) is also failing on 2026-04-28 and
   2026-04-29, so the failure is in the secret value, not the
   workflow's deploy plumbing.
   Evidence:
     gh run list --workflow railway-token-health.yml --limit 5
       → 25105119767 (Apr 29) failure, 25049349913 (Apr 28) failure.

WHY 5: Why has the token expired again?
↓ ROOT CAUSE: Previous rotations (issues #733, #739, #742, #755, #762,
   #751) created Railway tokens with the dashboard's default finite TTL
   instead of explicitly selecting "No expiration". Each token then
   expires within a few weeks, and the next deploy attempt re-trips
   the pre-flight gate.
   Evidence:
     - docs/RAILWAY_TOKEN_ROTATION_742.md:18-21 — "the default TTL
       may be short … The new token must be created with
       **No expiration**."
     - Recurrence cadence: #727 (Apr 27 09:00), #733 (Apr 27 10:00),
       #739 (Apr 27 18:30), #742 (Apr 27 19:30), #747 (Apr 27 20:30),
       #751 (Apr 27 21:30), #755 (Apr 29 18:00), #762 (Apr 29 19:00),
       #766 (Apr 30 05:30). Hourly bursts on Apr 27 are the same monitor
       refiring; the Apr 29–30 issues are the *next* token expiry.
```

### Evidence Chain (terse)

WHY: `staging-pipeline.yml` run 25148434478 fails at `Validate Railway secrets`
↓ BECAUSE: Railway `me{id}` GraphQL probe returns `Not Authorized`
  Evidence: `gh run view 25148434478 --log-failed` →
  `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ BECAUSE: bearer token in `secrets.RAILWAY_TOKEN` is past its expiration
  Evidence: independent `railway-token-health.yml` runs `25105119767`,
  `25049349913` show identical failure on the same secret.
↓ ROOT CAUSE: prior rotations accepted the dashboard's default finite TTL
  instead of selecting "No expiration"
  Evidence: `docs/RAILWAY_TOKEN_ROTATION_742.md:18-21`; recurrence cadence
  #727 → #733 → #739 → #742 → #755 → #762 → #751 → #766.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/a122778df09411f8f384b7dd9567d920/investigation.md` | NEW | CREATE | This artifact. Documents that #766 is the same root cause as #762/#751 and that the fix is a human secret rotation. |
| `artifacts/runs/a122778df09411f8f384b7dd9567d920/web-research.md` | NEW | CREATE | Companion web research (already produced earlier in this run). Confirms Account-Token (not Workspace-Token) is required for the `me{id}` probe. |
| **GitHub Actions secret `RAILWAY_TOKEN`** | n/a | **HUMAN ROTATE** | The actual fix. Not an in-repo edit — performed via `gh secret set` after minting a new Account Token at https://railway.com/account/tokens with **No expiration**. |
| `.github/workflows/staging-pipeline.yml` | 32-58 | **DO NOT EDIT** | Workflow is correct. Listed here to make scope explicit. |
| `.github/workflows/railway-token-health.yml` | n/a | **DO NOT EDIT** | Already daily after PR #757; correctly red. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | n/a | **DO NOT EDIT** | Runbook is current and correct on actions to take. Cosmetic "third occurrence" wording is out of scope. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — the `Validate Railway secrets` step that currently fails.
- `.github/workflows/staging-pipeline.yml:60-78` — the `Deploy staging image to Railway` step; would also fail with the same token, but never executes because the pre-flight gates first.
- `.github/workflows/railway-token-health.yml` — independent daily probe, currently red.
- GitHub Actions repo-level secret `RAILWAY_TOKEN` — the only piece of state that needs to change.
- Railway dashboard at https://railway.com/account/tokens — where the new token must be minted (account-level page; **not** a project-settings page).

### Git History

- `docs/RAILWAY_TOKEN_ROTATION_742.md` — added during incident #742; covers exactly this rotation procedure.
- `bdc2651` (Apr 27) — `add weekly Railway token health check to prevent recurring deploy failures (#753)` (originally weekly).
- `6a0d232` (Apr 28) — `ci: run Railway token health check daily instead of weekly (#757)` — increased probe cadence in response to recurrences.
- `459f790` / `9b9ef96` (Apr 27) — removals of false rotation-completion docs (per CLAUDE.md prohibition; Category 1 errors from PRs #749, #750).
- `eb6a432` (Apr 30) — `docs: add investigation for issue #755 (#761)`.
- `1b9c246` (Apr 30) — `docs: investigation for issue #762 (5th RAILWAY_TOKEN expiration) (#764)`.
- `7433450` (Apr 30 06:00 UTC) — `docs: investigation for issue #751 (6th RAILWAY_TOKEN expiration) (#765)` — the SHA cited in #766; this commit is the head of `main` against which run `25148434478` failed.
- **Implication**: The repository's instrumentation is doing exactly what it was designed to do — the daily probe is alerting, the pre-flight gate is failing fast, the runbook exists, and prior false-rotation docs have been removed. The recurring failure mode is a process gap (rotators accepting the default TTL), not a regression.

---

## Implementation Plan

> ⚠️ **No code change is required.** Per `CLAUDE.md` § "Railway Token Rotation": "Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com." Creating a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done is a **Category 1 error**. The implementation plan below is a **human action checklist**, not an agent-executable plan. The agent's contribution is this investigation artifact and (optionally) the docs-only PR that commits it.

### Step 1: Mint a new Railway token (HUMAN)

**Where**: https://railway.com/account/tokens (account-level page — NOT a project's settings page).
**Action**: Create a new token with these settings:
- **Name**: `github-actions-permanent`
- **Expiration**: **No expiration** ← critical, do not accept the default TTL
- **Workspace**: **No workspace** (i.e., an **Account Token**, not a Workspace Token)

**Why**: The validate step at `staging-pipeline.yml:49-52` queries `{me{id}}` with `Authorization: Bearer $RAILWAY_TOKEN`. Per Railway's official API docs, `me` is account-scoped and **rejects Workspace and Project tokens**; only Account Tokens succeed. The prior #762 investigation recommended a Workspace token — this would fail the validate step even with a brand-new, non-expired token. See `web-research.md` Finding #1 for the citation. "No expiration" is what prevents the next recurrence.

---

### Step 2: Update the GitHub Actions secret (HUMAN)

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted
```

**Why**: This is the secret read by both `staging-pipeline.yml` and `railway-token-health.yml`. Same procedure as documented in `docs/RAILWAY_TOKEN_ROTATION_742.md:28-32`.

---

### Step 3: Verify rotation worked (EITHER agent or human)

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
# Wait ~30s, then:
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1 \
  --json conclusion
```

**Pass criterion**: `conclusion: success`. If still `failure`, the new token did not propagate or was minted with the wrong type — return to Step 1 and confirm "No workspace" / Account Token was selected.

---

### Step 4: Unblock the failed deploy (EITHER)

```bash
# Rerun the most recent failed staging-pipeline run:
gh run list --repo alexsiri7/reli --workflow staging-pipeline.yml --status failure \
  --limit 1 --json databaseId --jq '.[0].databaseId' \
  | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
```

**Pass criterion**: Run completes with `conclusion: success`. Production deploy then proceeds.

---

### Step 5: Close the duplicate issues (EITHER)

Close **#766, #762, and #751** with a comment linking to the green run. All three have the same root cause and the same fix; whichever staging-pipeline run goes green confirms all three.

---

### Step N: No tests to add

No code is changing in this repo, so no test updates apply. The `railway-token-health.yml` daily cron probe **is** the regression test for this class of failure; it is already in place and is what surfaced the current expiration before users noticed.

---

## Patterns to Follow

**Sibling investigations that already merged — mirror their structure exactly:**

```
PR #765 (merged 2026-04-30) — `docs: investigation for issue #751 (6th RAILWAY_TOKEN expiration)`
  Files: artifacts/runs/47dca44a7406f7256132e238201e7927/investigation.md
  Body declares: Fixes #751
```

```
PR #764 (merged 2026-04-30) — `docs: investigation for issue #762 (5th RAILWAY_TOKEN expiration)`
  Files: artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/{investigation.md,web-research.md}
  Body declares: Part of #762
```

```
PR #761 (merged 2026-04-29) — `docs: add investigation for issue #755`
  Files: artifacts/runs/f1aad5a4c565a621f7bd50a32068e729/investigation.md
  Body declares: Fixes #755
```

This PR follows the same shape: a single investigation artifact in `artifacts/runs/a122778df09411f8f384b7dd9567d920/`, no `.github/` or `backend/` edits, body declaring `Fixes #766`.

**From the existing runbook — quote directly into PR/comment text:**

```markdown
# SOURCE: docs/RAILWAY_TOKEN_ROTATION_742.md:18-21
When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days).
Previous rotations may have used these defaults. **The new token must be created with
"No expiration".**
```

```bash
# SOURCE: docs/RAILWAY_TOKEN_ROTATION_742.md:28-32
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted
```

**From CLAUDE.md — what NOT to do:**

> Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> File a GitHub issue or send mail to mayor with the error details.
> Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.

PRs #749 and #750 violated this; their files were removed in commits `459f790` and `9b9ef96`. Do not repeat that mistake.

**Correction to the prior #762 investigation (Polecat: flag, do not fix inline):**

The investigation at `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md:86` recommends a Workspace token. That is incompatible with the `{me{id}}` payload at `staging-pipeline.yml:49-52` — `me` is account-scoped and only Account Tokens populate it. If the rotator follows the #762 doc verbatim they will mint a token that *also* trips `Not Authorized`. This investigation supersedes that guidance for #766; a separate cleanup of the #762 artifact should be routed to mayor rather than rolled into this incident.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Rotator picks the wrong token type (Workspace or Project) | Step 3 (`railway-token-health.yml` rerun) fails fast — `me{id}` only succeeds with Account Tokens. Step 1 explicitly says "No workspace" / Account Token. |
| Rotator follows the #762 investigation's "Workspace token" guidance | Explicitly called out in Step 1 and "Patterns to Follow" above. The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md:24-26`) correctly says "Account Token" by directing the rotator to `https://railway.com/account/tokens`, not a project page. |
| Rotator accepts default TTL again (8th recurrence) | Daily health probe (`railway-token-health.yml`) catches it ahead of the next deploy attempt. Step 1 makes "No expiration" the first checkbox. The recurrence cadence shows finite-TTL has been the failure mode every single time. |
| Agent attempts to "fix" the workflow file thinking the YAML is the problem | The workflow is correct — failure is in the secret value. No edits to `.github/workflows/*.yml` are warranted by this incident. |
| Agent creates `.github/RAILWAY_TOKEN_ROTATION_766.md` claiming rotation is done | **Category 1 error per CLAUDE.md.** PRs #749, #750 already did this for #748 and were removed. Do not repeat. The deliverable is `artifacts/runs/.../investigation.md`, not a rotation-completion doc. |
| Sister issues #751, #762 are missed when closing | Step 5 explicitly closes all three. |
| Failing run cited in #766 (`25148434478`) is hours old at fix-time | Step 4 uses `gh run list --status failure --limit 1` to grab the most recent failure rather than the stale ID. |
| `Fixes #766` auto-close does not fire | Step 5's explicit `gh issue close` is the belt-and-braces fallback. |
| Token leaks via accidental log of `$RAILWAY_TOKEN` | `staging-pipeline.yml:34, 54` only sends the token in headers; GitHub Actions auto-redacts known secret values from logs. No mitigation needed beyond not changing this. |
| Endpoint cutover (Railway retires `backboard.railway.app` in favour of `.com`) | Future risk; would produce identical failure shape from a different root cause. **Out of scope** for this incident; tracked in `web-research.md` Finding #4 for a separate follow-up. |
| Runbook drift (`docs/RAILWAY_TOKEN_ROTATION_742.md` says "third occurrence") | Cosmetic — the runbook is still correct on the actions to take. Out of scope for this fix. |

---

## Validation

### Automated Checks

```bash
# Verify the rotated token works against Railway:
gh workflow run railway-token-health.yml --repo alexsiri7/reli

# Verify the most-recent failed staging-pipeline run now passes:
gh run list --repo alexsiri7/reli --workflow staging-pipeline.yml --status failure \
  --limit 1 --json databaseId --jq '.[0].databaseId' \
  | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed

# Confirm both:
gh run list --repo alexsiri7/reli --workflow railway-token-health.yml --limit 1 \
  --json conclusion
gh run list --repo alexsiri7/reli --workflow staging-pipeline.yml --limit 1 \
  --json conclusion
```

Both must show `"conclusion":"success"`.

### Manual Verification

1. Visit https://railway.com/account/tokens and confirm the active token shows **No expiration** and **No workspace** (Account Token).
2. Confirm production deploy completed by checking the Railway dashboard for the new image rollout.
3. Confirm #766, #762, and #751 are all closed with a link to the green run.

---

## Scope Boundaries

**IN SCOPE:**

- This investigation artifact at `artifacts/runs/a122778df09411f8f384b7dd9567d920/investigation.md`.
- The companion `web-research.md` already produced in the same directory.
- A docs-only PR committing both files with body `Fixes #766` (mirrors PR #765 → #751, PR #764 → #762, PR #761 → #755).
- An investigation comment on issue #766 directing the human rotator to `docs/RAILWAY_TOKEN_ROTATION_742.md` and the "No expiration" / Account Token requirements.

**OUT OF SCOPE — DO NOT TOUCH:**

- Editing `.github/workflows/staging-pipeline.yml` — workflow is correct; failure is in the secret value, not the YAML.
- Editing `.github/workflows/railway-token-health.yml` — already at daily cadence after PR #757; further frequency increases would not help.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming completion — **CLAUDE.md Category 1 error**, identical to PRs #749/#750 that were reverted in `459f790`/`9b9ef96`.
- Editing the prior `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md` to remove its incorrect Workspace-token guidance — flag to mayor instead (Polecat).
- Switching `backboard.railway.app` → `backboard.railway.com` in workflow files — real future risk, but separate concern; file as follow-up.
- Migrating `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` env-var rename — cosmetic; works as-is.
- Implementing OIDC federation — Railway has not published OIDC support; not currently feasible.
- Two-secret rolling rotation pattern — overkill; daily probe already gives early warning.
- Refreshing `docs/RAILWAY_TOKEN_ROTATION_742.md` to say "seventh occurrence" — cosmetic; runbook actions remain correct.
- Any change to `backend/` or `frontend/`.
- Re-investigating sister issues #762, #751, #758, #759 — they have their own artifacts already in `main`.

If the implementing agent finds any of these tempting, **stop and mail mayor** instead of fixing inline — that is the entire point of CLAUDE.md Polecat Scope Discipline.

---

## Metadata

- **Investigated by**: Claude (claude-opus-4-7[1m])
- **Timestamp**: 2026-04-30T07:30:00Z
- **Workflow ID**: a122778df09411f8f384b7dd9567d920
- **Worktree branch**: `archon/task-archon-fix-github-issue-1777527029039`
- **Artifact**: `artifacts/runs/a122778df09411f8f384b7dd9567d920/investigation.md`
- **Companion**: `artifacts/runs/a122778df09411f8f384b7dd9567d920/web-research.md`
- **Sibling investigations**:
  - `artifacts/runs/47dca44a7406f7256132e238201e7927/investigation.md` (#751, merged via PR #765)
  - `artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md` (#762, merged via PR #764) — **note: contains incorrect Workspace-token guidance; superseded by this artifact**
  - `artifacts/runs/f1aad5a4c565a621f7bd50a32068e729/investigation.md` (#755, merged via PR #761)
