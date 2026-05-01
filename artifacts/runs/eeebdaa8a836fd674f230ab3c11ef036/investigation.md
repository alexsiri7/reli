# Investigation: Main CI red — Deploy to staging (#843) — RAILWAY_TOKEN expired (37th occurrence, 3rd pickup)

**Issue**: #843 (https://github.com/alexsiri7/reli/issues/843)
**Type**: BUG (infrastructure / secret rotation — agent-unactionable)
**Investigated**: 2026-05-01T19:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The Staging → Production pipeline is fully blocked at the `Validate Railway secrets` gate — no code can ship to staging or production until the token is rotated; however, the live application is unaffected and there is no data loss, so not CRITICAL. |
| Complexity | LOW | The fix is a single GitHub Actions secret update by a human via railway.com — zero code changes, zero workflow edits; the only "complexity" is the human handoff. |
| Confidence | HIGH | The workflow run summary shows the exact failure string `RAILWAY_TOKEN is invalid or expired: Not Authorized` emitted by the `Validate Railway secrets` step at `.github/workflows/staging-pipeline.yml:53-57`, which is the same Railway GraphQL `{me{id}}` probe that has fired 36 times before in this repo. |

---

## Problem Statement

The "Staging → Production Pipeline" run [25215295472](https://github.com/alexsiri7/reli/actions/runs/25215295472) failed at the `Validate Railway secrets` step on commit `c42a83b` with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. This is the **37th** RAILWAY_TOKEN-expiration investigation in this repository and the **3rd pickup** of #843 — the first two archon attempts each timed out (labeled `archon:in-progress` for ~7211s and ~8984s respectively) without producing a live run or a linked PR (see issue comments at 2026-05-01T15:30:50Z and 2026-05-01T18:00:50Z). The token lives in GitHub Actions secrets and **cannot be rotated by an agent**; it requires a human with railway.com access.

---

## Analysis

### Root Cause

The `RAILWAY_TOKEN` GitHub Actions secret is rejected by Railway's API. The validation step at `.github/workflows/staging-pipeline.yml:32-58` calls Railway's GraphQL `{me{id}}` endpoint to probe the token; Railway returns `Not Authorized`, so the workflow exits 1 before any deploy mutation runs. No application or pipeline-config bug exists — the deploy code path is healthy and would succeed with a valid token. The same single (un-rotated) token expiration is the root cause for the open `Prod deploy failed on main` series #841 (closed, 34th + 35th investigations), #845 (closed, 36th investigation), #843 (this one), and #847 (filed at 2026-05-01T18:00:25Z, currently in flight). Each new merge produces a new SHA, which triggers a new run, which trips the same gate, which spawns a new auto-cron issue — the cycle will not stop until a human rotates the secret.

### Evidence Chain

WHY: `Staging → Production Pipeline` run 25215295472 ended in `failure`.
↓ BECAUSE: The `Deploy to staging` job exited 1 at the `Validate Railway secrets` step.
  Evidence: `gh run view 25215295472 --repo alexsiri7/reli` —

  ```
  X Deploy to staging in 5s (ID 73934260732)
    ✓ Set up job
    ✓ Run actions/checkout@v4
    ✓ Resolve commit SHA
    X Validate Railway secrets
    - Deploy staging image to Railway        (skipped)
    - Wait for staging health                (skipped)
  - Staging E2E smoke tests in 0s            (skipped)
  - Deploy to production in 0s               (skipped)
  ```

↓ BECAUSE: The token-probe call to Railway's GraphQL API returned an auth error.
  Evidence: Run annotation (`.github#29`):

  ```
  X RAILWAY_TOKEN is invalid or expired: Not Authorized
  ```

↓ ROOT CAUSE: The `RAILWAY_TOKEN` repository secret is no longer accepted by Railway's API.
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` —

  ```yaml
  RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
    -H "Authorization: Bearer $RAILWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"{me{id}}"}')
  if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
    MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
    echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
    echo "Rotate the token — see DEPLOYMENT_SECRETS.md Token Rotation section."
    exit 1
  fi
  ```

  The annotation message body matches the validator's format string verbatim, with `$MSG` resolved to `Not Authorized` (Railway's standard rejection from the `{me{id}}` probe).

### Affected Files

**No application/pipeline code changes are required.** The fix is in GitHub Actions secret storage (managed via railway.com → GitHub repo settings), which is outside this repository.

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (GitHub repo secret `RAILWAY_TOKEN`) | n/a | ROTATE (human) | New Railway API token, pasted into Actions secrets. See `docs/RAILWAY_TOKEN_ROTATION_742.md`. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | n/a | REFERENCE | Existing canonical runbook for the rotation procedure — do not modify. |
| `artifacts/runs/eeebdaa8a836fd674f230ab3c11ef036/investigation.md` | n/a | CREATE (this PR) | This investigation artifact, mirroring the format of the prior 36 expirations. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the gate that just failed).
- `.github/workflows/staging-pipeline.yml:60-95` — `Deploy staging image to Railway` (skipped on this run; will run on the next push once the token is valid).
- `.github/workflows/railway-token-health.yml` — periodic health probe; expected to remain failing until rotation completes.

### Git History

- **Pipeline workflow last touched**: `git log -- .github/workflows/staging-pipeline.yml` — the validate step is unchanged across recent commits; the failure is data-driven (the token), not a regression in the workflow.
- **Recent investigations of the same failure mode** (most recent first):
  - #845 — 36th RAILWAY_TOKEN expiration, 2nd pickup (commit `bd17591`, PR #846, merged 2026-05-01T18:30Z)
  - #841 — 35th RAILWAY_TOKEN expiration, 2nd pickup (commit `212718c`, PR #844)
  - #841 — 34th RAILWAY_TOKEN expiration, prod-deploy framing (commit `c42a83b`, PR #842)
  - #833 — 32nd RAILWAY_TOKEN expiration, 3rd pickup (commit `da29247`, PR #840)
  - #758 — deploy-down stale duplicate of #836 (commit `76b58f5`, PR #839)
  - #836 — 33rd RAILWAY_TOKEN expiration, 2nd pickup (commit `ee9d0fb`, PR #838)
- **Implication**: This is a long-standing operational issue, not a regression. The deploy SHA `c42a83b` is the merge SHA of PR #842 (the 34th investigation), so the failure detected in run 25215295472 is the very next CI run after that PR merged — the token still wasn't rotated, so the new run failed exactly as expected. Subsequent merges (PR #844, PR #846) produced their own failed runs, which were filed as #845 and #847.
- **Current open siblings** (`gh issue list --search "Prod deploy failed in:title" --state open`):
  - #843 (this one, created 2026-05-01T13:30:33Z, 3rd pickup)
  - #847 (created 2026-05-01T18:00:25Z, in flight)

---

## Implementation Plan

**Agent action — none on the codebase.** Per `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
> When CI fails with `RAILWAY_TOKEN is invalid or expired`:
> 1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> 2. File a GitHub issue or send mail to mayor with the error details.
> 3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

### Step 1: Human rotates the token

**Owner**: Repository maintainer with railway.com access.
**Action**: Follow `docs/RAILWAY_TOKEN_ROTATION_742.md` end to end:

1. Log into railway.com.
2. Generate a new API token with the same scope as the previous one (account or team-scoped, with permissions to deploy to the staging service/environment).
3. Update GitHub Actions secret `RAILWAY_TOKEN` at https://github.com/alexsiri7/reli/settings/secrets/actions.
4. Re-run the failed pipeline: `gh run rerun 25215295472 --failed --repo alexsiri7/reli` (or push a no-op commit to `main`).
5. Confirm `Validate Railway secrets` passes and the deploy proceeds through `Deploy staging image to Railway` → `Wait for staging health` → `Staging E2E smoke tests` → `Deploy to production`.

### Step 2: Verify and close the issues

Once the rerun is green:
- Comment on #843 (and #847) with the successful run URL.
- Remove the `archon:in-progress` label.
- Close #843 and #847 (and any other open `Prod deploy failed` siblings filed in the meantime).

### Step N: No tests to add

Token rotation is an out-of-band operational task; nothing to assert in the codebase. The existing `.github/workflows/railway-token-health.yml` workflow already monitors token validity on a schedule.

---

## Patterns to Follow

This investigation deliberately mirrors the structure of the prior 36 RAILWAY_TOKEN investigations (most recently commit `bd17591` for #845 / PR #846). The pattern, per `CLAUDE.md`, is:

1. Confirm the failure string verbatim from the workflow log/annotations.
2. State plainly that the agent cannot rotate the token.
3. Point the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`.
4. Do **not** create or modify any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — that has historically been a Category 1 error (claiming success on an action the agent did not perform).
5. Do **not** edit `.github/workflows/staging-pipeline.yml` — the validate step is correctly designed and the failure mode is informative, not a bug in the workflow.

```yaml
# SOURCE: .github/workflows/staging-pipeline.yml:53-57
# The validator that emitted the annotation we saw on this run:
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  echo "Rotate the token — see DEPLOYMENT_SECRETS.md Token Rotation section."
  exit 1
fi
```

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a "rotation done" doc (Category 1 error per `CLAUDE.md`) | Investigation explicitly forbids this; only the canonical rotation runbook is referenced. |
| Pickup cron re-fires while human is mid-rotation | Issue is labeled `archon:in-progress`; the comment trail (3 pickup re-queues so far) makes the state visible. The 3rd-pickup framing in this PR signals to a future reviewer that the cycle is the bottleneck, not the investigation. |
| Token-health workflow keeps paging until rotation | Expected and self-resolving once the secret is rotated; no action needed. |
| Multiple stale duplicate "Prod deploy failed" issues open simultaneously (#843 + #847) | Both are caused by the same un-rotated token. After rotation, close all open siblings with a pointer to the successful rerun. Optionally treat #847 as a stale duplicate of #843 (or vice versa) per the `#758 → #836` precedent (commit `76b58f5`). |
| Other secrets (`RAILWAY_STAGING_SERVICE_ID`, `RAILWAY_STAGING_ENVIRONMENT_ID`, `RAILWAY_STAGING_URL`) are also missing | The validate step would name them in a separate `Missing required secrets:` error. The actual log says `Not Authorized` (token rejected by Railway), so the other secrets are present — only the token needs rotation. |
| Future regression where the validator stops emitting a clear error | Out of scope for this bead; would be filed separately. The current emission is correct and matched verbatim to the annotation. |

---

## Validation

### Automated Checks

After human rotation:

```bash
gh run rerun 25215295472 --failed --repo alexsiri7/reli
gh run watch <new-run-id> --repo alexsiri7/reli
```

The pipeline must reach `Deploy to production` and complete with conclusion `success`.

### Manual Verification

1. The new run's `Validate Railway secrets` step shows no `Not Authorized` annotation.
2. `Deploy staging image to Railway` posts a `serviceInstanceUpdate` response without `errors`.
3. `Wait for staging health` returns 200 from the staging URL's healthcheck.
4. `Staging E2E smoke tests` job runs and passes.
5. `Deploy to production` job runs and passes.
6. The production URL serves the new SHA (`c42a83b` — or whatever SHA is current at rerun time).
7. `archon:in-progress` removed and #843 (and #847) closed.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnose the deploy failure on run 25215295472.
- Produce this investigation artifact and post it as a comment on #843.
- Direct the human to the rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`).
- Open a docs-only PR linking to this investigation, mirroring the prior 36-investigation pattern.

**OUT OF SCOPE (do not touch):**
- Rotating `RAILWAY_TOKEN` (agent cannot do this — railway.com requires human auth).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming the rotation is done (explicitly forbidden by `CLAUDE.md`; Category 1 error).
- Modifying `docs/RAILWAY_TOKEN_ROTATION_742.md` (it's the canonical runbook; changes belong in their own bead).
- Modifying `.github/workflows/staging-pipeline.yml` — the validate step is correctly designed and the failure mode is informative, not a bug in the workflow.
- Any "automation" to refresh the token (would require storing a long-lived Railway credential elsewhere — out of scope and a separate security discussion).
- Closing #847 or merging it with #843 — handled by a separate dedup bead following the `#758 → #836` precedent if a human chooses.

---

## Metadata

- **Investigated by**: Claude (claude-opus-4-7[1m])
- **Timestamp**: 2026-05-01T19:10:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/eeebdaa8a836fd674f230ab3c11ef036/investigation.md`
- **Failed run**: https://github.com/alexsiri7/reli/actions/runs/25215295472
- **Failed SHA**: `c42a83bbbb48a1279663b2ca823594d964dce985` (= merge SHA of PR #842, the 34th investigation)
- **Failure annotation**: `RAILWAY_TOKEN is invalid or expired: Not Authorized`
- **Series position**: 37th RAILWAY_TOKEN expiration, 3rd pickup of #843
- **Sibling open issues at time of investigation**: #847
