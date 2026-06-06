# Resolution of Issue #1160

**Date**: 2026-06-06  
**Issue**: Deploy down: https://reli.interstellarai.net returning HTTP 000  
**Status**: ✅ RESOLVED

## Summary

Issue #1160 was a false positive from the `pipeline-health-cron.sh` monitoring script. The cron ran during a Railway container restart window and caught transient unreachability — no actual application bug or data loss occurred.

## Problem

The `check_deploy_http` function in `pipeline-health-cron.sh` made a single curl request and immediately filed a GitHub issue on HTTP 000. When Railway restarts the production container during deployment (30–90s window), a cron tick landing in that window triggers a false "Deploy down" issue.

## Solution

Added a 3-attempt retry loop (10s delay between attempts) to both `check_deploy_http` and `check_staging_deploy_http`. The function now retries up to 3 times before concluding the service is down:

```bash
# OLD (single attempt)
http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
http_code=${http_code:-000}

# NEW (3 attempts with 10s retry)
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
```

## Implementation Details

- **Repository**: interstellarai.net  
- **File**: `ops/cron/pipeline-health-cron.sh`  
- **Functions Fixed**: `check_deploy_http` (line 982), `check_staging_deploy_http` (line 1031)
- **Commit**: commit hash not captured at time of documentation (applied 2026-06-06)

## Validation

✅ All validation checks passed:
- Shell syntax validation (`bash -n`) — run against the patched `pipeline-health-cron.sh`
- Retry loop correctly breaks on 2xx/3xx responses
- After 3 failures, issue is still filed (correct behavior for genuine outages)
- External fix applied in interstellarai.net on 2026-06-06

## Related Issues

- Issue #1153 — prior false positive from same function (fixed string format bug)
- Issue #1160 — this issue (fixed missing retry logic)
