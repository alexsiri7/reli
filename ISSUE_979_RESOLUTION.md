# Issue #979 Resolution Report

## Status: RESOLVED ✅

Issue #979 "Main CI red: Staging E2E smoke tests" was investigated and found to be **already fixed**.

## Root Cause Analysis

The staging E2E smoke test `GET /api/health returns detailed status` was failing with HTTP 401 because:

1. The `/api/health` endpoint was auth-gated in commit `fc3be06` (SEC-036)
2. The smoke test in `frontend/e2e/smoke.spec.ts` was calling the endpoint without authentication
3. The `require_user` dependency was returning 401 to the unauthenticated request

## Fix Applied

This issue was fully resolved by commit `46d6b9a` (PR #977), which updated the smoke test to:
- Remove the unauthenticated `/api/health` test expecting HTTP 200
- Add `/api/health` to the auth-gated API endpoints group, verifying it correctly returns 401/403

## CI Status Post-Fix

All CI runs since the fix was merged show green status:
- ✅ Commit `46d6b9a` — SUCCESS
- ✅ Commit `a7caff1` — SUCCESS
- ✅ Commit `52c7757` — SUCCESS
- ✅ All commits from `38d3126` onward — SUCCESS

## Test Validation Results

- Tests: 374 passed, 0 failed
- Build: ✅ Successful
- Lint: ✅ Pass (0 errors)
- Type check: ✅ Pass

## Conclusion

No further action required. Issue #979 can be closed as the problem is fully resolved and CI is operational.

**Investigation Date**: 2026-05-15T19:00:00Z
**Verification Date**: 2026-05-15T19:44:00Z
