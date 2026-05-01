# Investigation: Prod deploy failed on main (#845) — RAILWAY_TOKEN expired (36th occurrence, 2nd pickup)

**Issue**: #845 (https://github.com/alexsiri7/reli/issues/845)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-01T17:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy pipeline is fully blocked at the staging step — no code can ship until the token is rotated; however, no data loss or runtime outage of the live app, so not CRITICAL. |
| Complexity | LOW | The fix is a single GitHub Actions secret update by a human via railway.com — zero code changes; the only "complexity" is the human handoff. |
| Confidence | HIGH | Workflow log shows the exact failure string `RAILWAY_TOKEN is invalid or expired: Not Authorized` emitted by the `Validate Railway secrets` step, which is the same Railway GraphQL `{me{id}}` probe that has fired 35 times before. |

---

## Problem Statement

The "Staging → Production Pipeline" run [25218338831](https://github.com/alexsiri7/reli/actions/runs/25218338831) failed at the `Validate Railway secrets` step on commit `212718c` with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. This is the **36th** RAILWAY_TOKEN expiration (2nd pickup of issue #845 after the first archon attempt timed out without producing a PR — see issue comment at 2026-05-01T17:00:43Z). The token lives in GitHub Actions secrets and **cannot be rotated by an agent**; it requires a human with railway.com access.

---

## Analysis

### Root Cause

The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked) again. The validation step at `.github/workflows/staging-pipeline.yml:32-58` calls Railway's GraphQL `{me{id}}` endpoint to probe the token; Railway returned `Not Authorized`, so the workflow exits 1 before any deploy mutation runs. No application or pipeline-config bug exists — the deploy code path is healthy and would succeed with a valid token.

### Evidence Chain

WHY: `Staging → Production Pipeline` run 25218338831 ended in `failure`.
↓ BECAUSE: The `Deploy to staging` job exited 1 at the `Validate Railway secrets` step.
  Evidence: `gh run view 25218338831` — `X Validate Railway secrets` failed; subsequent steps `Deploy staging image`, `Wait for staging health`, and the `production` job were all skipped.

↓ BECAUSE: The token-probe call to Railway's GraphQL API returned an auth error.
  Evidence: Annotation on the run: `RAILWAY_TOKEN is invalid or expired: Not Authorized` (`.github#29`).

↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is no longer accepted by Railway's API.
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the workflow probes `https://backboard.railway.app/graphql/v2` with `{me{id}}`; on a non-`data.me.id` response it prints `RAILWAY_TOKEN is invalid or expired: <message>` and exits 1. The message body matches verbatim.

### Affected Files

**No application/pipeline code changes are required.** The fix is in GitHub Actions secret storage (managed via railway.com → GitHub repo settings), which is outside this repository.

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub repo secret `RAILWAY_TOKEN`) | n/a | ROTATE (human) | New Railway API token, pasted into Actions secrets. See `docs/RAILWAY_TOKEN_ROTATION_742.md`. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | n/a | REFERENCE | Existing runbook for the rotation procedure — do not modify. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the gate that just failed).
- `.github/workflows/staging-pipeline.yml:60-95` — `Deploy staging image to Railway` (skipped; will run on next push once the token is valid).
- `.github/workflows/railway-token-health.yml` — periodic health probe; expected to start failing as well until rotation completes.

### Git History

- **Pipeline workflow last touched**: see `git log -- .github/workflows/staging-pipeline.yml` — recent edits are unrelated to auth (logging/format tweaks).
- **Recent investigations of the same failure mode**:
  - #841 — 35th RAILWAY_TOKEN expiration, 2nd pickup (commit `212718c`)
  - #841 — 34th RAILWAY_TOKEN expiration, prod-deploy framing (commit `c42a83b`)
  - #836 — 33rd RAILWAY_TOKEN expiration, 2nd pickup (commit `ee9d0fb`)
  - #833 — 32nd RAILWAY_TOKEN expiration, 3rd pickup (commit `da29247`)
