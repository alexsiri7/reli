# Resolution of Issue #1380

**Date**: 2026-09-04
**Issue**: Prod deploy lagging main
**Status**: RESOLVED (false positive)

## Summary

Issue #1380 was a false positive from the `pipeline-health-cron.sh` monitoring script.
The cron detected that main (`c4ee3f0`, committed 2026-09-03T04:47:43Z) had been ahead
of production for ~117768s (~32.7 hours). However, the Staging → Production Pipeline for
`c4ee3f0` completed successfully on 2026-09-03T05:14:46Z (run 33717768717) — all three
stages passed (deploy-staging, staging-e2e, deploy-production). Production was deployed
on Sep 3, not "lagging".

## Problem

The cron script reported "Latest prod deploy: a4d9a135 at 2026-08-26T05:16:16Z" despite
`c4ee3f0` being deployed successfully on Sep 3. This is a new variant of the false-positive
pattern: the cron's "latest prod deploy" detection returned a stale SHA.

A likely contributing factor: the deploy-production job created TWO GitHub deployment
records for `c4ee3f0`:
- ID 6237406340: created 05:13:02Z, status stuck at `in_progress` (orphaned)
- ID 6237424724: created 05:14:42Z, status `success`

If the cron resolves "latest prod deploy" by finding the most recently-created deployment
that is in `in_progress` or filters incorrectly, it may bypass the actual latest success.

## Pattern

Previous false positive types:
1. **HTTP 000 type** (issues #1153–#1378): Railway container restart exceeds cron retry window
2. **Lag threshold type** (issues #1358, #1361): 15-min threshold < ~20-min CI duration
3. **Stale SHA detection type** (this issue, #1380): cron returns old prod SHA despite new successful deploy

## Evidence

- **Site confirmed live** — GH Actions run 33717768717 deployed `c4ee3f0` to production
  at 2026-09-03T05:14:46Z; all health checks passed.
- **GitHub deployment API** — `GET /repos/alexsiri7/reli/deployments?environment=production`
  returns deployment 6237424724 (c4ee3f0, status=success, 2026-09-03T05:14:42Z).
- **No outage** — no user-visible impact at time of investigation.

## Solution

Two fixes needed in `interstellarai.net/ops/cron/pipeline-health-cron.sh`:

1. **Existing fix (HTTP 000 type)**: Increase retry window from 3×30s to 12×20s (~240s)
2. **Existing fix (lag threshold type)**: Increase `LAG_THRESHOLD_SECONDS` from 900 to 2700
3. **New fix (stale SHA detection)**: When querying GitHub deployments for "latest prod deploy",
   skip any records with `in_progress` status and select the most-recent `success` record only.
   Fetch deployment statuses and verify `state=success` before treating a deployment record
   as "the latest prod deploy":
   ```bash
   # Fetch deployments, then for each find the latest with state=success
   DEPLOYMENTS=$(gh api "repos/$REPO/deployments?environment=production&per_page=10" --jq '.[].id')
   LATEST_SUCCESS_ID=""
   for DEP_ID in $DEPLOYMENTS; do
     STATUS=$(gh api "repos/$REPO/deployments/$DEP_ID/statuses" --jq '.[0].state')
     if [ "$STATUS" = "success" ]; then
       LATEST_SUCCESS_ID=$DEP_ID
       break
     fi
   done
   # LATEST_SUCCESS_ID now holds the most recent successful deployment
   ```

**Repository for fix**: `interstellarai.net` (not `reli`)
**File**: `ops/cron/pipeline-health-cron.sh`

## Related Issues

- Issue #1153 — original cron HTTP format bug
- Issues #1160–#1378 — HTTP 000 false positive type (22 instances total)
- Issue #1358 — first lag-threshold false positive
- Issue #1361 — second lag-threshold false positive
- Issue #1181 — precedent for documented fixes never being applied
