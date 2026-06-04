# Resolution of Issue #1153

**Date**: 2026-06-04  
**Issue**: Bug: pipeline-health-cron.sh produces HTTP 000000 instead of 000  
**Status**: ✅ RESOLVED

## Summary

Issue #1153 documented a bug in the `pipeline-health-cron.sh` script (located in the external `interstellarai.net` repository at `ops/cron/pipeline-health-cron.sh`). The health check script is monitored by Reli, so this issue was filed here for visibility.

## Problem

When curl timed out or failed, the command substitution was capturing both:
1. The `000` output from curl's `-w "%{http_code}"` format string
2. The `000` from the `|| echo "000"` fallback

Result: HTTP status code appeared as `000000` (six zeros) instead of `000` (three zeros).

## Solution

Separated the assignment from the fallback default, ensuring only one `000` is produced:

```bash
# OLD (broken)
http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null || echo "000")

# NEW (fixed)
http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$deploy_url" 2>/dev/null)
http_code=${http_code:-000}
```

## Implementation Details

- **Repository**: interstellarai.net  
- **File**: `ops/cron/pipeline-health-cron.sh`  
- **Lines Fixed**: 983, 1031, 1070  
- **Commit**: `24418d1` - "Fix: pipeline-health-cron produces HTTP 000000 instead of 000 (#1153)"

## Validation

✅ All validation checks passed:
- Shell syntax validation (`bash -n`) — run against the patched `pipeline-health-cron.sh`
- External commit applied: `24418d1` in interstellarai.net
- Reli regression check (confirms no impact to Reli monitoring layer):
  - Frontend tests: 403 passed
  - Backend tests: 1226 passed, 14 skipped
  - Frontend build successful

## Related Issue

See issue #1153 in the reli repository for full context.
