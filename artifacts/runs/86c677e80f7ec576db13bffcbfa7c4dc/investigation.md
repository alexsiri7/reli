# Investigation: Main CI red — Deploy to staging (24th RAILWAY_TOKEN expiration)

**Issue**: #811 (https://github.com/alexsiri7/reli/issues/811)
**Type**: BUG
**Investigated**: 2026-04-30T22:45:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The staging→production pipeline fails on every push to `main` at the staging validate step, blocking all auto-promotions to prod; no production data is at risk and a clear (human-only) workaround exists. |
| Complexity | LOW | Resolution is a single human action — rotate the `RAILWAY_TOKEN` GitHub secret. No code changes required; the validate step and runbook are already correct. |
| Confidence | HIGH | Run log explicitly emits `RAILWAY_TOKEN is invalid or expired: Not Authorized`, the validate step at `.github/workflows/staging-pipeline.yml:32-58` is designed to surface exactly this case, and the same failure has now recurred 24 times. Run `git log --grep "RAILWAY_TOKEN expiration" --oneline` on `main` for the full chain (most recent: #810 = 23rd; #808 = 22nd; #804/#805 = 21st; #800/#801 = 20th). |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at the `Validate Railway secrets` step because the `RAILWAY_TOKEN` GitHub Actions secret has expired again. Railway's GraphQL API rejects the token with `Not Authorized`, the deploy step is skipped, and downstream `Staging E2E smoke tests` and `Deploy to production` jobs are skipped as well — which is what `pipeline-health-cron.sh` reports as "Main CI red: Deploy to staging". **Agents cannot fix this** — rotation requires a human with railway.com dashboard access.

---

## Analysis

### Root Cause / Change Rationale

This is the **24th recurrence** of the same `RAILWAY_TOKEN` expiration. The validate step is working as designed; it is correctly surfacing an expired credential. The structural driver of the recurrence cycle (per prior investigations and Railway's published guidance at `docs.railway.com/integrations/api`) is most likely the use of an **account-tier** token (user-bound, easily revoked) and/or a default short-lived TTL on each rotation. Railway officially recommends **workspace tokens** with no expiration for "Team CI/CD" — they are a drop-in replacement (same `Authorization: Bearer` header, same `{me{id}}` validation works unchanged).

Notably, the failing run was triggered on SHA `3f1d6e60c7f6a55fa7d1b58d9e6665e6d668e512`, which is the merge commit of PR #809 — the investigation for the **22nd** recurrence. The 23rd investigation (#810/#812, merged as `b5d05ef`) has since landed on `main`, and that merge will fail the staging pipeline in exactly the same way until the token is rotated.

### Evidence Chain

WHY: The "Staging → Production Pipeline" run #25186694297 ends `failure`, and downstream jobs (`Staging E2E smoke tests`, `Deploy to production`) were `skipped`.
↓ BECAUSE: The `Deploy to staging` job's `Validate Railway secrets` step exited 1.
  Evidence: `gh run view 25186694297` — step "Validate Railway secrets" `X`, downstream "Deploy staging image to Railway" / "Wait for staging health" `-` (skipped).

↓ BECAUSE: A `{me{id}}` probe to `https://backboard.railway.app/graphql/v2` returned no `data.me.id`.
  Evidence: run log line `RAILWAY_TOKEN is invalid or expired: Not Authorized`.

↓ BECAUSE: That probe is the exact-by-design check at `.github/workflows/staging-pipeline.yml:49-58` — it calls Railway's GraphQL `me` query and exits 1 when the response lacks `.data.me.id`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret is expired (or revoked). Rotation requires a human with railway.com dashboard access; no agent can perform it.
  Evidence: `CLAUDE.md` — "Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com."

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| GitHub Actions secret `RAILWAY_TOKEN` | n/a | ROTATE (human-only) | Create a new Railway **workspace** token with **"No expiration"** and update the secret. |

No source files require modification. The validate step at `.github/workflows/staging-pipeline.yml:32-58` (and the prod equivalent later in the same file) is functioning correctly.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging validate step that emitted the failure (this run).
- `.github/workflows/staging-pipeline.yml:60-88` — staging deploy step, uses the same `RAILWAY_TOKEN`.
- `.github/workflows/staging-pipeline.yml` (prod validate step) — will fail next prod deploy with the same error if token isn't rotated.
- `.github/workflows/railway-token-health.yml` — periodic health check that monitors the token.

### Git History

- The validate step was introduced by commit `3dfb995` ("fix: add Railway API token auth check to deploy pre-flight (#738)") and refined in `0040535` ("fix: use curl -sf consistently in Railway token validate steps (#744)"). Behavior is correct.
- Prior recurrence investigations are listed by `git log --grep "RAILWAY_TOKEN expiration" --oneline` on `main` (authoritative). Most recent: `b5d05ef` (#810, 23rd); `3f1d6e6` (#808, 22nd); `10577df` (#804, 21st); `d5e2233` (#805, 21st); `0275146` (#800, 20th); `83a2f93` (#801, 20th).
- **Implication**: This is not a regression. The CI is doing its job; the credential expired again.

---

## Implementation Plan

> ⚠️ **No code change. This issue requires a human to rotate the Railway API token.**
> Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. Doing so is a Category 1 error.

### Step 1 (HUMAN): Create a new Railway **workspace** token with no expiration

1. Sign in at https://railway.com/account/tokens.
2. Choose the **workspace** tab (NOT account, NOT project).
   - **Why workspace**: Railway officially recommends workspace tokens for "Team CI/CD" (per `docs.railway.com/integrations/api`). Workspace tokens are not bound to a single user account, eliminating the most likely root cause of the 24-cycle recurrence (account-token-tied-to-user revocation).
   - Workspace tokens are a drop-in replacement: `Authorization: Bearer $RAILWAY_TOKEN` and the `{me{id}}` validation in the workflow both work unchanged.
3. Name it `github-actions-permanent`.
4. **Set expiration to "No expiration"** — do not accept the default TTL. Several past rotations used short-lived defaults, which is part of why this keeps recurring.

### Step 2 (HUMAN): Update the GitHub Actions secret

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# paste the new workspace token when prompted
```

### Step 3 (HUMAN): Re-run the failed CI

```bash
gh run rerun 25186694297 --repo alexsiri7/reli --failed

# Fallback if the run is stale:
gh run list --repo alexsiri7/reli --status failure --limit 1 \
  --json databaseId --jq '.[0].databaseId' \
  | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
```

### Step 4 (HUMAN): Close issue #811 once CI is green

The full runbook lives at `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Patterns to Follow

Mirror prior recurrence handling — file an investigation that points the human at the runbook, do not fabricate a rotation receipt. The full chain of prior recurrences is authoritative via:

```bash
git log --grep "RAILWAY_TOKEN expiration" --oneline
```

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_811.md` claiming success. | Explicitly forbidden by `CLAUDE.md`; this artifact does not create such a file. |
| Human rotates the token but with a default short TTL again. | Step 1 emphasizes **"No expiration"** — accepting the default TTL is part of the recurrence root cause. |
| Human creates an **account** token (user-bound, easily revoked). | Step 1 explicitly calls for a **workspace** token. |
| Human creates a **project** token (uses `Project-Access-Token` header, not `Authorization: Bearer`; `{me{id}}` validation will fail immediately even with a fresh token). | Step 1 explicitly calls for a **workspace** token. Picking project token would require workflow code changes — out of scope here. |
| Prod deploy job will hit the same failure on next deploy. | The rotation fixes both staging and prod since both jobs read the same `RAILWAY_TOKEN` secret. |
| Recurrence pattern (24 times) suggests systemic process problem. | Out of scope for this investigation per Polecat Scope Discipline. Prior investigations recommend follow-ups: (a) update `docs/RAILWAY_TOKEN_ROTATION_742.md` to specify workspace-token tier; (b) consider a Railway-side automation/alternate auth approach. File those separately if desired. |

---

## Validation

### Automated Checks

After human rotates the token:

```bash
# Re-run the failed pipeline
gh run rerun 25186694297 --repo alexsiri7/reli --failed

# Watch the rerun
gh run watch --repo alexsiri7/reli
```

### Manual Verification

1. New run of `staging-pipeline.yml` reaches `Deploy staging image to Railway` without the `RAILWAY_TOKEN is invalid or expired` error.
2. Staging health probe (`/healthz`) returns `{"status":"ok"}` within the 20-attempt loop at `.github/workflows/staging-pipeline.yml:90-104`.
3. `Deploy to production` job (gated on `deploy-staging` + `staging-e2e`) completes successfully.
4. `railway-token-health.yml` next scheduled run reports green.

---

## Scope Boundaries

**IN SCOPE:**
- Document the recurrence (24th) and direct the human to the rotation runbook.
- Reaffirm the recommendation: workspace-tier token with no expiration.

**OUT OF SCOPE (do not touch):**
- Performing the rotation (agents cannot — see `CLAUDE.md`).
- Creating a `.github/RAILWAY_TOKEN_ROTATION_811.md` "completion receipt" — explicitly forbidden.
- Editing `.github/workflows/staging-pipeline.yml` — the validate step is correct; the credential is the problem.
- Editing `docs/RAILWAY_TOKEN_ROTATION_742.md` — that's a separate documentation issue.
- Refactoring the pipeline to avoid Railway tokens — separate scoping decision.

---

## Metadata

- **Investigated by**: Claude (claude-opus-4-7[1m])
- **Timestamp**: 2026-04-30T22:45:00Z
- **Artifact**: `artifacts/runs/86c677e80f7ec576db13bffcbfa7c4dc/investigation.md`
