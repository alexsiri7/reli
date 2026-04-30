# Investigation: Main CI red — Deploy to staging (15th `RAILWAY_TOKEN` expiration)

**Issue**: #783 (https://github.com/alexsiri7/reli/issues/783)
**Type**: BUG
**Investigated**: 2026-04-30T10:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Every prod deploy on `main` is still aborting at the `Validate Railway secrets` pre-flight (`.github/workflows/staging-pipeline.yml:32-58`); the issue cites run `25159527419` (10:04:41Z, SHA `bb69f77a`) and the four prior consecutive runs all fail identically with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Nothing ships until a human rotates the GitHub Actions secret. |
| Complexity | LOW | No code change is permitted (per `CLAUDE.md` § "Railway Token Rotation"); the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md` and the action is one Railway dashboard rotation + one `gh secret set RAILWAY_TOKEN`. This artifact is docs-only. |
| Confidence | HIGH | The exact failing run (`25159527419`) emits the canonical error string at `2026-04-30T10:04:53Z`; the immediately preceding investigation (issue #781, PR #782, still open as of this write) already cited the same run as proof-of-no-rotation; staging-pipeline runs at 09:04Z, 09:34Z, 10:04Z (the cited one) and the on-merge `bb69f77` retry all fail identically. The token has not been rotated since the #779 chain closed. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight step in `.github/workflows/staging-pipeline.yml` calls Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, and aborts the deploy. The auto-pickup pipeline-health cron filed issue #783 against run `25159527419` (the same SHA `bb69f77a` post-merge run already cited inside the still-open #781/PR-#782 investigation).

This is the **15th identical recurrence** of the same failure mode, immediately following #781 (14th, `cd69933` on a sibling branch / PR #782 still open). No human rotation has occurred between #781's filing (10:00:28Z) and #783's filing (10:30:19Z), so the cron — which fires once per failed `staging-pipeline` run on `main` — produced a fresh issue on the next 30-minute tick.

---

## Analysis

### Root Cause / Change Rationale

This is a **process / human-action defect**, not a code defect. The workflow is failing closed exactly as designed (`.github/workflows/staging-pipeline.yml:32-58`), and editing it to mask the failure would itself be a defect. Per `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
>
> When CI fails with `RAILWAY_TOKEN is invalid or expired`:
> 1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> 2. File a GitHub issue or send mail to mayor with the error details.
> 3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.
>
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

### Evidence Chain