- **Implication**: This is a long-standing operational issue, not a regression. Each expiration produces a fresh `pipeline-health-cron.sh` issue; #845 is the 36th in the series. The deploy SHA `212718cc` is the previous investigation's own commit — i.e., the prior fix attempt landed (just docs) but did not and could not rotate the token, so the next deploy still fails on the same gate.

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
2. Generate a new API token (account or team-scoped, same permissions as previous).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run the failed pipeline: `gh run rerun 25218338831 --failed` (or push a no-op commit).
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Deploy to production`.

### Step 2: Verify and close the issue

Once the rerun is green:
- Comment on #845 with the successful run URL.
- Remove the `archon:in-progress` label.
- Close #845.

### Step N: No tests to add

Token-rotation is an out-of-band operational task; nothing to assert in the codebase. The existing `railway-token-health.yml` workflow already monitors token validity on a schedule.

---

## Patterns to Follow

This investigation deliberately mirrors the structure of the prior 35 RAILWAY_TOKEN investigations (e.g., commit `212718c` for #841). The pattern, per `CLAUDE.md`, is:

1. Confirm the failure string verbatim from the workflow log.
2. State plainly that the agent cannot rotate the token.
3. Point the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`.
4. Do **not** create or modify any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — that has historically been a Category 1 error (claiming success on an action the agent did not perform).

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a "rotation done" doc (Category 1 error per CLAUDE.md) | Investigation explicitly forbids this; only the rotation runbook is referenced. |
| Pickup cron re-fires while human is mid-rotation | Issue is labeled `archon:in-progress`; the comment trail makes the state visible. |
| Token-health workflow starts paging once it next runs | Expected and self-resolving once the secret is rotated; no action needed. |
| Multiple stale duplicate "Prod deploy failed" issues open simultaneously | Only #845 is open right now (`gh issue list --search "Prod deploy failed"` returned only #845). If duplicates appear later, dedupe by run ID. |
| Other secrets (`RAILWAY_STAGING_SERVICE_ID`, `RAILWAY_STAGING_ENVIRONMENT_ID`, `RAILWAY_STAGING_URL`) are also missing | The validate step would name them in the `Missing required secrets:` error. The actual log says `Not Authorized` (token rejected by Railway), so the other secrets are present — only the token needs rotation. |

---

## Validation

### Automated Checks

After human rotation:

```bash
gh run rerun 25218338831 --failed
gh run watch <new-run-id>
```

Pipeline must reach `Deploy to production` and complete `success`.

### Manual Verification

1. New run's `Validate Railway secrets` step shows no `Not Authorized` annotation.
2. `Deploy staging image to Railway` posts a `serviceInstanceUpdate` response without `errors`.
3. `Wait for staging health` returns 200.
4. Production deploy job runs and passes.
5. https://reli.up.railway.app (or whatever the prod URL is) serves the new SHA.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnose the deploy failure on run 25218338831.
- Produce this investigation artifact and post it to #845.
- Direct the human to the rotation runbook.

**OUT OF SCOPE (do not touch):**
- Rotating `RAILWAY_TOKEN` (agent cannot do this — railway.com requires human auth).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming the rotation is done (explicitly forbidden by `CLAUDE.md`).
- Modifying `docs/RAILWAY_TOKEN_ROTATION_742.md` (it's the canonical runbook; changes belong in their own bead).
- Modifying `.github/workflows/staging-pipeline.yml` — the validate step is correctly designed and the failure mode is informative, not a bug in the workflow.
- Any "automation" to refresh the token (would require storing a long-lived Railway credential elsewhere — out of scope and a separate security discussion).
- Closing duplicate prior deploy-down issues — handled by separate dedup beads.

---

## Metadata

- **Investigated by**: Claude (claude-opus-4-7[1m])
- **Timestamp**: 2026-05-01T17:10:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/d86021071e05e1fc63af34398ba0bafd/investigation.md`
- **Failed run**: https://github.com/alexsiri7/reli/actions/runs/25218338831
- **Failure annotation**: `RAILWAY_TOKEN is invalid or expired: Not Authorized`
- **Series position**: 36th RAILWAY_TOKEN expiration, 2nd pickup of #845
