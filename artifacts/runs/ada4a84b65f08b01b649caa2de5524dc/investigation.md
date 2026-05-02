# Investigation: Prod deploy failed on `main` — RAILWAY_TOKEN expired (38th occurrence, 5th pickup)

**Issue**: #850 (https://github.com/alexsiri7/reli/issues/850)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-02T02:15:00Z
**Workflow**: ada4a84b65f08b01b649caa2de5524dc

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→production pipeline fully blocked at `Validate Railway secrets`; no code can ship until the token is rotated. Live app keeps serving traffic and there is no data loss, so not CRITICAL. |
| Complexity | LOW | Fix is a single GitHub Actions secret update by a human via railway.com — zero code, workflow, or runbook changes are needed; only complexity is the human handoff. |
| Confidence | HIGH | Latest failed run `25239867327` (2026-05-02T01:04:55Z) emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized` from `staging-pipeline.yml:55`, identical to the 37 prior occurrences. Five consecutive `staging-pipeline` runs (`25227458546`, `25229747557`, `25237747540`, `25238494833`, `25239867327`) and four consecutive scheduled `railway-token-health.yml` runs (2026-04-28 → 2026-05-01) all fail at the same probe. |

---

## Problem Statement

The staging pipeline has now failed five times in a row (`25227458546` → `25239867327`) at the `Validate Railway secrets` step with `Not Authorized` from Railway's `{me{id}}` probe. PRs #851 and #853 landed investigation artifacts for this same issue (#850); they did not — and could not — rotate the underlying secret. Issue #854 already opened for the 39th occurrence (PR #855 merged the artifact). The pickup cron has now re-queued #850 four times because no PR followed each prior pickup with the actual fix. **Per `CLAUDE.md` § "Railway Token Rotation", agents cannot perform this rotation** — the fix lives in a non-code primitive (a GitHub Actions secret) that requires human auth at railway.com.

---

## Analysis

### First-Principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| `Validate Railway secrets` probe | `.github/workflows/staging-pipeline.yml:49-58` | Yes | Correctly fails fast with an actionable error message. The validator is doing exactly what it should — surfacing the expired secret before a destructive deploy attempt. |
| `RAILWAY_TOKEN` GitHub Actions secret | (GitHub repo settings → Actions secrets) | No (operational) | Token is invalid; secret needs to be re-issued by a human via railway.com. Agents have no credential to authenticate to railway.com. |
| Rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Yes | Canonical, human-targeted runbook already exists. No edits needed. |

The **primitive is sound**; the **operational state is broken**. There is no code change that can fix this — only a human secret rotation.

### Root Cause / Evidence Chain

WHY: Staging pipeline run `25239867327` ended in `failure`.
↓ BECAUSE: Job `Deploy to staging` exited 1 at the `Validate Railway secrets` step; downstream jobs (`Deploy staging image to Railway`, `Wait for staging health`, `Staging E2E smoke tests`, `Deploy to production`) were skipped.
↓ BECAUSE: The `{me{id}}` probe (`.github/workflows/staging-pipeline.yml:49-52`) to `https://backboard.railway.app/graphql/v2` returned an auth error.
  Evidence: `2026-05-02T01:04:55.5764191Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is not accepted by Railway's API.
  Evidence: same `Not Authorized` signature across `25227458546` (18:35), `25229747557` (19:34), `25237747540` (23:34), `25238494833` (00:04), `25239867327` (01:04). Independently, the scheduled `railway-token-health.yml` job has failed every day from 2026-04-28 through 2026-05-01 (`25049349913`, `25105119767`, `25161724763`, `25211139148`).

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub Actions secret `RAILWAY_TOKEN`) | n/a | UPDATE (human) | Replace with a freshly issued account/team-scoped Railway API token |
| `.github/workflows/staging-pipeline.yml` | 49-58 | (no change) | Validator works as designed — confirmed by clean `Not Authorized` surfacing |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | n/a | (no change) | Canonical runbook — owned by separate change, do not edit here |
| `.github/RAILWAY_TOKEN_ROTATION_*.md` | n/a | **DO NOT CREATE** | Category 1 trap per `CLAUDE.md` |

### Integration Points

- `.github/workflows/staging-pipeline.yml` consumes `RAILWAY_TOKEN` at `Validate Railway secrets` (line 50), `Deploy staging image to Railway` (line 62), and downstream Railway GraphQL calls.
- `.github/workflows/railway-token-health.yml` (scheduled) probes the same secret daily — currently red since 2026-04-28.
- No code paths consume `RAILWAY_TOKEN` (it is a CI-only secret).

### Git History

- `staging-pipeline.yml` validator step has been stable for many weeks; this is not a regression in the workflow.
- 38 prior recurrences across issues (e.g. `docs/RAILWAY_TOKEN_ROTATION_742.md` was created for the 1st rotation; subsequent investigations have followed the same pattern: `#843`, `#847`, `#850`, `#854`).
- **Implication**: This is a **recurring operational issue**, not a code defect. The high cadence (38 occurrences) is itself a signal worth investigating in a separate bead — see web-research.md for hypotheses (wrong token type stored in the secret, account-side revocation, leakage triggering invalidation).

---

## Implementation Plan

