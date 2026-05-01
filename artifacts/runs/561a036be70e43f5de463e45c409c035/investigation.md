# Investigation: Prod deploy failed on main (#850) — RAILWAY_TOKEN expired (38th occurrence)

**Issue**: #850 (https://github.com/alexsiri7/reli/issues/850)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-01T19:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy pipeline is fully blocked at the staging gate — no code can ship until the token is rotated; live app keeps serving traffic and there is no data loss, so not CRITICAL. |
| Complexity | LOW | Fix is a single GitHub Actions secret update by a human via railway.com — zero code changes; the only "complexity" is the human handoff. |
| Confidence | HIGH | Workflow log at `.github/workflows/staging-pipeline.yml:55` shows the exact failure string `RAILWAY_TOKEN is invalid or expired: Not Authorized` emitted by the `Validate Railway secrets` step, the same Railway GraphQL `{me{id}}` probe that has fired 37 times before; the daily `railway-token-health.yml` workflow has also failed on 2026-04-28, 2026-04-29, 2026-04-30, and 2026-05-01. |

---

## Problem Statement

The "Staging → Production Pipeline" run [25227458546](https://github.com/alexsiri7/reli/actions/runs/25227458546) failed at the `Validate Railway secrets` step on commit `22d947c` (the merge SHA of PR #848 — the previous investigation) with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. This is the **38th** RAILWAY_TOKEN expiration in the series. The token lives in GitHub Actions secrets and **cannot be rotated by an agent**; it requires a human with railway.com access.

---

## Analysis

### Root Cause

The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked) and not been rotated. The validation step at `.github/workflows/staging-pipeline.yml:32-58` calls Railway's GraphQL `{me{id}}` endpoint to probe the token; Railway returned `Not Authorized`, so the workflow exits 1 before any deploy mutation runs. No application or pipeline-config bug exists — the deploy code path is healthy and would succeed with a valid token. The independent `railway-token-health.yml` workflow has failed four days in a row (2026-04-28, 2026-04-29, 2026-04-30, 2026-05-01), confirming the token has been bad for ~96 hours.

### Evidence Chain

WHY: `Staging → Production Pipeline` run 25227458546 ended in `failure`.
↓ BECAUSE: The `Deploy to staging` job exited 1 at the `Validate Railway secrets` step (step #4), and downstream `Deploy staging image to Railway`, `Wait for staging health`, `Staging E2E smoke tests`, and `Deploy to production` were all `skipped`.
  Evidence: `gh run view 25227458546 --json jobs` — `"name":"Validate Railway secrets","conclusion":"failure"`; subsequent steps `"conclusion":"skipped"`.

↓ BECAUSE: The token-probe call to Railway's GraphQL API returned an auth error.
  Evidence: Workflow log line `2026-05-01T18:35:14.3742222Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is no longer accepted by Railway's API.
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` probes `https://backboard.railway.app/graphql/v2` with `{query: "{me{id}}"}`; on a non-`data.me.id` response it emits `RAILWAY_TOKEN is invalid or expired: <message>` and exits 1. The message body matches verbatim. Independently, `railway-token-health.yml` runs 25211139148 (2026-05-01), 25161724763 (2026-04-30), 25105119767 (2026-04-29), and 25049349913 (2026-04-28) all conclude `failure`.

### Affected Files

**No application/pipeline code changes are required.** The fix is in GitHub Actions secret storage (managed via railway.com → GitHub repo settings), which is outside this repository.

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub repo secret `RAILWAY_TOKEN`) | n/a | ROTATE (human) | New Railway API token, pasted into Actions secrets. See `docs/RAILWAY_TOKEN_ROTATION_742.md`. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | n/a | REFERENCE | Existing runbook for the rotation procedure — do not modify. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the gate that just failed).
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` step (skipped; will run on next push once the token is valid). Calls `serviceInstanceUpdate` and `serviceInstanceDeploy` mutations with the same token.
- `.github/workflows/railway-token-health.yml` — periodic health probe; currently failing daily and will keep failing until rotation completes.

### Git History

- **Pipeline workflow last touched**: `.github/workflows/staging-pipeline.yml` — recent edits unrelated to auth (logging/format tweaks).
- **Recent investigations of the same failure mode** (most recent first):
  - #847 — 37th RAILWAY_TOKEN expiration (commit `22d947c`, PR #848)
  - #843 — 37th RAILWAY_TOKEN expiration, 3rd pickup (commit `802cb44`, PR #849)
  - #845 — 36th RAILWAY_TOKEN expiration, 2nd pickup (commit `bd17591`, PR #846)
  - #841 — 35th RAILWAY_TOKEN expiration, 2nd pickup (commit `212718c`, PR #844)
  - #841 — 34th RAILWAY_TOKEN expiration, prod-deploy framing (commit `c42a83b`, PR #842)
  - #833 — 32nd RAILWAY_TOKEN expiration, 3rd pickup (commit `da29247`, PR #840)
- **Implication**: This is a long-standing operational issue, not a regression. Each new push to `main` re-fires the deploy and `pipeline-health-cron.sh` files a fresh issue. Issue #850's failed deploy ran on commit `22d947c` — the merge SHA of the prior investigation (PR #848). That PR (correctly) only added documentation; it could not and did not rotate the token, so the next deploy still fails on the same gate. This pattern will continue indefinitely until a human rotates the token.

---

## Implementation Plan

**Agent action — none on the codebase.** Per `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
> When CI fails with `RAILWAY_TOKEN is invalid or expired`:
> 1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> 2. File a GitHub issue or send mail to mayor with the error details.
> 3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

