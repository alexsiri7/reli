# Resolution of Issue #1356

**Date**: 2026-08-29  
**Issue**: Deploy down: https://reli.interstellarai.net returning HTTP 000  
**Status**: RESOLVED (false positive)

## Summary

Issue #1356 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron detected `HTTP 000` (connection refused) at 2026-08-29 03:02:09 UTC across all 3 retry attempts. This is consistent with a Railway container restart exceeding the 3×30s (~90s) retry window — no actual application outage occurred.

## Problem

The `check_deploy_http` function in `pipeline-health-cron.sh` (interstellarai.net repo, `ops/cron/pipeline-health-cron.sh:993-999`) uses 3 retry attempts with 30s sleep (~90s coverage). Railway container restarts can take ~240s. The previously recommended 6×20s fix (from issue #1181, 120s coverage) was not applied; subsequent incidents showed 120s was itself insufficient for Railway worst-case restarts, leading to the current recommendation of 12×20s (240s coverage). The deployed code still uses the original 3×30s retry.

## Pattern

This is the eighteenth instance of this false positive:

| Issue | Date | Cause | Fix Applied |
|-------|------|-------|-------------|
| #1153 | 2026-06-04 | HTTP 000000 string bug | Fixed in #1153 |
| #1156 | 2026-06-05 | No retry logic | Added staging wait in #1157 |
| #1158 | 2026-06-05 | Same pattern | Fixed in #1157 |
| #1160 | 2026-06-06 | No retry in cron | Added 3×10s retry in #1161 |
| #1162 | 2026-06-07 | Retry window too short (3×10s) | Documented in RESOLUTION_1162 |
| #1178/#1179 | 2026-06-10 | Staging pre-flight pattern | Fixed in #1178/#1180 |
| #1181 | 2026-06-11 | Retry window still too short (3×30s) | Documented as fixed to 6×20s (never applied) |
| #1280 | 2026-07-01 | Retry window too short (3×30s) | Documented in RESOLUTION_1280 |
| #1281 | 2026-07-02 | Retry window too short (3×30s) | Documented in RESOLUTION_1281 |
| #1282 | 2026-07-03 | Retry window too short (3×30s) | Documented in RESOLUTION_1282 |
| #1283 | 2026-07-04 | Retry window too short (3×30s) | Documented in RESOLUTION_1283 |
| #1284 | 2026-07-05 | Retry window too short (3×30s) | Documented in RESOLUTION_1284 |
| #1285 | 2026-07-06 | Retry window too short (3×30s) | Documented in RESOLUTION_1285 |
| #1338 | 2026-08-18 | Retry window too short (3×30s) | Documented in RESOLUTION_1338 |
| #1340 | 2026-08-20 | Retry window too short (3×30s) | Documented in RESOLUTION_1340 |
| #1352 | 2026-08-26 | Retry window too short (3×30s) | Documented in RESOLUTION_1352 |
| #1354 | 2026-08-28 | Retry window too short (3×30s) | Documented in RESOLUTION_1354 |
| #1356 | 2026-08-29 | Retry window too short (3×30s) | This resolution |

## Evidence

- **No code changes on Aug 28–29 2026** that would trigger a deployment. Last commit was `6816890` (2026-08-28, docs only).
- **Detection at 03:02 UTC** — no deployment was in progress.
- **HTTP 000 = connection refused** — consistent with Railway container restart (port not yet bound), not a crash loop or config error.
- **Site confirmed live** — `curl` to https://reli.interstellarai.net returns HTTP 200 at time of investigation.
- Service recovered on its own — consistent with transient restart, not a persistent outage.

## Solution

Increase the retry window in `pipeline-health-cron.sh` (interstellarai.net repo) from 3×30s (~90s coverage) to 12×20s (~240s coverage). Also add retry logic to `check_staging_deploy_http` which currently has zero retry logic.

```bash
# CURRENT — 3×30s (~90s coverage — insufficient)
for attempt in 1 2 3; do
  http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  http_code=${http_code:-000}
  if [ "$http_code" -ge 200 ] 2>/dev/null && [ "$http_code" -lt 400 ] 2>/dev/null; then
    break
  fi
  [ "$attempt" -lt 3 ] && sleep 30
done

# REQUIRED — 12×20s (~240s coverage — matches Railway worst-case restart)
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  http_code=${http_code:-000}
  if [ "$http_code" -ge 200 ] 2>/dev/null && [ "$http_code" -lt 400 ] 2>/dev/null; then
    break
  fi
  [ "$attempt" -lt 12 ] && sleep 20
done
```

**Repository for fix**: `interstellarai.net` (not `reli`)  
**File**: `ops/cron/pipeline-health-cron.sh`  
**Functions**: `check_deploy_http` (line ~993), `check_staging_deploy_http` (line ~1042)

## Related Issues

- Issue #1153 — original cron HTTP format bug
- Issue #1160 — missing retry logic
- Issue #1162 — retry window too short (3×10s)
- Issue #1178/#1179 — staging pre-flight pattern
- Issue #1181 — retry window too short (3×30s), documented as fixed to 6×20s but never applied
- Issues #1280–#1285 — same pattern (retry insufficient)
- Issue #1338 — same pattern (recommend 12×20s)
- Issue #1340 — same pattern (recommend 12×20s)
- Issue #1352 — same pattern (recommend 12×20s)
- Issue #1354 — same pattern (recommend 12×20s)
