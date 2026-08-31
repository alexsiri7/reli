# Resolution of Issue #1361

**Date**: 2026-08-31
**Issue**: Prod deploy lagging main
**Status**: RESOLVED (false positive)

## Summary

Issue #1361 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron detected that main (`f8fe1d4`, committed 2026-08-31T02:15:13Z) had been ahead of production for ~925 seconds (~15.4 minutes). However, CI was still running at detection time — the staging → production pipeline for `f8fe1d4` started at 2026-08-31T02:34:08Z (run 33351077247) and completed successfully, deploying all three stages (staging, E2E smoke tests, production).

## Problem

The `pipeline-health-cron.sh` lag threshold is 15 minutes, but the CI pipeline for this repo takes ~19 minutes to complete before it can trigger the staging pipeline. This means the cron will always fire during the normal CI window for any push to main.

- **Lag threshold**: 15 minutes (fires when main is >15min ahead of prod)
- **CI duration**: ~19 minutes (run 33350101474 started 02:15:16Z, completed ~02:34:06Z)
- **Staging pipeline trigger**: 02:34:08Z (run 33351077247)
- **Gap**: The cron fires at 15min, before CI (~19min) can possibly finish

## Pattern

This is the second instance of this specific false positive type (lag threshold too short vs CI duration).

| Issue | Date | Type | Fix Applied |
|-------|------|------|-------------|
| #1358 | 2026-08-29 | Lag threshold 15min < CI ~20min | Documented in RESOLUTION_1358 — not yet applied |
| #1361 | 2026-08-31 | Lag threshold 15min < CI ~19min | This resolution |

## Evidence

- **Commit `f8fe1d4`** pushed at 2026-08-31T02:15:13Z — frontend store refactor (#1360).
- **CI run 33350101474** started at 02:15:16Z for `f8fe1d4` — took 18m50s, completed ~02:34:06Z.
- **Cron detected lag** at ~02:30:38Z (commit was ~925s old) — CI was still running.
- **Staging pipeline run 33351077247** started at 02:34:08Z — all 3 jobs succeeded:
  - ✓ Deploy to staging (1m36s)
  - ✓ Staging E2E smoke tests (54s)
  - ✓ Deploy to production (1m38s)
- **Production fully deployed** at approximately 02:38Z — no actual outage.

## Solution

Increase the lag detection threshold in `pipeline-health-cron.sh` (interstellarai.net repo) from 15 minutes to 45 minutes. This covers:
- CI duration: ~20 minutes
- Staging pipeline duration: ~5 minutes
- Buffer: ~20 minutes

```bash
# CURRENT — 15-minute threshold (fires before CI can complete)
LAG_THRESHOLD_SECONDS=900

# REQUIRED — 45-minute threshold (covers full CI + deploy pipeline + buffer)
LAG_THRESHOLD_SECONDS=2700
```

**Repository for fix**: `interstellarai.net` (not `reli`)
**File**: `ops/cron/pipeline-health-cron.sh`
**Variable**: `LAG_THRESHOLD_SECONDS`

## Related Issues

- Issue #1358 — first instance of lag-threshold false positive; fix documented but not applied
- Issues #1352, #1354, #1356 — different false positive type (HTTP 000 during Railway restart)
- Issue #1181 — precedent for documented fixes not being applied
