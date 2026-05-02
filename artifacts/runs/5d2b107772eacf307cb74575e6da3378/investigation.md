# Investigation: Prod deploy failed on main (#858)

**Issue**: #858 (https://github.com/alexsiri7/reli/issues/858)
**Type**: BUG
**Investigated**: 2026-05-02

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | Prod deploy pipeline is fully blocked — no path to ship code to staging/production until the token is rotated; this is an authentication outage, not a code defect. |
| Complexity | LOW | Recovery is a 3-step manual rotation in the Railway UI + GitHub Actions secret update — zero source files change, the bug is exclusively in external secret state. |
| Confidence | HIGH | Failed step's stderr (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) is unambiguous, and this is the 40th occurrence of the identical pattern with a documented runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`). |

---

## Problem Statement

The `Validate Railway secrets` step in the staging deploy job (workflow `Staging → Production Pipeline`, run [25241673721](https://github.com/alexsiri7/reli/actions/runs/25241673721)) failed because the Railway GraphQL API rejected `RAILWAY_TOKEN` with `Not Authorized` when probing `{ me { id } }`. Because this validation gates the actual `serviceInstanceUpdate` deploy mutation, no staging/prod release can land until the GitHub Actions secret is rotated.

---

## Analysis

### Root Cause / Change Rationale

The token stored in the GitHub Actions secret `RAILWAY_TOKEN` is no longer accepted by Railway's GraphQL endpoint. The workflow's pre-flight authentication probe (lines 49–58 of `.github/workflows/staging-pipeline.yml`) correctly catches this and refuses to proceed, which is the intended fail-fast behaviour — there is no code regression here.

### Evidence Chain

WHY: Why did the prod deploy run fail?
↓ BECAUSE: Job `Deploy to staging` exited 1 in the `Validate Railway secrets` step.
  Evidence: workflow log — `##[error]Process completed with exit code 1.`

↓ BECAUSE: Why did that step exit 1?
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` (workflow log line at 02:34:53.0417012Z)

↓ BECAUSE: Why was the token rejected?
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` posts `{me{id}}` to `https://backboard.railway.app/graphql/v2` with `Authorization: Bearer $RAILWAY_TOKEN` and inspects `.data.me.id`. Railway returned `errors[0].message == "Not Authorized"` instead of a `me.id`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an account-scoped Railway API token that has been revoked or has expired.
  Evidence: Identical failure mode to closed issues #742, #747, #751, #755, #762, #769, #774, #777, #779, #783, #785, #786, #789, #790, #793, #794, #798, #801, #804, #805, #808, #810, #811, #814, #816, #818, #820, #821, #824, #825, #828, #829, #832, #833, #836, #841, #843, #845, #847, #850, #854 — all resolved by rotating the token via `docs/RAILWAY_TOKEN_ROTATION_742.md` with no source change. This is the 40th occurrence.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none — code) | — | — | No source/workflow change is required or appropriate. |
| GitHub secret `RAILWAY_TOKEN` | n/a | ROTATE (human) | Replace with a freshly-issued account-scoped Railway API token. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the failing pre-flight)
- `.github/workflows/staging-pipeline.yml:60-78` — `Deploy staging image to Railway` step (gated by the validate step; would fail equivalently if reached)
- `.github/workflows/railway-token-health.yml` — independent token-health probe; will also fail on the same secret
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the rotation runbook (canonical procedure)

### Git History

- **Failing commit**: `55a7ac0` ("docs: investigation for #850 (38th RAILWAY_TOKEN expiration, 5th pickup) (#856)") — docs-only, cannot have caused this
- **Pre-flight probe added**: tracked back via `git log --oneline .github/workflows/staging-pipeline.yml` — well-established pattern long before this run
- **Implication**: Not a regression. This is recurring secret-rotation toil; the token issued during the previous rotation has now been revoked/expired again.

---

## Implementation Plan

> **Agent-side: NO CODE CHANGES.** Per `CLAUDE.md` § "Railway Token Rotation":
>
> > Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. File a GitHub issue or send mail to mayor with the error details. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
>
> Producing such a marker file would be a Category 1 error.

### Step 1: Document the failure (agent action)

**File**: `artifacts/runs/5d2b107772eacf307cb74575e6da3378/investigation.md`
**Action**: CREATE (this file)

Captures the failing run URL, the exact error string, the rotation runbook pointer, and the prior-occurrence count so the human has a one-stop summary.

### Step 2: Post investigation comment on #858 (agent action)

Use `gh issue comment 858` with the formatted summary so the human can act without opening Actions logs.

### Step 3: Human rotation per runbook (NOT an agent action)

Per `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Sign in at https://railway.com/account/tokens.
2. Create a new **account-scoped** API token (label e.g. `gh-actions-2026-05-02`).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions with the new value.
4. Re-run the failed pipeline: `gh run rerun 25241673721 --repo alexsiri7/reli --failed`.
5. Confirm the `Validate Railway secrets` step passes; close #858 with the green run URL.
6. (Optional but useful) Revoke the previous token in Railway after the new one verifies green, to limit overlap.

### Step 4: Verify (after human rotation)

- `Validate Railway secrets` step succeeds (`me.id` returned).
- `Deploy staging image to Railway` proceeds and `serviceInstanceUpdate` returns no `errors`.
- Health check on `RAILWAY_STAGING_URL` reports 200.
- `railway-token-health.yml` next scheduled run is green.

---

## Patterns to Follow

This issue's documentation pattern mirrors the prior 39 instances. Reference the most recent pair (issue #854, PR #857) for the docs-only investigation pattern.

The runbook itself (`docs/RAILWAY_TOKEN_ROTATION_742.md`) is the canonical procedure — do not duplicate or fork it.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires #858 before rotation completes | Issue is labelled `archon:in-progress`; the pickup cron skips while that label is present. Do not strip the label until the deploy goes green. |
| Cron re-fires #858 after PR merges (label cleared early) | Prior issues (#854) saw this; harmless but wasteful. Out of scope for this fix — track separately if it recurs. |
| Token rotates but workflow still fails | Likely a separate issue (e.g., revoked service ID). Re-investigate from logs; do **not** assume same root cause. |
| New Railway UI lacks "No expiration" option | Capture the rotation flow in screenshots and update `docs/RAILWAY_TOKEN_ROTATION_742.md` if instructions drift. |
| Human believes agent rotated the token because of a `.github/RAILWAY_TOKEN_ROTATION_*.md` file | Do **not** create such a file. The runbook is the only canonical rotation doc. |

---

## Validation

### Automated Checks

```bash
# Agent-side: docs-only diff. Standard suite is vacuously passing.
# The actual signal lives in the deploy pipeline, which only goes green
# AFTER the human rotates the token:
gh run rerun 25241673721 --repo alexsiri7/reli --failed
gh run watch <new-run-id> --repo alexsiri7/reli
```

### Manual Verification (post-rotation)

1. The re-run of [25241673721](https://github.com/alexsiri7/reli/actions/runs/25241673721) reaches the `Deploy staging image to Railway` step and exits 0.
2. `RAILWAY_STAGING_URL` returns the freshly-deployed SHA (`55a7ac0`) on `/api/version` (or equivalent health endpoint).
3. `railway-token-health.yml` next scheduled run reports green.

---

## Scope Boundaries

**IN SCOPE (agent):**
- Investigate the failed run, identify the recurring root cause.
- Produce this investigation artifact under `artifacts/runs/5d2b107772eacf307cb74575e6da3378/`.
- Post a summary comment on issue #858 directing the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**OUT OF SCOPE (do not touch):**
- Rotating the Railway API token (human-only — railway.com access required).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` "rotation done" marker (Category 1 error per `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml`, `railway-token-health.yml`, or `docs/RAILWAY_TOKEN_ROTATION_742.md` — none are wrong; the secret is.
- Any unrelated cleanup (Polecat scope discipline).
- Designing token-expiration mitigations (longer-lived tokens, automatic rotation, alerting earlier than CI failure) — file separate issues if pursued.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/5d2b107772eacf307cb74575e6da3378/investigation.md`
- **Failing run**: https://github.com/alexsiri7/reli/actions/runs/25241673721
- **Prior occurrences**: 39 (this is #40)
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md`
