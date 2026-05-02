# Investigation: Main CI red — `Deploy to staging` / RAILWAY_TOKEN expired (39th occurrence, issue #854)

**Issue**: #854 (https://github.com/alexsiri7/reli/issues/854)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-02T00:30:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging gate is blocking every push to `main`; staging-pipeline.yml run `25238494833` (head SHA `9502630`) failed at `Validate Railway secrets` immediately after `pipeline-health-cron.sh` fired this issue. Prod pipeline cannot advance, but the live app keeps serving traffic and no data is at risk — not CRITICAL. |
| Complexity | LOW | Zero-line code change. The fix is a human action: generate a new account-scoped Railway token at railway.com and update the GitHub Actions secret `RAILWAY_TOKEN`. No tree edits are appropriate. |
| Confidence | HIGH | Failure signature in the failed run is the exact `RAILWAY_TOKEN is invalid or expired: Not Authorized` string emitted by `staging-pipeline.yml:55`; identical to the 38 prior occurrences (most recent: PR #853 / issue #850 investigation, also still open). The validator probe (`{me{id}}` against `https://backboard.railway.app/graphql/v2`) is correctly designed and is not the source of the bug. |

---

## Problem Statement

`pipeline-health-cron.sh` filed issue #854 immediately after staging-pipeline run `25238494833` failed on head SHA `9502630e51dd39a6676680ac66cd54d5a5da7c4a` (the merge commit of PR #853, itself the prior #850 investigation). The failure is the same `RAILWAY_TOKEN is invalid or expired: Not Authorized` signature that has now occurred **39 times** — `web-research.md` (this artifact dir) traces the historic counts. Issue #850 is **still open** under `archon:in-progress`, so #854 is functionally a re-firing of the same condition under a fresh issue number rather than an independent regression. Per `CLAUDE.md` § "Railway Token Rotation", an agent **cannot** rotate this token; the action requires a human with railway.com access.

---

## Analysis

### Primitive — first principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Token validity probe | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Step `Validate Railway secrets` correctly fails fast on auth error and emits an actionable message at `:55-56`; not the source of the bug. |
| `RAILWAY_TOKEN` GitHub Actions secret | (GitHub UI) | No | Token is rejected by `https://backboard.railway.app/graphql/v2` `{me{id}}` — needs rotation by a human; agents cannot perform this. |
| Pipeline-health cron / immediate-fire path | `pipeline-health-cron.sh` (mayor) | Yes | Auto-filing under `archon:in-progress` correctly suppresses double-pickup; the loop will keep firing one new issue per failed run until the secret is rotated and #850/#854 are closed. |

The bug is in a non-code primitive (the secret value). No source change can fix it.

### Root Cause

WHY: Staging pipeline run `25238494833` (2026-05-02T00:04:34Z, head SHA `9502630`) ended in `failure`.
↓ BECAUSE: Job `Deploy to staging` exited 1 in step `Validate Railway secrets`.
↓ BECAUSE: The `{me{id}}` probe to `https://backboard.railway.app/graphql/v2` returned `Not Authorized`.
  Evidence: `2026-05-02T00:04:38.7863098Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is no longer accepted by Railway's API. It has not been rotated since PRs #851 / #853 landed the prior investigations for #850.
  Evidence: `staging-pipeline.yml:49-58` issues the probe; Railway returns `Not Authorized`. The `railway-token-health.yml` cron (last run `25211139148`, 2026-05-01T10:27:15Z) is also still `failure`.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub secret `RAILWAY_TOKEN`) | — | UPDATE | Human rotates via railway.com → repo secrets |
| (none in source tree) | — | — | No code, workflow, or runbook changes are required or appropriate |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` consumes the secret for the probe; the deploy step at `:60-88` reuses it for `serviceInstanceUpdate` and `serviceInstanceDeploy` mutations.
- `.github/workflows/railway-token-health.yml` runs the same probe daily; will go green automatically once the secret is rotated.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` is the canonical human runbook.

### Git History

- **PR #853** merged 2026-05-02 — landed the previous #850 investigation (commit `9502630`); no source change. Its merge to `main` is precisely what triggered run `25238494833` and thus this new issue.
- **No subsequent commits to `.github/`** — confirming nothing on the agent side has changed (and nothing should).
- **Implication**: This is a stuck-on-human-action condition, not a regression. Each merge to `main` will continue to file a fresh issue until the token is rotated.

---

## Implementation Plan

### Step 1: Human rotates `RAILWAY_TOKEN`

**File**: GitHub Actions secret (out-of-tree)
**Action**: UPDATE

Per `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new **account-scoped** API token at `https://railway.com/account/tokens`. Workspace and project tokens cannot answer `{me{id}}` (see `web-research.md` § 1, § 5 in this artifact dir). Select **No expiration** if the option is present; if it is not present, screenshot the UI and report back so the runbook can be corrected (see `web-research.md` § 2).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run the failed pipeline: `gh run rerun 25238494833 --failed --repo alexsiri7/reli`.
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Staging E2E smoke tests` → `Deploy to production`.
6. Comment on issues #854 **and** #850 with the green run URL, remove `archon:in-progress` from both, close both.
7. Verify the next scheduled `railway-token-health.yml` run also goes green.

**Why**: Without this human action, every subsequent merge to `main` will trigger a fresh staging-pipeline failure and `pipeline-health-cron.sh` will keep filing new sibling issues.

---

### Step 2 (Explicitly NOT done — Category 1 traps)

Per `CLAUDE.md`:

- ❌ Do **not** create `.github/RAILWAY_TOKEN_ROTATION_*.md` claiming rotation is done.
- ❌ Do **not** edit `.github/workflows/staging-pipeline.yml` — the validator is correctly designed.
- ❌ Do **not** edit `.github/workflows/railway-token-health.yml` — same reasoning.
- ❌ Do **not** edit `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook owned by separate change.
- ❌ Do **not** swap to `Project-Access-Token` headers — per `web-research.md` § 5, project tokens cannot answer `{me{id}}` and would also require coordinated changes to deploy-step mutations; out of scope for this emergency bead.

---

## Patterns to Follow

This pickup mirrors the established no-op pattern (PRs #848, #851, #852, #853 and 35 prior occurrences):

1. Verify the failure signature matches `RAILWAY_TOKEN is invalid or expired`.
2. Write a short investigation artifact (this file) under `artifacts/runs/<workflow-id>/`.
3. Post a brief comment on the issue restating the human action.
4. Land the artifact via PR with `Part of #854` (so `gt done` links it).
5. Do **not** modify any source/workflow/runbook file.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| `pipeline-health-cron.sh` files yet another sibling issue before the human rotates | Tolerable — comment trail makes the human action obvious; each pickup is a docs-only PR |
| Issues #854 and #850 race for closure | Both should be closed by the same human after the green run; either order is fine |
| Human rotates but creates a workspace/project token by mistake | `docs/RAILWAY_TOKEN_ROTATION_742.md` and `web-research.md` § 1 both call out account-scope explicitly |
| Token rotation lands while another bead is mid-flight | No conflict — secret rotation is out-of-tree; other PRs proceed unaffected once pipeline is green |

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
3. Issues #854 and #850 closed with green run URL.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact under `artifacts/runs/8a2386c3ae1983d14df8161ca0d0849e/`.
- A brief restating-comment on issue #854 directing the human to the runbook.

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
- **Timestamp**: 2026-05-02T00:30:00Z
- **Workflow ID**: 8a2386c3ae1983d14df8161ca0d0849e
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/8a2386c3ae1983d14df8161ca0d0849e/investigation.md`
- **Companion**: `web-research.md` in the same directory (Railway token type / TTL research)
- **Sibling open issue**: #850 (still open, same root cause; closing one without the other will leave the loop running)
- **Latest failing run**: `25238494833` (2026-05-02T00:04:34Z, head SHA `9502630`)