| Step | File | Change |
|------|------|--------|
| 1 | (GitHub secret `RAILWAY_TOKEN`) | **Human rotates** via railway.com → repo Actions secrets (account/team-scoped token, NOT a project token) |
| 2 | (none — codebase) | No source / workflow / runbook changes; agents cannot perform this action |
| 3 | (GitHub Actions UI / `gh` CLI) | `gh run rerun 25239867327 --failed` and confirm pipeline reaches `Deploy to production` |

### Step 1: Human rotates `RAILWAY_TOKEN` per the canonical runbook

**File**: GitHub Actions secret (no source file)
**Action**: UPDATE (human-only)

Per `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
> When CI fails with `RAILWAY_TOKEN is invalid or expired`:
> 1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> 2. File a GitHub issue or send mail to mayor with the error details.
> 3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.

The issue is already open (#850); this artifact is the agent's contribution. The human steps are:

1. Log into railway.com.
2. Generate a new **account/team-scoped** API token at https://railway.com/account/tokens (project tokens **cannot** answer the `{me{id}}` probe — see web-research.md §2).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run failed pipeline: `gh run rerun 25239867327 --failed`.
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Staging E2E smoke tests` → `Deploy to production`.
6. Comment on this issue with the green run URL, remove `archon:in-progress`, close #850 (and #854).
7. Confirm the next scheduled `railway-token-health.yml` run goes green.

**Why**: The validator at `staging-pipeline.yml:53-57` correctly identifies that `{me{id}}` returns no `data.me.id` — the only way to make this pass is to supply a token Railway accepts.

### Step 2: No code changes

The validator, deploy step, and runbook are all correct. Editing any of them would either (a) create a Category 1 documentation trap (claiming work an agent cannot do) or (b) destabilize a known-working primitive without addressing the root cause.

### Step 3: Re-run pipeline post-rotation

`gh run rerun 25239867327 --failed` after the secret is updated. Verify via `gh run watch <new-run-id>` that the deploy reaches `Deploy to production`.

---

## Patterns to Follow

This is the **5th pickup** of issue #850. The established pattern across the prior 4 pickups (PRs #851, #853, plus two re-queues) is:

```
# SOURCE: pattern used by PR #851 and PR #853
# 1. Write investigation artifact under artifacts/runs/<workflow-id>/
# 2. Reference latest failed run ID and exact error string
# 3. Cite CLAUDE.md § "Railway Token Rotation" verbatim
# 4. Direct human to docs/RAILWAY_TOKEN_ROTATION_742.md
# 5. Explicitly enumerate the Category 1 traps NOT taken
# 6. Post a GH comment summarising the artifact
# 7. Make NO source / workflow / runbook edits
```

This pickup follows that pattern exactly.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Agent invents a "rotation done" `.github/RAILWAY_TOKEN_ROTATION_*.md` | Explicitly enumerated as not-done in this artifact and in the GH comment; CLAUDE.md flags this as a Category 1 error |
| Agent edits `staging-pipeline.yml` to bypass the validator | Validator is correct and load-bearing; bypassing it would let a broken deploy proceed and damage prod |
| Agent edits the canonical runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` | Out of scope; runbook is owned by a separate change. Edits here would be an out-of-scope drive-by |
| Agent attempts to swap to `Project-Access-Token` header | Per web-research.md from PR #851: project tokens **cannot** call `serviceInstanceUpdate`/`serviceInstanceDeploy`, so this would break the deploy step too |
| Pickup cron continues to re-queue indefinitely | This is by design; the cron unblocks itself only when a human rotates the secret. The re-queue cost is bounded (one investigation artifact per pickup) |

---

## Validation

### Automated Checks

```bash
# After human rotation:
gh run rerun 25239867327 --failed
gh run list --workflow=staging-pipeline.yml --limit 1
gh run list --workflow=railway-token-health.yml --limit 1
```

Both workflows must show `success` after rotation.

### Manual Verification

1. Pipeline reaches `Deploy to production` (not skipped).
2. Production health check passes.
3. Next scheduled `railway-token-health.yml` run goes green.
4. Issues #850 and #854 are closed by the human operator.

---

## Scope Boundaries

**IN SCOPE:**
- Write this investigation artifact.
- Post a summary comment on issue #850.
- Direct the human to the canonical rotation runbook.

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` (validator is correct).
- `.github/workflows/railway-token-health.yml` (probe is correct).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` (canonical runbook, separate change).
- Any `.github/RAILWAY_TOKEN_ROTATION_*.md` file (Category 1 trap).
- Renaming `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` (deferred — see PR #853 follow-ups).
- Refactor to Railway CLI + project token (deferred — see PR #853 follow-ups, ~half-day durable refactor).
- Closing or deduping issue #854 (separate triage decision for the human operator).

---

## Metadata

- **Investigated by**: Claude (Opus 4.7)
- **Timestamp**: 2026-05-02T02:15:00Z
- **Workflow ID**: ada4a84b65f08b01b649caa2de5524dc
- **Artifact**: `artifacts/runs/ada4a84b65f08b01b649caa2de5524dc/investigation.md`
- **Companion**: `artifacts/runs/ada4a84b65f08b01b649caa2de5524dc/web-research.md`
- **Pickup count**: 5th pickup of #850 (initial PR #851 → re-queue → re-queue → PR #853 → re-queue at 2026-05-02T02:00:42Z → this pickup)
