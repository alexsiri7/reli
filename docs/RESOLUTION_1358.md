# Resolution of Issue #1358

**Date**: 2026-08-29
**Issue**: Prod deploy lagging main
**Status**: RESOLVED (false positive)

## Summary

Issue #1358 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron detected that main (`d6b0928`, committed 2026-08-29T04:43:11Z) had been ahead of production for >15 minutes. However, CI was still running at the time — the staging → production pipeline for `d6b0928` started at 2026-08-29T05:03:45Z (run 33235269565) and completed successfully, deploying all three stages (staging, E2E smoke tests, production).

## Problem

The `pipeline-health-cron.sh` lag threshold is 15 minutes, but the CI pipeline for this repo takes ~20 minutes to complete before it can trigger the staging pipeline. This means the cron will always fire during the normal CI window for any push to main.

- **Lag threshold**: 15 minutes (fires when main is >15min ahead of prod)
- **CI duration**: ~20 minutes (run 33234489859 started 04:43:14Z, staging pipeline triggered at 05:03:45Z)
- **Gap**: The cron runs before CI can possibly finish

## Pattern

This is the first instance of this specific false positive type (lag threshold too short vs CI duration). Previous false positives were of a different type (HTTP 000 during Railway container restart).

## Evidence

- **Commit `d6b0928`** pushed at 2026-08-29T04:43:11Z — docs-only commit (no breaking changes).
- **CI run 33234489859** started at 04:43:14Z for `d6b0928` — succeeded.
- **Cron detected lag** at ~05:00:30Z (commit was ~1039s old) — CI was still running.
- **Staging pipeline run 33235269565** started at 05:03:45Z — all 3 jobs succeeded:
  - ✓ Deploy to staging (1m35s)
  - ✓ Staging E2E smoke tests (57s)
  - ✓ Deploy to production (1m40s)
- **Production fully deployed** at approximately 05:09Z — well within normal parameters.

## Solution

Increase the lag detection threshold in `pipeline-health-cron.sh` (interstellarai.net repo) from 15 minutes to 45 minutes. This covers:
- CI duration: ~20 minutes
- Staging pipeline duration: ~10 minutes
- Buffer: ~15 minutes

```bash
# CURRENT — 15-minute threshold (fires before CI can complete)
# check if main has been ahead of prod for >15 minutes
LAG_THRESHOLD_SECONDS=900

# REQUIRED — 45-minute threshold (covers full CI + deploy pipeline)
LAG_THRESHOLD_SECONDS=2700
```

**Repository for fix**: `interstellarai.net` (not `reli`)
**File**: `ops/cron/pipeline-health-cron.sh`
**Variable/logic**: lag detection threshold for prod-behind-main check

## Related Issues

- Issues #1352, #1354, #1356 — different false positive type (HTTP 000 during Railway restart)
- Issue #1181 — retry window documented as fixed but never applied (precedent for fixes not landing)
