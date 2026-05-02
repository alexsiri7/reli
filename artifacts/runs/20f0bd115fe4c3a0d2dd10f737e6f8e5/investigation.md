---
name: Investigation — Issue #903
description: 60th RAILWAY_TOKEN expiration (~20th today, 2026-05-02). Validator at .github/workflows/staging-pipeline.yml:49-58 rejects token; per CLAUDE.md only a human can rotate.
type: project
---

# Investigation: Main CI red: Deploy to staging (60th RAILWAY_TOKEN expiration)

**Issue**: #903 (https://github.com/alexsiri7/reli/issues/903)
**Type**: BUG (infra/secret expiry — not a code defect)
**Investigated**: 2026-05-02T16:35:00Z
**Workflow ID**: 20f0bd115fe4c3a0d2dd10f737e6f8e5

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging deploys are blocked on every push to `main`, but no production data is at risk and a documented manual rotation path exists for the human admin (`docs/RAILWAY_TOKEN_ROTATION_742.md`); not CRITICAL because the failure is gated at the validation step before any deploy mutation runs. |
| Complexity | LOW | Zero code changes are in the agent's scope — the only valid agent actions are routing the human admin to the runbook and recording the investigation; the actual fix is a single dashboard action on railway.com performed by a human. |
| Confidence | HIGH | The failed-step log is unambiguous (`RAILWAY_TOKEN is invalid or expired: Not Authorized`), the validator script that produced it is the exact one at `.github/workflows/staging-pipeline.yml:49-58`, and this is the 60th identical occurrence with the same evidence chain — there is no diagnostic uncertainty left. |

---

## Problem Statement

