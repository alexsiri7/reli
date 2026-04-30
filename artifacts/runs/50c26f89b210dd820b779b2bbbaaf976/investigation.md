# Investigation: Main CI red — Deploy to staging (16th `RAILWAY_TOKEN` expiration)

**Issue**: #785 (https://github.com/alexsiri7/reli/issues/785)
**Type**: BUG
**Investigated**: 2026-04-30T11:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The `Validate Railway secrets` pre-flight at `.github/workflows/staging-pipeline.yml:32-58` is still aborting every prod deploy on `main` — `25161929515` (11:04:46Z, the run #785 cites) and the immediately-adjacent `25161923407` (11:04:37Z, same SHA `d21b401d`) both failed with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Nothing ships until a human rotates the GitHub Actions secret. |
| Complexity | LOW | No code change is permitted (per `CLAUDE.md` § "Railway Token Rotation"); the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md` and the action is one Railway dashboard rotation + one `gh secret set`. |
| Confidence | HIGH | The run cited by #785 ([`25161929515`](https://github.com/alexsiri7/reli/actions/runs/25161929515)) emits the canonical error string at `2026-04-30T11:04:52Z`; an immediately-adjacent run [`25161923407`](https://github.com/alexsiri7/reli/actions/runs/25161923407) at 11:04:37Z on the same SHA `d21b401d` (the merge commit of #781's investigation PR #782) failed identically. #781 closed at 11:00:15Z and #783 closed at 11:00:14Z; #785 was filed at 11:30:28Z — ~30 minutes after both prior siblings closed cleanly, proving the secret was not rotated in that window. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight step in `.github/workflows/staging-pipeline.yml` calls Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, and aborts the deploy.

This is the **16th identical recurrence** of the same failure mode. Issue #781 (14th) closed at 2026-04-30T11:00:15Z; issue #783 (15th) closed at 11:00:14Z; the auto-pickup cron filed #785 at 11:30:28Z against run `25161929515` on SHA `d21b401d` (the merge commit of #781's investigation PR #782). The secret is still bad, exactly as expected — rotation is a human-only action per `CLAUDE.md`.

---

## Analysis

### Root Cause / Change Rationale

This is a **process / human-action defect**, not a code defect. The workflow is failing closed exactly as designed (`.github/workflows/staging-pipeline.yml:32-58`), and editing it to mask the failure would itself be a defect. Per `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
>
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

### Evidence Chain

WHY: run `25161929515` (cited by #785) failed
↓ BECAUSE: the `Validate Railway secrets` job step exited 1
  Evidence: `.github/workflows/staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then … exit 1; fi`

↓ BECAUSE: Railway returned `Not Authorized` to the `{me{id}}` GraphQL probe
  Evidence: CI log line `2026-04-30T11:04:52.3402629Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: `secrets.RAILWAY_TOKEN` is still expired even after investigation PRs #780 (#779), #782 (#781), and #784 (#783) merged at ~10:00Z, ~11:00Z, and ~11:00Z respectively
  Evidence: adjacent run `25161923407` at 11:04:37Z on the *same* SHA `d21b401d` (merge of #782, the investigation for #781) failed identically — `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`. The rotation cannot happen on a PR merge — only via railway.com.

↓ ROOT CAUSE: prior rotations created Railway tokens with a finite TTL instead of selecting **No expiration**, *or* the token created was a workspace token that is rejected by the `{me{id}}` probe (see `web-research.md` § Findings 1-2 in this run dir). The auto-pickup cron has now produced **16 occurrences across 15 unique issues** (`#733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #774 → #777 → #779 → #781 → #783 → #785`). No human has yet performed the rotation that resolves the current expiry window.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/50c26f89b210dd820b779b2bbbaaf976/investigation.md` | NEW | CREATE | This investigation artifact (lineage update + human-action checklist) |
| `artifacts/runs/50c26f89b210dd820b779b2bbbaaf976/web-research.md` | NEW (carried forward from `alexsiri7` workspace) | CREATE | Pre-existing web-research artifact summarising Railway token taxonomy / TTL findings as of 2026-04-30 |

**Deliberately not changed** (per `CLAUDE.md`):
- `.github/workflows/staging-pipeline.yml` — failing closed correctly; editing it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is correct.
- No `.github/RAILWAY_TOKEN_ROTATION_*.md` will be created — Category 1 error.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step using `{me{id}}` probe.
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` (`serviceInstanceUpdate` + `serviceInstanceDeploy` mutations), would also fail without rotation.
- `.github/workflows/railway-token-health.yml` — independent health-check workflow that the operator uses to verify the new secret before re-running deploys.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook referenced from `CLAUDE.md`.

### Git History

- **Issue-cited failure**: run `25161929515` at 2026-04-30T11:04:46Z on SHA `d21b401d` (merge commit of investigation PR #782 for issue #781).
- **Subsequent / adjacent failure proving secret is still bad**: run `25161923407` at 2026-04-30T11:04:37Z, 9 seconds earlier, on the same SHA `d21b401d`. Two pipeline runs on the same merge commit failing identically rules out any "transient probe / network blip" hypothesis.
- **Issue #781 timing**: closed at 2026-04-30T11:00:15Z. **Issue #783 timing**: closed at 2026-04-30T11:00:14Z (one second apart, both archon:done). #785 was filed at 11:30:28Z — ~30 minutes after both prior siblings transitioned to `archon:done`. This is the same auto-pickup-cron loop deferred-follow-up #1 in PRs #780, #782, and #784 already call out, **now occurring even after #781 *and* #783 closed cleanly**.
- **Prior occurrences (canonical chain)**: per the lineage table below, this is the 16th.

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
| 12 | #777 | #778 | |
| 13 | #779 | #780 | |
| 14 | #781 | #782 | |
| 15 | #783 | #784 | |
| 16 | **#785** | **(this PR)** | Auto-pickup cron re-fired against `25161929515` *after* both #781 and #783 closed cleanly within 1 second of each other, confirming the cron continues to fire on every red `staging-pipeline` run regardless of how many sibling investigations have just closed. |

---

## Implementation Plan

### Step 1 (Human) — Mint a new Railway Workspace token with No expiration

**Where**: https://railway.com/account/tokens
**Action**: Create a new **Workspace** token, **Expiration: No expiration**. Suggested name: `github-actions-permanent`.

Rationale:
- `staging-pipeline.yml:50` uses `Authorization: Bearer $RAILWAY_TOKEN` — the workspace contract. Project tokens require the `Project-Access-Token` header and would still fail the `{me{id}}` probe (see `web-research.md` § Finding 1).
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
# Re-run the issue-cited failure plus the adjacent one:
gh run rerun 25161929515 --repo alexsiri7/reli --failed
gh run rerun 25161923407 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 3
# Expect: conclusion: success on all
```

---

### Step 5 (Either) — Close the issue and clear the label

Close #785 with a comment linking the green run, then remove the `archon:in-progress` label so the auto-pickup cron stops re-firing.

---

## Patterns to Follow

**This investigation mirrors PR #784 (issue #783), PR #782 (issue #781), and PR #780 (issue #779) exactly** — same lineage table format, same human-action checklist, same scope-boundary discipline. No code or workflow changes; the canonical runbook is reused.

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
| Fresh Workspace token still returns `Not Authorized` | Per this run's `web-research.md` § Finding 2, the `{me{id}}` probe specifically requires an *account* (personal) token; a workspace token will be rejected by validation even if it would deploy successfully. If rotation lands and the probe still fails, switch the dashboard creation to "no workspace selected" (account token) or change the validation query in a separate bead. |
| Sibling "Main CI red" / "Prod deploy failed on main" issue filed in the next cron window | Close it alongside #785 and remove `archon:in-progress` on both. |
| New deploys file additional sister issues before rotation lands | Expected; the auto-pickup cron will keep firing until `RAILWAY_TOKEN` is rotated. The 30-minute gap between #781/#783 closing and #785 filing is itself an instance of this — the loop-stopper is a deferred follow-up (below). |
| Agents create a `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming success | Category 1 error per `CLAUDE.md` — explicitly forbidden. This investigation does not do that. |

---

## Validation

### Automated Checks

```bash
# Health-check the new secret (after human rotation):
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1   # expect: success

# Re-run the failed deploys:
gh run rerun 25161929515 --repo alexsiri7/reli --failed
gh run rerun 25161923407 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 3       # expect: success on all
```

### Manual Verification

1. Confirm the new token shows **No expiration** in https://railway.com/account/tokens.
2. Confirm `https://reli.interstellarai.net` returns 200 after the deploy.
3. Confirm #785 is closed and the `archon:in-progress` label is removed.

---

## Scope Boundaries

**IN SCOPE**:
- This investigation artifact + the GitHub comment posted to #785.
- Updating the lineage table to reflect the 16th recurrence.

**OUT OF SCOPE (do not touch)**:
- `.github/workflows/staging-pipeline.yml` — the `Validate Railway secrets` step is correct (failing closed); editing it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is already correct.
- The pre-existing `web-research.md` in this run dir — it was generated earlier in the workflow and is canonical for this run; this investigation does not duplicate or rewrite it.
- Any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — Category 1 error per `CLAUDE.md`.
- The actual token rotation — agent-out-of-scope per `CLAUDE.md`.

**Deferred follow-ups** (file by a human after #785 closes and rotation is verified):

1. **Investigation-only loop-stopper for `archon:in-progress`** (P0, escalated again from P0 — now 16 recurrences) — the auto-pickup cron has now produced 16 occurrences across 15 unique issues on the same expired secret because no PR ever lands on no-op investigations. Issue #785 was filed ~30 minutes after both #781 and #783 closed cleanly (within 1 second of each other), proving the cron now fires on every red `staging-pipeline` run regardless of whether *multiple* sibling investigation issues have just closed. The cron should suppress re-firing while *any* `Prod deploy failed on main` / `Main CI red` issue exists for an unrotated secret (e.g. gate on a successful `railway-token-health` run rather than just on the absence of an open `archon:in-progress` sibling).
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — service-account token or scheduled-rotation automation. Railway has no OIDC trust feature as of April 2026 (see `web-research.md` § Finding 3).
3. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against future `.app` retirement.
4. **Rename secret `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI conventions now treat `RAILWAY_TOKEN` as project-only; renaming the secret avoids the ambiguity that triggered finding 1 in PR #768's `web-research.md`.
5. **Reconcile with `web-research.md` Recommendation 2** (P2, follow-up only) — if the operator opts to migrate from account-scoped to workspace tokens, the validation query in `.github/workflows/staging-pipeline.yml:42` will need to change from `{me{id}}` (account-only per Railway moderator, `web-research.md` § Finding 2) to `{__typename}` (works for both). This is **explicitly out of scope for this bead** and any future bead — it must wait until rotation has landed and the operator decides token-type migration is desired; doing it while the current secret is expired would mask the real failure signal.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T11:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/50c26f89b210dd820b779b2bbbaaf976/investigation.md`
- **Workflow run id**: `50c26f89b210dd820b779b2bbbaaf976`
