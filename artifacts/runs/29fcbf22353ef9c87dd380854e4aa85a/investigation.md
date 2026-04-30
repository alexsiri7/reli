# Investigation: Prod deploy failed on main (12th `RAILWAY_TOKEN` expiration)

**Issue**: #777 (https://github.com/alexsiri7/reli/issues/777)
**Type**: BUG
**Investigated**: 2026-04-30T09:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The pre-flight `Validate Railway secrets` step at `.github/workflows/staging-pipeline.yml:32-58` aborts every staging+prod deploy on `main` — nothing ships until a human rotates the GitHub Actions secret. |
| Complexity | LOW | No code change is permitted; the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md` and the action is one Railway dashboard rotation + one `gh secret set`. |
| Confidence | HIGH | Run [`25155727395`](https://github.com/alexsiri7/reli/actions/runs/25155727395) on SHA `1346f34d` (merge of investigation PR #775) emits `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at 2026-04-30T08:35:07Z; the *next* run [`25156988688`](https://github.com/alexsiri7/reli/actions/runs/25156988688) at 2026-04-30T09:04:47Z on SHA `aa30a5a7` (merge of investigation PR #776 itself) also failed identically — proving conclusively that no rotation has occurred since #774 closed. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight step in `.github/workflows/staging-pipeline.yml` calls Railway's `me{id}` GraphQL probe, receives `Not Authorized`, and aborts the deploy.

This is the **12th identical recurrence** of the same failure mode. Investigation PRs #775 and #776 (for issues #773 and #774 respectively) merged within the last hour; the very next post-merge CI runs failed at the identical step, confirming that the secret has not been rotated — which is expected, because rotation is a human-only action per `CLAUDE.md`.

---

## Analysis

### Root Cause / Change Rationale

This is a **process / human-action defect**, not a code defect. The workflow is failing closed exactly as designed (`.github/workflows/staging-pipeline.yml:32-58`), and editing it to mask the failure would itself be a defect. Per `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
>
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

### Evidence Chain

WHY: run `25155727395` failed
↓ BECAUSE: the `Validate Railway secrets` job step exited 1
  Evidence: `.github/workflows/staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then … exit 1; fi`

↓ BECAUSE: Railway returned `Not Authorized` to the `me{id}` GraphQL probe
  Evidence: CI log line `2026-04-30T08:35:07.8615404Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: `secrets.RAILWAY_TOKEN` is still expired even after investigation PRs #775 and #776 merged at ~08:25Z and ~09:00Z respectively
  Evidence: identical failure on the *subsequent* run `25156988688` at 09:04:47Z on SHA `aa30a5a7` (merge of PR #776 itself); the rotation cannot happen on a PR merge — only via railway.com.

↓ ROOT CAUSE: prior rotations created Railway tokens with a finite TTL instead of selecting **No expiration**. The auto-pickup cron has now produced **12 occurrences across 11 unique issues** (`#733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #774 → #777`). No human has yet performed the rotation that resolves the current expiry window.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/29fcbf22353ef9c87dd380854e4aa85a/investigation.md` | NEW | CREATE | This investigation artifact (lineage update + human-action checklist) |

**Deliberately not changed** (per `CLAUDE.md`):
- `.github/workflows/staging-pipeline.yml` — failing closed correctly; editing it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is correct.
- No `.github/RAILWAY_TOKEN_ROTATION_*.md` will be created — Category 1 error.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step using `me{id}` probe.
- `.github/workflows/staging-pipeline.yml:60-80` — `Deploy staging image to Railway` (`serviceInstanceUpdate` mutation), would also fail without rotation.
- `.github/workflows/railway-token-health.yml` — independent health-check workflow that the operator uses to verify the new secret before re-running deploys.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook referenced from `CLAUDE.md`.

### Git History

- **Issue-cited failure**: run `25155727395` at 2026-04-30T08:35:03Z on SHA `1346f34d` (merge commit of investigation PR #775 for issue #773).
- **Subsequent failure proving secret is still bad**: run `25156988688` at 2026-04-30T09:04:47Z on SHA `aa30a5a7` (merge commit of investigation PR #776 for issue #774).
- **Prior occurrences (canonical chain)**: per the lineage table below, this is the 12th.

| # | Issue | Investigation PR | Notes |
|---|-------|------------------|-------|
| 1 | #733 | (fix-only) | |
| 2 | #739 | (fix-only) | |
| 3 | #742 | #743 | |
| 4 | #755 | #761 | |
| 5 | #762 | #764 | |
| 6 | #751 | #765 | |
| 7 | #766 | #767 | |
| 8 | #762 (re-fire) | #768 | |
| 9 | #769 | #770 | |
| 10 | #771 | #772 | |
| 11 | #774 | #776 | Sibling: #773 / PR #775 — same workflow run, different cron template. |
| 12 | **#777** | **(this PR)** | No sibling "Main CI red" issue filed in the same window as of 09:10Z. |

---

## Implementation Plan

### Step 1 (Human) — Mint a new Railway Workspace token with No expiration

**Where**: https://railway.com/account/tokens
**Action**: Create a new **Workspace** token, **Expiration: No expiration**. Suggested name: `github-actions-permanent`.

Rationale:
- `staging-pipeline.yml:50` uses `Authorization: Bearer $RAILWAY_TOKEN` — the workspace contract. Project tokens require the `Project-Access-Token` header and would still fail the `me{id}` probe.
- The recurrence-breaker is **No expiration**. If the dashboard does not offer that option, pick the longest TTL available, record the dropdown options as a comment on this issue, and a follow-up bead will amend `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**Why**: prior rotations were finite-TTL — that is what causes this exact issue every few hours/days.

---

### Step 2 (Human) — Update the GitHub Actions secret

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token value when prompted.
```

---

### Step 3 (Either) — Verify the new token

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1
# Expect: conclusion: success
```

---

### Step 4 (Either) — Unblock the failed deploys

```bash
# Re-run the issue-cited failure plus the subsequent one on aa30a5a:
gh run rerun 25155727395 --repo alexsiri7/reli --failed
gh run rerun 25156988688 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 2
# Expect: conclusion: success on both
```

---

### Step 5 (Either) — Close the issue and clear the label

Close #777 with a comment linking the green run, then remove the `archon:in-progress` label so the auto-pickup cron stops re-firing.

---

## Patterns to Follow

**This investigation mirrors PR #776 (issue #774) and PR #772 (issue #771) exactly** — same lineage table format, same human-action checklist, same scope-boundary discipline. No code or workflow changes; the canonical runbook is reused.

```yaml
# SOURCE: .github/workflows/staging-pipeline.yml:32-58
# This step is correct — it fails closed when the secret is bad.
# DO NOT EDIT it to "fix" the deploy; that would mask the real defect.
- name: Validate Railway secrets
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
    ...
  run: |
    ...
    RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
      -H "Authorization: Bearer $RAILWAY_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"query":"{me{id}}"}')
    if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
      MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
      echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
      ...
      exit 1
    fi
```

---

## Edge Cases & Risks

| Risk / Edge case | Mitigation |
|------------------|------------|
| Dashboard no longer offers "No expiration" | Pick the longest TTL, record options on issue, file a follow-up bead to amend `docs/RAILWAY_TOKEN_ROTATION_742.md`. |
| Fresh Workspace token still returns `Not Authorized` | Per PR #768's `web-research.md` Finding 1, Railway may have tightened `RAILWAY_TOKEN` to project-only — switch the workflow header to `Project-Access-Token` in a separate bead. |
| Sibling "Main CI red" issue filed in the next cron window | Close it alongside #777 and remove `archon:in-progress` on both. |
| New deploys file additional sister issues before rotation lands | Expected; the auto-pickup cron will keep firing until `RAILWAY_TOKEN` is rotated. The loop-stopper is a deferred follow-up (below). |
| Agents create a `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming success | Category 1 error per `CLAUDE.md` — explicitly forbidden. This investigation does not do that. |

---

## Validation

### Automated Checks

```bash
# Health-check the new secret (after human rotation):
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1   # expect: success

# Re-run the failed deploys:
gh run rerun 25155727395 --repo alexsiri7/reli --failed
gh run rerun 25156988688 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 2       # expect: success on both
```

### Manual Verification

1. Confirm the new token shows **No expiration** in https://railway.com/account/tokens.
2. Confirm `https://reli.interstellarai.net` returns 200 after the deploy.
3. Confirm #777 is closed and the `archon:in-progress` label is removed.

---

## Scope Boundaries

**IN SCOPE**:
- This investigation artifact + the GitHub comment posted to #777.
- Updating the lineage table to reflect the 12th recurrence.

**OUT OF SCOPE (do not touch)**:
- `.github/workflows/staging-pipeline.yml` — the `Validate Railway secrets` step is correct (failing closed); editing it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is already correct.
- A new `web-research.md` — the existing one in this run's directory plus the one in #762/#768's artifact still apply.
- Any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — Category 1 error per `CLAUDE.md`.
- The actual token rotation — agent-out-of-scope per `CLAUDE.md`.

**Deferred follow-ups** (file by a human after #777 closes and rotation is verified):

1. **Investigation-only loop-stopper for `archon:in-progress`** (P2) — the auto-pickup cron has produced 12 occurrences across 11 unique issues on the same expired secret because no PR ever lands on no-op investigations. The cron should suppress re-firing while a `RAILWAY_TOKEN` issue is open.
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — service-account token or scheduled-rotation automation. Railway has no OIDC trust feature as of April 2026.
3. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against future `.app` retirement.
4. **Rename secret `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI conventions now treat `RAILWAY_TOKEN` as project-only; renaming the secret avoids the ambiguity that triggered finding 1 in PR #768's `web-research.md`.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T09:10:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/29fcbf22353ef9c87dd380854e4aa85a/investigation.md`
- **Workflow run id**: `29fcbf22353ef9c87dd380854e4aa85a`