### Step 1: Human rotates the token

**Owner**: Repository maintainer with railway.com access.
**Action**: Follow `docs/RAILWAY_TOKEN_ROTATION_742.md` end to end:

1. Log into railway.com.
2. Generate a new account/team-scoped API token (must satisfy `{me{id}}` — project tokens **cannot**, per web research; see `web-research.md` Finding 1).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run the failed pipeline: `gh run rerun 25227458546 --failed` (or push a no-op commit).
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Staging E2E smoke tests` → `Deploy to production`.

### Step 2: Verify and close the issue

Once the rerun is green:
- Comment on #850 with the successful run URL.
- Remove the `archon:in-progress` label.
- Close #850.

### Step 3: Confirm token-health workflow recovers

The next scheduled run of `.github/workflows/railway-token-health.yml` should conclude `success`. If it doesn't, the new token has the wrong scope (likely a project token instead of an account token).

### Step N: No tests to add

Token-rotation is an out-of-band operational task; nothing to assert in the codebase. The existing `railway-token-health.yml` workflow already monitors token validity on a schedule.

---

## Patterns to Follow

This investigation deliberately mirrors the structure of the prior 37 RAILWAY_TOKEN investigations (most recently commit `22d947c` for #847). The pattern, per `CLAUDE.md`, is:

1. Confirm the failure string verbatim from the workflow log.
2. State plainly that the agent cannot rotate the token.
3. Point the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`.
4. Do **not** create or modify any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — that has historically been a Category 1 error (claiming success on an action the agent did not perform).

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a "rotation done" doc (Category 1 error per CLAUDE.md) | Investigation explicitly forbids this; only the rotation runbook is referenced. |
| Pickup cron re-fires #850 while human is mid-rotation | Issue is labeled `archon:in-progress`; the comment trail makes the state visible. |
| Token-health workflow keeps paging | Self-resolving once the secret is rotated; no action needed. |
| Future merges to `main` keep re-firing `pipeline-health-cron.sh` and creating new duplicate deploy-failed issues | Expected; each will resolve once rotation completes. The duplicate issues should be closed by the dedup bead, not this one. |
| Human rotates with a project token instead of account token | The new token will fail the `{me{id}}` validation step the same way (`Not Authorized`). Web research (Finding 1) confirms project tokens cannot answer `me`; runbook step in `docs/RAILWAY_TOKEN_ROTATION_742.md` should explicitly call out account/team scope. |
| Token rotated with right type but wrong permissions | Validation will pass but `Deploy staging image to Railway` (the `serviceInstanceUpdate` mutation) will fail next. Runbook step 5 covers verification. |

---

## Validation

### Automated Checks

After human rotation:

```bash
gh run rerun 25227458546 --failed
gh run watch <new-run-id>
```

Pipeline must reach `Deploy to production` and complete `success`. The next scheduled `railway-token-health.yml` run must also conclude `success`.

### Manual Verification

1. New run's `Validate Railway secrets` step shows no `Not Authorized` annotation.
2. `Deploy staging image to Railway` posts a `serviceInstanceUpdate` response without `errors`.
3. `Wait for staging health` returns 200.
4. `Staging E2E smoke tests` job passes.
5. Production deploy job runs and passes.
6. Live app at the production URL serves the new SHA.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnose the deploy failure on run 25227458546.
- Produce this investigation artifact and post it to #850.
- Direct the human to the rotation runbook.

**OUT OF SCOPE (do not touch):**
- Rotating `RAILWAY_TOKEN` (agent cannot do this — railway.com requires human auth).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming the rotation is done (explicitly forbidden by `CLAUDE.md`).
- Modifying `docs/RAILWAY_TOKEN_ROTATION_742.md` (it's the canonical runbook; changes belong in their own bead).
- Modifying `.github/workflows/staging-pipeline.yml` — the validate step is correctly designed and the failure mode is informative, not a bug in the workflow.
- Refactoring deploy to use the Railway CLI image + project token (web-research recommendation #3 — durable but a half-day refactor; out of scope for this hot-path bead).
- Renaming `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` (web-research recommendation #2 — should be a separate, considered change once rotation is no longer an emergency).
- Closing duplicate prior deploy-down issues — handled by separate dedup beads.

---

## Metadata

- **Investigated by**: Claude (claude-opus-4-7[1m])
- **Timestamp**: 2026-05-01T19:35:00Z
- **Artifact**: `artifacts/runs/561a036be70e43f5de463e45c409c035/investigation.md`
- **Failed run**: https://github.com/alexsiri7/reli/actions/runs/25227458546
- **Failure annotation**: `RAILWAY_TOKEN is invalid or expired: Not Authorized`
- **Series position**: 38th RAILWAY_TOKEN expiration
- **Token-health workflow status**: failing daily since 2026-04-28 (runs 25049349913, 25105119767, 25161724763, 25211139148)
- **Companion artifact**: `artifacts/runs/561a036be70e43f5de463e45c409c035/web-research.md` (closes the open "project token + serviceInstanceUpdate" gap from prior research)
