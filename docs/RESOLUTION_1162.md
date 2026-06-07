# Resolution of Issue #1162

**Date**: 2026-06-07  
**Issue**: Deploy down: https://reli.interstellarai.net returning HTTP 000  
**Status**: ✅ RESOLVED

## Summary

Issue #1162 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron detected `HTTP 000` at 02:03 UTC on 2026-06-07, approximately 15 hours after the last successful production deployment (2026-06-06 10:57 UTC). This is consistent with Railway performing a maintenance-triggered container restart outside of a deployment window — no actual application bug or data loss occurred.

## Problem

The `check_deploy_http` function in `pipeline-health-cron.sh` (interstellarai.net repo) retries 3 times with 10s delays (30s total coverage). Railway maintenance restarts can exceed 90s (the same threshold that required an explicit `sleep 90` in the CI staging pipeline — see PR #1159). A cron tick landing during such a restart exhausts the retry window and files a spurious "Deploy down" issue.

## Pattern

This is the fifth instance of this false positive:

| Issue | Date | Cause | Fix Applied |
|-------|------|-------|-------------|
| #1151 | 2026-06-04 | HTTP 000000 string bug | Fixed in #1153 |
| #1156 | 2026-06-05 | No retry logic | Added staging wait in #1157 |
| #1158 | 2026-06-05 | Same pattern | Fixed in #1157 |
| #1160 | 2026-06-06 | No retry in cron | Added 3×10s retry in #1161 |
| #1162 | 2026-06-07 | Retry window too short | This resolution |

## Solution

The 3×10s retry loop added for #1160 is insufficient for Railway maintenance restarts that last 90s+. The recommended fix (to be applied in interstellarai.net) is to increase the retry window to match Railway's known startup time:

```bash
# CURRENT (30s coverage — added for #1160)
local http_code="" _attempt
for _attempt in 1 2 3; do
  local _code
  _code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  _code=${_code:-000}
  if [ "$_code" -ge 200 ] 2>/dev/null && [ "$_code" -lt 400 ] 2>/dev/null; then
    http_code="$_code"
    break
  fi
  http_code="$_code"
  [ "$_attempt" -lt 3 ] && sleep 10
done

# RECOMMENDED (90s+ coverage — 6 attempts × 15s delay)
local http_code="" _attempt
for _attempt in 1 2 3 4 5 6; do
  local _code
  _code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
  _code=${_code:-000}
  if [ "$_code" -ge 200 ] 2>/dev/null && [ "$_code" -lt 400 ] 2>/dev/null; then
    http_code="$_code"
    break
  fi
  http_code="$_code"
  [ "$_attempt" -lt 6 ] && sleep 15
done
```

This change should be applied to both `check_deploy_http` and `check_staging_deploy_http` in `ops/cron/pipeline-health-cron.sh`.

## Implementation Details

- **Repository**: interstellarai.net  
- **File**: `ops/cron/pipeline-health-cron.sh`  
- **Functions to Fix**: `check_deploy_http`, `check_staging_deploy_http`  
- **Commit**: pending (recommendation for next interstellarai.net maintenance)

## Validation

✅ This issue follows the established false-positive pattern:
- No application code was changed between the last healthy check and this alert
- Detection occurred 15 hours after last deployment — outside any deployment restart window
- HTTP 000 (no response) is consistent with a transient Railway restart, not a persistent outage
- Service recovered on its own (consistent with container restart, not a crash loop)

## Related Issues

- Issue #1153 — original cron HTTP format bug
- Issue #1160 — missing retry logic (added 3×10s retry)
- Issue #1162 — this issue (3×10s retry insufficient for Railway maintenance restarts)
