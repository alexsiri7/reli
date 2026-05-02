# Investigation: Main CI red — `Deploy to staging` / RAILWAY_TOKEN expired (39th occurrence, issue #854, 2nd pickup)

**Issue**: #854 (https://github.com/alexsiri7/reli/issues/854)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-02T02:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging gate continues to block every push to `main`; latest staging-pipeline run `25239867327` (2026-05-02T01:04:48Z) failed at `Validate Railway secrets` with the same signature seen in 38 prior occurrences. Live app keeps serving traffic and no data is at risk — not CRITICAL. |
| Complexity | LOW | Zero-line code change. The fix is a human action: generate a new account-scoped Railway token at railway.com and update the GitHub Actions secret `RAILWAY_TOKEN`. No tree edits are appropriate. |
| Confidence | HIGH | Failure signature is the exact `RAILWAY_TOKEN is invalid or expired: Not Authorized` string emitted by `staging-pipeline.yml` step `Validate Railway secrets`; identical to 38 prior occurrences and to the 1st pickup of this issue (PR #855, workflow `8a2386c3…`). The validator probe is correctly designed and is not the source of the bug. |

---

## Problem Statement

This is the **2nd pickup** of issue #854. The 1st pickup landed PR #855 (merged 2026-05-02T01:00:10Z, workflow `8a2386c3ae1983d14df8161ca0d0849e`) with a docs-only no-op investigation. The cron at 02:30:37Z then re-queued #854 because it found `archon:in-progress` set with no live run and no linked PR — likely a label-cleanup race rather than a new failure mode. Independently, the **most recent staging-pipeline run** (`25239867327`, 2026-05-02T01:04:48Z) **failed with the same signature**, confirming the secret remains unrotated.

Sibling issue #850 has been **closed** (`archon:done`) since the 1st pickup — only #854 is open under this root cause now.

Per `CLAUDE.md` § "Railway Token Rotation", an agent **cannot** rotate this token; the action requires a human with railway.com access. This investigation produces a docs-only artifact pair (this file plus the already-written `web-research.md`) and a restating comment on the issue.

---

## Analysis

### Primitive — first principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Token validity probe | `.github/workflows/staging-pipeline.yml` step `Validate Railway secrets` | Yes | Fails fast on auth error and emits an actionable message; not the source of the bug. |
| `RAILWAY_TOKEN` GitHub Actions secret | (GitHub UI) | No | Token is rejected by `https://backboard.railway.app/graphql/v2` `{me{id}}` — needs rotation by a human; agents cannot perform this. |
| `pipeline-health-cron.sh` immediate-fire path | (mayor) | Yes | Auto-files under `archon:in-progress`; correctly suppresses double-pickup *as long as the label is removed only when the issue is actually closed*. |
| `pipeline-health-cron.sh` re-pickup path | (mayor) | **Partial** | At 02:30:37Z the cron re-fired #854 because the label was still set with no live run — but PR #855 had already been merged 90 minutes earlier with a `Part of #854` reference. The cron's "no linked PR" detection apparently does not count `Part of` references; not in scope to fix here, but worth a follow-up mail to mayor. |

The bug is in a non-code primitive (the secret value). No source change can fix it.

### Root Cause

WHY: Staging-pipeline run `25239867327` (2026-05-02T01:04:48Z, on `main`) ended in `failure`.
↓ BECAUSE: Job `Deploy to staging` exited 1 in step `Validate Railway secrets` (15s end-to-end runtime — typical of a token-rejection failure).
↓ BECAUSE: The `{me{id}}` probe to `https://backboard.railway.app/graphql/v2` returned `Not Authorized`.
  Evidence: `2026-05-02T01:04:55.5764191Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is no longer accepted by Railway's API. It has not been rotated since PRs #851 / #853 / #855 / #856 landed prior investigations. PR #855 (1st pickup of #854) was docs-only by policy and could not have changed the secret state.
  Evidence: `staging-pipeline.yml` issues `curl -X POST … -d '{"query":"{me{id}}"}'`; Railway returns `Not Authorized`. The `railway-token-health.yml` cron's last 3 daily runs (`25211139148` 2026-05-01, `25161724763` 2026-04-30, `25105119767` 2026-04-29) are all `failure`.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub secret `RAILWAY_TOKEN`) | — | UPDATE | Human rotates via railway.com → repo secrets |
| (none in source tree) | — | — | No code, workflow, or runbook changes are required or appropriate |

### Integration Points

- `.github/workflows/staging-pipeline.yml` consumes the secret for the `{me{id}}` probe and reuses it for the deploy mutations downstream.
- `.github/workflows/railway-token-health.yml` runs the same probe daily on a schedule; will go green automatically once the secret is rotated.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` is the canonical human runbook. (Note: `web-research.md` § 1 in this artifact directory now flags that the runbook's "select No expiration" instruction is **not corroborated** by official Railway docs — worth a screenshot during the next rotation.)

### Git History

- **PR #855** merged 2026-05-02T01:00:10Z — 1st pickup of #854, docs-only no-op investigation; no source change.
- **PR #856** merged after #855 — 5th pickup of sibling #850; docs-only; closed #850 via `archon:done`.
- **No commits to `.github/`** between the 1st and 2nd pickup of #854 — confirming nothing on the agent side has changed (and nothing should).
- **Implication**: This is still a stuck-on-human-action condition. The cron's re-firing of #854 at 02:30:37Z is a label-tracking artifact, not a new failure mode. Each merge to `main` will continue to file fresh sibling issues until the token is rotated.

---

## Implementation Plan

### Step 1: Human rotates `RAILWAY_TOKEN`

**File**: GitHub Actions secret (out-of-tree)
**Action**: UPDATE

Per `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new **account-scoped** API token at `https://railway.com/account/tokens`. Workspace and project tokens cannot answer `{me{id}}` (see `web-research.md` § 1, § 5 in workflow `8a2386c3…`'s artifact dir, plus this run's `web-research.md` § 1, § 2). **Screenshot the token-creation UI** — `web-research.md` § 1 (this run) found that Railway's official docs do not document any "No expiration" option for any static token type, so the runbook's central instruction is unverified after 39 occurrences.
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run the failed pipeline: `gh run rerun 25239867327 --failed --repo alexsiri7/reli`.
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Staging E2E smoke tests` → `Deploy to production`.
6. Comment on issue #854 with the green run URL, remove `archon:in-progress`, close. (Sibling #850 is already closed — no need to touch it.)
7. Verify the next scheduled `railway-token-health.yml` run also goes green.

**Why**: Without this human action, every subsequent merge to `main` will trigger a fresh staging-pipeline failure and `pipeline-health-cron.sh` will keep filing new sibling issues.

---

### Step 2 (Explicitly NOT done — Category 1 traps)

Per `CLAUDE.md`:

- Do NOT create `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming rotation is done.
- Do NOT edit `.github/workflows/staging-pipeline.yml` — the validator is correctly designed.
- Do NOT edit `.github/workflows/railway-token-health.yml` — same reasoning.
- Do NOT edit `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook owned by separate change.
- Do NOT swap to `Project-Access-Token` headers — although `web-research.md` § 2 (this run) now confirms the validation query as `query { projectToken { projectId environmentId } }`, the migration also requires changes to deploy-step mutations and `railway up` compatibility verification; out of scope for this emergency bead.

---

## Patterns to Follow

This pickup mirrors the established no-op pattern (PRs #848, #851, #852, #853, #855, #856 — and 35 prior occurrences):

1. Verify the failure signature matches `RAILWAY_TOKEN is invalid or expired`.
2. Write a short investigation artifact (this file) under `artifacts/runs/<workflow-id>/`.
3. Post a brief comment on the issue restating the human action.
4. Land the artifact via PR with `Part of #854` (so `gt done` links it).
5. Do NOT modify any source/workflow/runbook file.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| `pipeline-health-cron.sh` files yet another sibling issue before the human rotates | Tolerable — comment trail makes the human action obvious; each pickup is a docs-only PR. |
| Cron's "no linked PR" detection re-picks up #854 again after this PR lands | Possible — PR #855 used `Part of #854` and the cron still re-fired. Acceptable (cost = one more docs-only PR); a follow-up mail to mayor would address the cron logic. |
| Human rotates but creates a workspace/project token by mistake | `docs/RAILWAY_TOKEN_ROTATION_742.md`, `web-research.md` § 1 (8a2386c3 dir), and `web-research.md` § 1 (this dir) all call out account-scope explicitly. |
| Token rotation lands while another bead is mid-flight | No conflict — secret rotation is out-of-tree; other PRs proceed unaffected once pipeline is green. |

---

## Validation

### Automated Checks

```bash
gh run list --repo alexsiri7/reli --workflow=staging-pipeline.yml --limit 1
gh run list --repo alexsiri7/reli --workflow=railway-token-health.yml --limit 1
```

Both should show `success` after rotation.

### Manual Verification

1. Human reruns failed pipeline; `Validate Railway secrets` step passes.
2. `Deploy to production` step completes `success`.
3. Issue #854 closed with green run URL.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact under `artifacts/runs/0aa164affe30087c42fdb1f17b4c013d/`.
- A brief restating-comment on issue #854 directing the human to the runbook, calling out the "screenshot the No-expiration UI" ask.

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml`
- `.github/workflows/railway-token-health.yml`
- `docs/RAILWAY_TOKEN_ROTATION_742.md`
- Any `.github/RAILWAY_TOKEN_ROTATION_*.md` "rotation done" file
- Migrating `staging-pipeline.yml` to a Project token (technically de-risked by `web-research.md` § 2 of this run; still a follow-up issue, not this bead)
- Investigating the cron's "no linked PR" detection so `Part of` references are recognized (mail to mayor as a separate bead)

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T02:35:00Z
- **Workflow ID**: 0aa164affe30087c42fdb1f17b4c013d
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/0aa164affe30087c42fdb1f17b4c013d/investigation.md`
- **Companion**: `web-research.md` in the same directory (confirmation of token-validation queries and absence of documented "No expiration" UI; written before this artifact)
- **Prior pickup**: PR #855 / workflow `8a2386c3ae1983d14df8161ca0d0849e` (1st pickup, merged 2026-05-02T01:00:10Z)
- **Sibling open issue**: none (#850 closed `archon:done` after the 5th pickup landed in PR #856)
- **Latest failing run**: `25239867327` (2026-05-02T01:04:48Z, branch `main`)