The `Deploy to staging` job in run [25255409159](https://github.com/alexsiri7/reli/actions/runs/25255409159) (SHA `86aca5c`) fails at the `Validate Railway secrets` step with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. The Railway GraphQL API rejects the bearer token stored in the `RAILWAY_TOKEN` GitHub Actions secret, so the workflow exits 1 before any deploy mutation runs. This is the **60th** recurrence of this exact failure mode and approximately the **20th** instance filed today (2026-05-02) — direct successor to #901 (PR #902), which was the 59th.

---

## Analysis

### Root Cause / Change Rationale

Railway has invalidated (or expired) the bearer token currently stored in the `RAILWAY_TOKEN` GitHub Actions secret. The workflow's validator step posts `{me{id}}` to `https://backboard.railway.app/graphql/v2` with `Authorization: Bearer $RAILWAY_TOKEN`; Railway responded with a structured `{"errors":[{"message":"Not Authorized"}]}` payload, the `jq -e '.data.me.id'` test failed, and the step exited 1. **No code, workflow, or runbook change can fix this** — the secret value held by GitHub Actions is the broken artifact, and rotating it requires dashboard access at https://railway.com/account/tokens, which only the human admin holds.

Per `CLAUDE.md` § "Railway Token Rotation":

> **Agents cannot rotate the Railway API token.** […] Creating documentation that claims success on an action you cannot perform is a Category 1 error.

So the agent's scope is strictly: file the issue / route the human, record the investigation, and **not** create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file or modify the runbook.

### Evidence Chain

WHY: `Deploy to staging` job failed in run 25255409159
↓ BECAUSE: the `Validate Railway secrets` step exited 1
  Evidence: failed-job log line `2026-05-02T15:34:37.3175772Z ##[error]Process completed with exit code 1.`

↓ BECAUSE: the validator's `jq -e '.data.me.id'` test failed because Railway returned `Not Authorized`
  Evidence: failed-job log line `2026-05-02T15:34:37.3162996Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: the bearer token submitted from the secret was rejected by the Railway GraphQL API
  Evidence: `.github/workflows/staging-pipeline.yml:49-52`
  ```
  RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
    -H "Authorization: Bearer $RAILWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{me{id}}"}')
  ```

↓ ROOT CAUSE: the secret value of `RAILWAY_TOKEN` (a GitHub Actions repo secret) is no longer accepted by Railway
  Evidence: identical failure mode in 59 prior occurrences (#742 → … → #898 → #901). The most recent predecessor PR #902 documented the same evidence chain at `artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/investigation.md`.

  Resolution requires a human to mint a new token at https://railway.com/account/tokens and update the GitHub Actions `RAILWAY_TOKEN` secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none — agent-side) | — | — | Polecat scope discipline: the failure is a secret-rotation problem, not a code defect. The only changes appropriate from the agent are the artifact files in `artifacts/runs/20f0bd115fe4c3a0d2dd10f737e6f8e5/`. |
| GitHub Actions secret `RAILWAY_TOKEN` | n/a | UPDATE (human-only) | Rotate per `docs/RAILWAY_TOKEN_ROTATION_742.md`; cannot be touched by an agent. |

**Files explicitly NOT changed (Category 1 guard):**
- `.github/RAILWAY_TOKEN_ROTATION_903.md` — must NOT be created (CLAUDE.md forbids documentation that claims rotation success on an action the agent cannot perform).
- `.github/workflows/staging-pipeline.yml` — unchanged. The validator is doing its job correctly; the token, not the workflow, is broken.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — unchanged. Updates to this runbook (e.g., re: the "No expiration" option flagged in the predecessor PR's web research) are out of scope for #903 and would be a separate bead routed via mail to mayor.
- `DEPLOYMENT_SECRETS.md` — unchanged.

### Integration Points

- `.github/workflows/staging-pipeline.yml:49-58` — the validator step that produced the error.
- `.github/workflows/staging-pipeline.yml:60-88` — the deploy mutations that would have run had the validator passed; they use the same `RAILWAY_TOKEN` and would also have failed.
- `.github/workflows/railway-token-health.yml` — a standalone health-check workflow the human admin can run after rotation to confirm the new token is accepted before re-running #903's failed run.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the rotation runbook.
- `pipeline-health-cron.sh` — the cron that auto-files these issues.

### Git History

- **Validator step introduced**: long-standing (well before #742). The current shape of the validator was already in place at the time of the very first rotation runbook.
- **Last modified**: `git log` on `.github/workflows/staging-pipeline.yml` shows no changes touching the validator block since the runbook was written.
- **Implication**: This is **not** a regression caused by recent code changes. It is a recurring infra issue — the secret value expires (or is invalidated) on Railway's side and the workflow correctly catches it.
- **Recent investigation precedents**:
  - 13bf51e — docs: investigation for issue #898 (58th, 18th today)
  - cce4362 — docs: investigation for issue #896 (57th, 17th today)
  - ed436e2 — docs: investigation for issue #889 (55th)
  - 1e48dc5 — docs: investigation for issue #894 (56th)
  - 86aca5c — docs: investigation for issue #901 (59th, 19th today)
  - **(this PR will be)** docs: investigation for issue #903 (60th, ~20th today)

---

## Implementation Plan

> **Scope reminder**: per `CLAUDE.md`, the agent's only valid output here is the routing comment on the issue + this investigation artifact. The implementation plan below is for the **human admin**, not the agent.

### Step 1 (agent): post a routing comment on #903

**File**: n/a (GitHub comment)
**Action**: POST

Comment body summarises the failure, identifies it as the 60th recurrence, and routes the human admin to `docs/RAILWAY_TOKEN_ROTATION_742.md`. (This is what `/investigate-issue` Phase 5 does — content templated below.)

**Why**: Visible signal on the issue that the agent has triaged it and identified the action owner.

---

### Step 2 (agent): commit this artifact + open the docs-only PR

**File**: `artifacts/runs/20f0bd115fe4c3a0d2dd10f737e6f8e5/investigation.md` (this file) plus the existing `web-research.md`.
**Action**: CREATE / COMMIT

Mirror the PR #902 shape: title `docs: investigation for issue #903 (60th RAILWAY_TOKEN expiration, ~20th today)`, body with `Fixes #903`, no source/workflow/runbook changes.

**Why**: Persists the audit trail (per the established pattern of one artifact bundle per occurrence) and fulfils the "file the issue / send mail to mayor" branch of the CLAUDE.md guidance with concrete written context for the human rotator.

---