WHY: run `25159527419` (cited by #783) failed
↓ BECAUSE: the `Validate Railway secrets` job step exited 1
  Evidence: `.github/workflows/staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then … exit 1; fi`

↓ BECAUSE: Railway returned `Not Authorized` to the `{me{id}}` GraphQL probe
  Evidence: CI log line `2026-04-30T10:04:53.0762802Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: `secrets.RAILWAY_TOKEN` was not rotated between #779 closing (10:00:15Z) and the next staging-pipeline tick (10:04:41Z), nor between #781 filing (10:00:28Z) and #783 filing (10:30:19Z)
  Evidence: `gh run list --workflow=staging-pipeline.yml` shows five consecutive failures on `main` between 08:35Z and 10:04Z (run IDs `25155727395`, `25156988688`, `25158268693`, `25159527419`), all on the same expired token. PR #782 (the #781 investigation) is still open in `gh pr list --state open` at the time of this write — no rotation has occurred.

↓ ROOT CAUSE: prior rotations created Railway tokens with a finite TTL instead of selecting **No expiration**, *or* the token created was a workspace token that is rejected by the `{me{id}}` probe (see `web-research.md` from run `044b57b9ed7f700e576327fa9c5486cb` — same finding applies). The auto-pickup cron has now produced **15 occurrences across 14 unique issues**: `#733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #774 → #777 → #779 → #781 → #783`. No human has yet performed the rotation that resolves the current expiry window.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/83ece8bb0449966196bc4ab1064d4381/investigation.md` | NEW | CREATE | This investigation artifact (lineage update + human-action checklist) |

**Deliberately not changed** (per `CLAUDE.md`):
- `.github/workflows/staging-pipeline.yml` — failing closed correctly; editing it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is correct.
- No `.github/RAILWAY_TOKEN_ROTATION_*.md` will be created — Category 1 error.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step using the `{me{id}}` probe. This is the step emitting the error in run `25159527419`.
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` (`serviceInstanceUpdate` + `serviceInstanceDeploy` mutations). Would also fail without rotation; never reached because the pre-flight aborts first.
- `.github/workflows/railway-token-health.yml` — independent health-check workflow that the operator should use to verify the new secret before re-running deploys.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook referenced from `CLAUDE.md` § "Railway Token Rotation".

### Git History

- **Issue-cited failure**: run `25159527419` at 2026-04-30T10:04:41Z on SHA `bb69f77a` (merge commit of investigation PR #780, which closed #779). This is the *same* run already cited as a "subsequent failure proving the secret is still bad" inside the still-open #781 / PR #782 investigation.
- **Surrounding failures (same token, same root cause)**:
  - `25155727395` @ 08:35:03Z on `1346f34` (merge of PR #775, the 11th investigation)
  - `25156988688` @ 09:04:47Z on `aa30a5a` (merge of PR #776, the 11th re-investigation)
  - `25158268693` @ 09:34:59Z on `a020a354` (merge of PR #778, the 12th investigation, cited by #781)
  - `25159527419` @ 10:04:41Z on `bb69f77a` (merge of PR #780, the 13th investigation, cited by #783)
- **Issue timing**:
  - #781 filed at 10:00:28Z, 13s after #779 closed.
  - #783 filed at 10:30:19Z, ~30 min after #781 — exactly one staging-pipeline cron tick later, on the very next failed run on `main`.
- **Lineage table**:

| # | Issue | Investigation PR | Notes |
|---|-------|------------------|-------|
| 1 | #733 | (fix-only) | |
| 2 | #739 | (fix-only) | |
| 3 | #742 | #743 | first canonical runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) |
| 4 | #755 | #761 | |
| 5 | #762 | #765 | |
| 6 | #751 | #765 | |
| 7 | #766 | #767 | |
| 8 | #762 (re-fire) | #768 | |
| 9 | #769 | #770 | |
| 10 | #771 | #772 | |
| 11 | #773 / #774 | #775 / #776 | dual-fire (cron + manual) |
| 12 | #777 | #778 | |
| 13 | #779 | #780 (merged → SHA `bb69f77a`) | last merged investigation |
| 14 | #781 | #782 (open) | filed 10:00:28Z |
| **15** | **#783 (this)** | **TBD** | filed 10:30:19Z |

---

## Implementation Plan

This is a docs-only artifact. No code, workflow, or `.github/` changes are made.

### Step 1: Create this investigation artifact

**File**: `artifacts/runs/83ece8bb0449966196bc4ab1064d4381/investigation.md`
**Action**: CREATE

Records the 15th recurrence with the lineage chain so the next agent / operator can see at a glance that this is not a new defect and rotation is the only valid action.

---

### Step 2: Post a GitHub comment to issue #783

**Target**: https://github.com/alexsiri7/reli/issues/783
**Action**: `gh issue comment 783 --body "..."`

The comment summarises the assessment, lineage, and next-step (human rotation per `docs/RAILWAY_TOKEN_ROTATION_742.md`) so issue #783 can transition out of `archon:in-progress` while a human performs the rotation.

---

### Step 3 (operator, NOT this agent): Rotate the token

Per `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com → Account Settings → Tokens.
2. Revoke the current expired token.
3. Create a new **personal account token** (not a workspace token) with **No expiration**.
4. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli --body "<new-token>"`
5. Trigger `.github/workflows/railway-token-health.yml` via `workflow_dispatch` to confirm the new secret passes the `{me{id}}` probe.
6. Re-run the failed `staging-pipeline` run `25159527419` (or merge any green PR to `main`) to confirm deploys flow again.
7. Close #781 and #783 with a comment referencing the rotation timestamp.

This agent **must not** perform step 3.

---

## Patterns to Follow

The pattern is identical to the prior 14 recurrences. Key precedents:

- `cd69933` — "docs: investigation for issue #781 (14th RAILWAY_TOKEN expiration)" (sibling branch, PR #782).
- `bb69f77` — "docs: investigation for issue #779 (13th RAILWAY_TOKEN expiration) (#780)" (last merged).
- `a020a35` — "docs: investigation for issue #777 (12th RAILWAY_TOKEN expiration) (#778)".

All three are docs-only artifacts that update the lineage and direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`. None of them edit `.github/workflows/staging-pipeline.yml`, none of them create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Auto-pickup cron files a 16th issue (#785?) before rotation happens | Expected; identical artifact pattern applies. The cron is correct to keep filing while `main` deploys are red. |
| Operator rotates but pastes wrong token (e.g., workspace token, not personal) | `railway-token-health.yml` (`workflow_dispatch`) will surface this immediately before the next staging deploy. |
| Operator rotates but token has finite TTL again | Same problem will recur in N days. Runbook explicitly says **No expiration** at step 3. |
| Issue #781 / PR #782 lands first | No conflict — #783 is a strictly newer recurrence and its artifact lives in its own `runs/<id>/` directory. |
| An agent (mis)reads this and tries to "fix" the workflow | `Deliberately not changed` table above plus the explicit `CLAUDE.md` § "Railway Token Rotation" Category-1 warning prevent that. |

---

## Validation

### Automated Checks

```bash
# Confirm the workflow still fails closed exactly as expected (no edits made):
git diff --stat HEAD -- .github/workflows/staging-pipeline.yml   # → empty
git diff --stat HEAD -- docs/RAILWAY_TOKEN_ROTATION_742.md       # → empty

# Confirm the artifact was written:
ls -la artifacts/runs/83ece8bb0449966196bc4ab1064d4381/investigation.md
```

### Manual Verification (operator only, after rotation)

1. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` — must succeed (`me.id` returned).
2. `gh run rerun 25159527419 --repo alexsiri7/reli` — `Validate Railway secrets` must pass.
3. `gh issue close 783 --comment "Token rotated at <ISO timestamp>; staging-pipeline run <new-id> green."`
4. `gh issue close 781 --comment "Resolved by rotation closing #783."`

---

## Scope Boundaries

**IN SCOPE:**
- Create this investigation artifact at the path the harness pre-allocated.
- Post a GitHub comment on #783 with the assessment + next-step pointer.
- (If the orchestrator opens a PR) include `Fixes #783` in the PR body so the issue auto-closes when merged.

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — failing closed is correct.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is correct.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` — Category 1 error per `CLAUDE.md`.
- Performing the rotation itself — agent has no railway.com access.
- Closing #781 / #783 — that belongs to the operator after rotation.
- Editing the cron that filed #783 — the cron is correct to keep filing on red `main` deploys.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T10:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/83ece8bb0449966196bc4ab1064d4381/investigation.md`
- **Working directory**: `/home/asiri/.archon/workspaces/ext-fast/reli/worktrees/archon/task-archon-fix-github-issue-1777545021299`
- **Branch**: `archon/task-archon-fix-github-issue-1777545021299`
- **Lineage**: 15th `RAILWAY_TOKEN` expiration — `#733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #773 / #774 → #777 → #779 → #781 → #783`
