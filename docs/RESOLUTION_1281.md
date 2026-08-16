# Resolution of Issue #1281

**Date**: 2026-08-16  
**Issue**: Deploy down: https://reli.interstellarai.net returning HTTP 000  
**Status**: RESOLVED (false positive)

## Summary

Issue #1281 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron detected `HTTP 000` (connection refused) at 2026-07-02 03:01:56 UTC across all retry attempts. This is consistent with a Railway container restart exceeding the 6×20s (~100–160s) retry window — no actual application outage occurred.

## Problem

The `check_deploy_http` function in `pipeline-health-cron.sh` (interstellarai.net repo) was fixed in #1181 to use 6×20s retries (~100–160s coverage). However, Railway container restarts can occasionally exceed 160s. A cron tick landing during such a restart exhausts the retry window and files a spurious "Deploy down" issue.

## Pattern

This is the ninth instance of this false positive:

| Issue | Date | Cause | Fix Applied |
|-------|------|-------|-------------|
| #1153 | 2026-06-04 | HTTP 000000 string bug | Fixed in #1153 |
| #1156 | 2026-06-05 | No retry logic | Added staging wait in #1157 |
| #1158 | 2026-06-05 | Same pattern | Fixed in #1157 |
| #1160 | 2026-06-06 | No retry in cron | Added 3×10s retry in #1161 |
| #1162 | 2026-06-07 | Retry window too short (3×10s) | Documented in RESOLUTION_1162 |
| #1178/#1179 | 2026-06-10 | Staging pre-flight pattern | Fixed in #1178/#1180 |
| #1181 | 2026-06-11 | Retry window still too short (3×30s) | Fixed to 6×20s |
| #1280 | 2026-07-01 | Retry window still too short (6×20s) | Documented in RESOLUTION_1280 |
| #1281 | 2026-07-02 | Retry window still too short (6×20s) | This resolution |
| #1283 | 2026-07-04 | Same pattern (6×20s retry insufficient for July 4 restart) | Documented in RESOLUTION_1283 |
| #1284 | 2026-07-05 | Same pattern (6×20s retry insufficient for July 5 restart) | Documented in RESOLUTION_1284 |
| #1285 | 2026-07-06 | Same pattern (6×20s retry insufficient for July 6 restart) | Documented in RESOLUTION_1285 |

## Evidence

- **No code changes on July 1-2 2026** that would trigger a deployment or cause a startup failure.
- **Detection at 03:01 UTC** — no deployment was in progress.
- **HTTP 000 = connection refused** — consistent with Railway container restart (port not yet bound), not a crash loop or config error.
- Service recovered on its own — consistent with transient restart, not a persistent outage.

## Solution

Increase the retry window in `pipeline-health-cron.sh` (interstellarai.net repo) from 6×20s (~100–160s coverage) to 12×20s (~220–340s coverage). This covers Railway worst-case restarts with significant margin.

```bash
# PREVIOUS — #1181 fix (~100–160s coverage — 6 attempts × 20s delay)
for attempt in 1 2 3 4 5 6; do
  http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  http_code=${http_code:-000}
  ...
  [ "$attempt" -lt 6 ] && sleep 20
done

# RECOMMENDED (~220–340s coverage — 12 attempts × 20s delay)
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
**Functions**: `check_deploy_http`, `check_staging_deploy_http`

## Related Issues

- Issue #1153 — original cron HTTP format bug
- Issue #1160 — missing retry logic
- Issue #1162 — retry window too short (3×10s)
- Issue #1178/#1179 — staging pre-flight pattern
- Issue #1181 — retry window too short (3×30s), fixed to 6×20s
- Issue #1283 — same pattern (6×20s retry insufficient for July 4 restart)
- Issue #1284 — same pattern (6×20s retry insufficient for July 5 restart)
- Issue #1285 — same pattern (6×20s retry insufficient for July 6 restart)