### Step 3 (human admin, NOT agent): rotate `RAILWAY_TOKEN`

**File**: GitHub Actions repo secret + `https://railway.com/account/tokens`
**Action**: UPDATE (manual, dashboard-only)

Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`. Before doing so, the human admin should also read `artifacts/runs/20f0bd115fe4c3a0d2dd10f737e6f8e5/web-research.md` § Recommendations — predecessor research raises three open items (account-vs-project token type, the runbook's "No expiration" claim, and possible secret rename to `RAILWAY_API_TOKEN`) that are worth a dashboard verification on this rotation.

**Why**: The expired secret is the only thing actually broken; rotating it is the only thing that fixes #903.

---

### Step 4 (human admin, NOT agent): verify and close

**File**: n/a (CI re-run)
**Action**: VERIFY

```bash
# 1. Sanity-check the new token via the standalone health workflow
gh workflow run railway-token-health.yml --repo alexsiri7/reli

# 2. Re-run the failed staging deploy
gh run rerun 25255409159 --repo alexsiri7/reli --failed

# 3. Close the issue with the green run URL
gh issue close 903 --repo alexsiri7/reli --comment "Rotated and verified — run <new-run-url> green."
```

**Why**: Closes the loop and ensures `archon:in-progress` is cleared on a green signal, not on the docs PR alone.

---

### Step 5 (agent, optional): mail mayor about deeper hypotheses

**File**: n/a (Graphite mail)
**Action**: SEND

If predecessor mail to mayor about the account-token-vs-project-token mismatch hasn't already produced a separate bead, send a follow-up: 60 consecutive expirations is well past the threshold where it stops being plausible that the runbook's "No expiration" instruction is being followed end-to-end. Do **not** action it inside #903 — Polecat Scope Discipline.

**Why**: The bead pattern keeps the recurring symptom (this issue) and the deeper investigation (a separate bead) properly separated.

---

## Patterns to Follow

**Mirror PR #902 exactly** — same structure, same Polecat boundaries, same Category 1 guard:

- Three artifact files only: `investigation.md`, `web-research.md`, `implementation.md` (the latter two already exist or will be created by the implementation phase).
- PR title format: `docs: investigation for issue #903 (60th RAILWAY_TOKEN expiration, ~20th today)`.
- PR body uses the same "Changes" table, "Root Cause (surface)", "Deeper hypothesis (escalated, not actioned here)", and "Validation" sections as #902.
- PR body must include `Fixes #903`.
- No `.github/RAILWAY_TOKEN_ROTATION_903.md`, no edits to the workflow, runbook, or `DEPLOYMENT_SECRETS.md`.

Reference: PR #902 body and file list (already on disk at HEAD `86aca5c`):

```
artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/investigation.md     (+179)
artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/web-research.md      (+152)
artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/implementation.md    (+102)
```

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Agent is tempted to "fix" by editing the workflow (e.g., adding retries). | Out of scope — the API explicitly returned `Not Authorized`; retries on a rejected token will not help. Polecat-mail to mayor instead, do not change the workflow. |
| Agent is tempted to create `.github/RAILWAY_TOKEN_ROTATION_903.md` mirroring the runbook to "show progress". | Forbidden by CLAUDE.md (Category 1 error). The investigation artifact under `artifacts/runs/.../` is the correct, allowed record. |
| Agent is tempted to amend `docs/RAILWAY_TOKEN_ROTATION_742.md` based on the web-research findings. | Out of scope for #903. The runbook update is itself a bead — route to mayor via mail, do not bundle. |
| Issue auto-pickup cron double-fires while the docs PR is open. | The issue is already labelled `archon:in-progress`; per its body the regular pickup cron will not double-fire. The docs PR's `Fixes #903` will close the issue once merged, preventing a third firing. (Note: merging the docs PR does not actually fix CI — only token rotation does. The human admin still needs to do Step 3 above. The issue may need to be reopened if rotation hasn't happened by merge time.) |
| The investigation artifact misstates the "Nth recurrence" or "Nth today" count. | Counts derived from: (a) predecessor PR #902 says #901 was "59th overall, 19th today, 2026-05-02"; (b) #903 is filed after #901 with no intervening RAILWAY rotation evidence, so it is the **60th overall** and approximately the **20th today** (#904 was filed at the same time but is a "Prod deploy failed" issue, likely a sibling symptom of the same broken secret). The "approximately" hedge guards against an off-by-one if a sibling RAILWAY-tagged issue was filed between #901 and #903 that I haven't accounted for. |
| Endpoint `backboard.railway.app` vs `backboard.railway.com`. | Web research confirms the `.app` host is still routing — the `Not Authorized` response proves the request reached Railway. Do not change the endpoint as part of this fix. |

