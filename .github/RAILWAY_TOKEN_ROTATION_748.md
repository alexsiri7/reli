# Railway Token Rotation — Issue #748

**Date**: 2026-04-27
**Status**: Pending manual credential rotation
**Issue**: #748

## Summary

The `RAILWAY_TOKEN` GitHub secret has expired again. The Railway API returns `Not Authorized` when the staging-pipeline.yml workflow attempts to validate the token.

## Root Cause

Railway API tokens have a finite lifetime. The token set during a previous rotation has now expired. This is a recurring issue (#733, #739, #742 all had identical root cause).

## Required Action

A human with access to railway.com and GitHub must:

1. Generate a new no-expiry (maximum lifetime) API token at https://railway.com/account/tokens
2. Run: `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the new token
3. Re-run the failed CI job (run ID at incident time: 25016653713):
   `gh run list --workflow=staging-pipeline.yml --repo alexsiri7/reli --status=failure --limit=1`
   then: `gh run rerun <run-id> --repo alexsiri7/reli --failed`
4. Confirm the "Validate Railway secrets" step passes

## Long-term Mitigation

Create a Railway token with maximum lifetime or implement automated refresh to break this cycle.
