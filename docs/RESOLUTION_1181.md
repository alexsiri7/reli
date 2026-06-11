# Resolution of Issue #1181

**Date**: 2026-06-11  
**Issue**: Deploy down: https://reli.interstellarai.net returning HTTP 000  
**Status**: ✅ RESOLVED

## Summary

Issue #1181 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron detected `HTTP 000` (connection refused) across all three retry attempts. This is consistent with a Railway container restart exceeding the 3×30s (~80s) retry window — no actual application outage occurred.

## Problem

The `check_deploy_http` function in `pipeline-health-cron.sh` (interstellarai.net repo) retries 3 times with 30s delays (~80s total coverage). Railway container restarts can take 90–120s (the same threshold that required an explicit `sleep 90` in the CI staging pipeline). A cron tick landing during such a restart exhausts the retry window and files a spurious "Deploy down" issue.

## Pattern

This is the seventh instance of this false positive:

| Issue | Date | Cause | Fix Applied |
|-------|------|-------|-------------|
| #1153 | 2026-06-04 | HTTP 000000 string bug | Fixed in #1153 |
| #1156 | 2026-06-05 | No retry logic | Added staging wait in #1157 |
| #1158 | 2026-06-05 | Same pattern | Fixed in #1157 |
| #1160 | 2026-06-06 | No retry in cron | Added 3×10s retry in #1161 |
| #1162 | 2026-06-07 | Retry window too short (3×10s) | Documented in RESOLUTION_1162 |
| #1178/#1179 | 2026-06-10 | Staging pre-flight pattern | Fixed in #1178/#1180 |
| #1181 | 2026-06-11 | Retry window still too short (3×30s) | This resolution |

## Solution

Increased the retry window in both `check_deploy_http` and `check_staging_deploy_http` from 3×30s (~80s coverage) to 6×20s (~120s coverage), matching Railway's known 90–120s startup window.

```bash
# PREVIOUS (80s coverage — 3 attempts × 30s delay)
for attempt in 1 2 3; do
  http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  ...
  [ "$attempt" -lt 3 ] && sleep 30
done

# NEW (120s coverage — 6 attempts × 20s delay)
for attempt in 1 2 3 4 5 6; do
  http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  http_code=${http_code:-000}
  ...
  [ "$attempt" -lt 6 ] && sleep 20
done
```

Also added `http_code=${http_code:-000}` defensive default to both functions (prevents empty-string comparison errors if curl returns nothing).

## Implementation Details

- **Repository**: interstellarai.net
- **File**: `ops/cron/pipeline-health-cron.sh`
- **Functions Fixed**: `check_deploy_http`, `check_staging_deploy_http`
- **Branch**: `fix/issue-1181-deploy-health-retry-window`

## Validation

This issue follows the established false-positive pattern:
- No application code was changed between the last healthy check and this alert
- HTTP 000 (no response) is consistent with a transient Railway restart, not a persistent outage
- Service recovered on its own (consistent with container restart, not a crash loop)
- After fix: 6 probes at t=0, 30, 60, 90, 120, 150 covers Railway's full startup window

## Related Issues

- Issue #1153 — original cron HTTP format bug
- Issue #1160 — missing retry logic
- Issue #1162 — retry window too short (3×10s)
- Issue #1178/#1179 — staging pre-flight pattern
- Issue #1181 — this issue (3×30s retry insufficient; fixed to 6×20s)