---

## Validation

### Automated Checks

This is a docs-only artifact PR. Code-level checks are **N/A** — there are no source, workflow, or runbook edits to validate. The PR's own CI will exercise the unrelated `Deploy to staging` job again and is expected to fail at the **same** validator step until the human admin completes Step 3 above. That expected-failure is acceptable for the docs PR; merging the docs PR does not depend on staging being green (it cannot be, by design).

### Manual Verification

For the agent (after PR open):

1. Confirm only the three artifact files are staged in the PR (use `gh pr view <n> --json files`).
2. Confirm `.github/RAILWAY_TOKEN_ROTATION_903.md` does NOT exist (`ls .github/RAILWAY_TOKEN_ROTATION_*.md` should show only the legacy file from #742, if any).
3. Confirm `.github/workflows/staging-pipeline.yml`, `docs/RAILWAY_TOKEN_ROTATION_742.md`, and `DEPLOYMENT_SECRETS.md` are unmodified (`git diff main -- <path>` empty for each).
4. Confirm the PR body contains `Fixes #903`.

For the human admin (after Step 3 rotation):

1. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` returns green.
2. `gh run rerun 25255409159 --repo alexsiri7/reli --failed` — `Validate Railway secrets` passes; deploy proceeds; staging health check goes green.
3. `gh issue close 903` with the green run URL.

---

## Scope Boundaries

**IN SCOPE for the agent on #903:**
- Post a routing comment on issue #903 directing the human admin to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Create `artifacts/runs/20f0bd115fe4c3a0d2dd10f737e6f8e5/investigation.md` (this file).
- Open a docs-only PR titled `docs: investigation for issue #903 (60th RAILWAY_TOKEN expiration, ~20th today)` with `Fixes #903`, mirroring PR #902.
- (Optional) Send mail to mayor only if no follow-up bead has yet been opened on the deeper account-vs-project-token hypothesis from web research.

**OUT OF SCOPE — do not touch:**
- The `RAILWAY_TOKEN` GitHub Actions secret itself (agent has no access; only a human admin can rotate via railway.com).
- `.github/workflows/staging-pipeline.yml` (the validator is correct; the secret is the broken artifact).
- `.github/RAILWAY_TOKEN_ROTATION_903.md` — **must not be created** (CLAUDE.md Category 1 error).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` (runbook updates re: web-research findings are a separate bead).
- `DEPLOYMENT_SECRETS.md` (unchanged).
- Renaming the secret `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` (would require a coordinated workflow + secret update, separate bead).
- Switching to OAuth + refresh-token rotation (large refactor, separate bead).
- Endpoint change `backboard.railway.app` → `backboard.railway.com` (unrelated to the failure; out of scope).
- Closing or commenting on sibling issue #904 ("Prod deploy failed on main") even if it shares the same root cause — that's its own bead.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7)
- **Timestamp**: 2026-05-02T16:35:00Z
- **Workflow ID**: 20f0bd115fe4c3a0d2dd10f737e6f8e5
- **Artifact**: `artifacts/runs/20f0bd115fe4c3a0d2dd10f737e6f8e5/investigation.md`
- **Companion artifact**: `artifacts/runs/20f0bd115fe4c3a0d2dd10f737e6f8e5/web-research.md`
- **Source issue**: https://github.com/alexsiri7/reli/issues/903
- **Source run**: https://github.com/alexsiri7/reli/actions/runs/25255409159
- **Predecessor**: #901 / PR #902 / artifact `artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/` (59th occurrence)
