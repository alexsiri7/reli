# Investigation: Prod deploy failed on `main` — RAILWAY_TOKEN expired (38th occurrence, 3rd pickup of #850)

**Issue**: #850 (https://github.com/alexsiri7/reli/issues/850)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-02T00:00:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy pipeline still blocked at the staging gate — three further `staging-pipeline.yml` runs (`25237747540`, `25229747557`, `25227442673`) failed at `Validate Railway secrets` since PR #851 merged; live app keeps serving traffic, no data loss, so not CRITICAL. |
| Complexity | LOW | Single GitHub Actions secret update by a human via railway.com — zero code changes; complexity is purely the human handoff that has not yet occurred. |
| Confidence | HIGH | Most recent failed run `25237747540` (2026-05-01T23:34:49Z) emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized` from `staging-pipeline.yml:55` — identical signature to the 37 prior occurrences; no token rotation has landed. |

---

## Problem Statement

Issue #850 is the 38th `RAILWAY_TOKEN` expiration. PR #851 (merged 2026-05-01T19:30:09Z) shipped the prior investigation artifact and web research, but a human has not yet rotated the secret — the staging pipeline has continued to fail after that merge (most recently run `25237747540` at 2026-05-01T23:34:49Z). The pickup cron has now re-queued #850 twice (comments at 2026-05-01T21:00:41Z and 2026-05-01T23:30:38Z) because no new PR was opened. Per `CLAUDE.md` § "Railway Token Rotation", an agent **cannot** rotate this token; the action requires a human with railway.com access.

---

## Analysis

### Primitive — first principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Token validity probe | `.github/workflows/staging-pipeline.yml:49-58` | Yes | Correctly fails fast on auth error and emits an actionable message; not the source of the bug. |
| `RAILWAY_TOKEN` GitHub Actions secret | (GitHub UI) | No | Token is rejected by `https://backboard.railway.app/graphql/v2` `{me{id}}` — needs rotation by a human; cannot be done by an agent. |
| Pickup cron / re-queue logic | (mayor) | Yes | Re-queueing on a stuck `archon:in-progress` label is correct behaviour; the loop will keep firing until the secret is rotated and the issue is closed. |

The bug is in a non-code primitive (the secret value). No source change can fix it.

### Root Cause

WHY: Latest staging pipeline run `25237747540` ended in `failure`.
↓ BECAUSE: `Deploy to staging` exited 1 at `Validate Railway secrets`.
↓ BECAUSE: The `{me{id}}` probe to `https://backboard.railway.app/graphql/v2` returned `Not Authorized`.
  Evidence: `2026-05-01T23:34:49.1344177Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is still not accepted by Railway's API; it has not been rotated since PR #851 merged.
  Evidence: `staging-pipeline.yml:49-58` issues the probe; Railway returns `Not Authorized`. The `railway-token-health.yml` cron (last run `25211139148`, 2026-05-01T10:27:15Z) is also still `failure`.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub secret `RAILWAY_TOKEN`) | — | UPDATE | Human rotates via railway.com → repo secrets |
| (none in source tree) | — | — | No code, workflow, or runbook changes are required or appropriate |

### Integration Points

- `.github/workflows/staging-pipeline.yml:49-58` consumes the secret for the probe and the deploy step (lines 60-67).
- `.github/workflows/railway-token-health.yml` runs the same probe daily; will go green automatically once the secret is rotated.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` is the canonical human runbook.

### Git History

- **PR #851** merged 2026-05-01T19:30:09Z — landed the prior investigation artifact (commit `4f11147`); no source change.
- **No subsequent commits to `.github/`** since that merge — confirming nothing on the agent side has changed (and nothing should).
- **Implication**: This is a stuck-on-human-action condition, not a regression.

---

## Implementation Plan

### Step 1: Human rotates `RAILWAY_TOKEN`

**File**: GitHub Actions secret (out-of-tree)
**Action**: UPDATE

Per `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new **account/team-scoped** API token at `https://railway.com/account/tokens` (workspace and project tokens cannot answer `{me{id}}` — see `web-research.md` in this artifact dir).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run the failed pipeline: `gh run rerun 25237747540 --failed` (or `25227442673`, the original).
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Staging E2E smoke tests` → `Deploy to production`.
6. Comment on issue #850 with the green run URL, remove `archon:in-progress`, close the issue.
7. Verify the next scheduled `railway-token-health.yml` run also goes green.

**Why**: Without this human action, every subsequent merge to `main` will trigger a fresh staging-pipeline failure and the pickup cron will keep re-queueing #850.

---

### Step 2 (Explicitly NOT done — Category 1 traps)

Per `CLAUDE.md`:

- ❌ Do **not** create `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming rotation is done.
- ❌ Do **not** edit `.github/workflows/staging-pipeline.yml` — the validator is correctly designed.
- ❌ Do **not** edit `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook owned by separate change.
- ❌ Do **not** swap to `Project-Access-Token` headers — per `web-research.md`, project tokens cannot call `serviceInstanceUpdate`/`serviceInstanceDeploy` and cannot answer `{me{id}}`; that path would require a half-day refactor and is out of scope for this emergency bead.

---

## Patterns to Follow

This pickup mirrors the pattern established in PR #848, #851, #852 (and the 35 prior occurrences):

1. Verify the failure signature matches `RAILWAY_TOKEN is invalid or expired`.
2. Write a short investigation artifact (this file).
3. Post a brief comment on the issue restating the human action.
4. Land the artifact via PR with `Part of #850` (so `gt done` links it).
5. Do **not** modify any source/workflow/runbook file.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-queues #850 again before human rotates | Tolerable — comment trail makes the human action obvious; each pickup is a docs-only PR |
| Human rotates but creates a workspace/project token by mistake | `docs/RAILWAY_TOKEN_ROTATION_742.md` and `web-research.md` both call out account-scope explicitly |
| Token rotation lands while another bead is mid-flight | No conflict — secret rotation is out-of-tree; other PRs proceed unaffected once pipeline is green |

---

## Validation

### Automated Checks

```bash
gh run list --workflow=staging-pipeline.yml --limit 1
gh run list --workflow=railway-token-health.yml --limit 1
```

Both should show `success` after rotation.

### Manual Verification

1. Human reruns failed pipeline; `Validate Railway secrets` step passes.
2. `Deploy to production` step completes `success`.
3. Issue #850 closed with green run URL.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact under `artifacts/runs/143fba6af8ed9a6eee7eae7c6cc02a7d/`.
- A brief restating-comment on issue #850 directing the human to the runbook.

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml`
- `.github/workflows/railway-token-health.yml`
- `docs/RAILWAY_TOKEN_ROTATION_742.md`
- Any `.github/RAILWAY_TOKEN_ROTATION_*.md` "rotation done" file
- Refactoring the deploy job to use the Railway CLI + project token (durable but ~half-day; deferred)
- Renaming `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` (deferred, low value)

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T00:00:00Z
- **Workflow ID**: 143fba6af8ed9a6eee7eae7c6cc02a7d
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/143fba6af8ed9a6eee7eae7c6cc02a7d/investigation.md`
- **Companion**: `web-research.md` in the same directory (from prior pickup)
- **Prior PRs for #850**: #851 (merged 2026-05-01T19:30:09Z)
- **Latest failing runs**: `25237747540` (2026-05-01T23:34:49Z), `25229747557`, `25227442673` (original)
