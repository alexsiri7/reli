# Investigation: Prod deploy failed on main (#860)

**Issue**: #860 (https://github.com/alexsiri7/reli/issues/860)
**Type**: BUG
**Investigated**: 2026-05-02

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | The `Validate Railway secrets` pre-flight gates every deploy step; with it failing, no staging or production release can land until the token is rotated — this is an authentication outage on the deploy pipeline, not a code defect. |
| Complexity | LOW | No source files change. Recovery is a 3-step manual rotation in the Railway dashboard plus a `gh secret set` and a re-run; the bug exists exclusively in external secret state. |
| Confidence | HIGH | The failed step's stderr (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) is unambiguous, the validator code is intact, and this is the 41st occurrence of the identical pattern with a documented runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`). |

---

## Problem Statement

The `Validate Railway secrets` step in the `Deploy to staging` job (workflow `Staging → Production Pipeline`, run [25242236208](https://github.com/alexsiri7/reli/actions/runs/25242236208)) failed because Railway's GraphQL endpoint rejected `RAILWAY_TOKEN` with `Not Authorized` when probing `{ me { id } }`. Because this validation gates the actual `serviceInstanceUpdate` deploy mutation, no staging/production release can land until the GitHub Actions secret `RAILWAY_TOKEN` is rotated by a human with railway.com access.

---

## Analysis

### Root Cause / Change Rationale

The token stored in the GitHub Actions secret `RAILWAY_TOKEN` is no longer accepted by Railway's GraphQL API. The workflow's pre-flight authentication probe (`.github/workflows/staging-pipeline.yml:49-58`) correctly catches this and refuses to proceed, which is the intended fail-fast behaviour — there is no code regression here. The fix lives entirely outside the repo: a human must mint a new account-scoped Railway API token and overwrite the GitHub secret.

### Evidence Chain

WHY: Why did the prod deploy run fail?
↓ BECAUSE: The `Deploy to staging` job exited 1 in the `Validate Railway secrets` step.
  Evidence: workflow log — `##[error]Process completed with exit code 1.` at `2026-05-02T03:04:50.0824485Z`.

↓ BECAUSE: Why did that step exit 1?
  Evidence: log line `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-02T03:04:50.0814013Z`.

↓ BECAUSE: Why was the token rejected?
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` posts `{me{id}}` to `https://backboard.railway.app/graphql/v2` with `Authorization: Bearer $RAILWAY_TOKEN` and inspects `.data.me.id`. Railway returned `errors[0].message == "Not Authorized"` instead of a `me.id`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an account-scoped Railway API token that has been revoked or has expired (or, per `web-research.md` Finding #2, may have been minted with a workspace bound rather than "No workspace" — silent rejection mode).
  Evidence: Identical failure mode to 40 prior closed issues, all resolved by rotating the token via `docs/RAILWAY_TOKEN_ROTATION_742.md` with no source change. The canonical prior-occurrence list is reproducible by `gh issue list --repo alexsiri7/reli --search '"RAILWAY_TOKEN" "Not Authorized"' --state closed --json number -q '.[].number'`; commit-history numbering pins #850 = 38th, #854 = 39th, #858 = 40th, #860 = 41st.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none — code) | — | — | No source/workflow change is required or appropriate. |
| GitHub secret `RAILWAY_TOKEN` | n/a | ROTATE (human) | Replace with a freshly-issued account-scoped Railway API token (No expiration, No workspace). |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the failing pre-flight)
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` step (gated by the validate step; would fail equivalently if reached, since it uses the same `Authorization: Bearer $RAILWAY_TOKEN`)
- `.github/workflows/railway-token-health.yml` — independent token-health probe (daily `0 9 * * *` cron); will also fail on the same secret until rotated
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical rotation runbook
- `DEPLOYMENT_SECRETS.md` — CI secret setup reference (linked from the validator's error message)

### Git History

- **Failing commit**: `3570101` ("docs: investigation for issue #854 (39th RAILWAY_TOKEN expiration, 2nd pickup) (#857)") — docs-only, cannot have caused this.
- **Validator step provenance**: `git log --oneline .github/workflows/staging-pipeline.yml` shows the `Validate Railway secrets` pattern is well-established; it has not been modified in any recent commit.
- **Implication**: Not a regression. This is recurring secret-rotation toil — the token issued during the previous rotation has now been revoked or has expired again.

---

## Implementation Plan

> **Agent-side: NO CODE CHANGES.** Per `CLAUDE.md` § "Railway Token Rotation":
>
> > Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. File a GitHub issue or send mail to mayor with the error details. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
>
> Producing such a marker file would be a Category 1 error.

### Step 1: Document the failure (agent action)

**File**: `artifacts/runs/31b45d722d1961ae59edfe9b72e7cf08/investigation.md`
**Action**: CREATE (this file)

Captures the failing run URL, the exact error string, the rotation runbook pointer, and the prior-occurrence count so the human has a one-stop summary.

### Step 2: Post investigation comment on #860 (agent action)

Use `gh issue comment 860` with a formatted summary so the human can act without opening Actions logs.

### Step 3: Human rotation per runbook (NOT an agent action)

Per `docs/RAILWAY_TOKEN_ROTATION_742.md` (with the additional setting flagged by `web-research.md` Finding #2):

1. Sign in at https://railway.com/account/tokens.
2. Create a new **account-scoped** API token. Required settings:
   - Name: `github-actions-permanent` (or `gh-actions-2026-05-02`).
   - **Expiration: No expiration** (critical — do not accept the default TTL).
   - **Workspace: No workspace** (per Railway support thread; workspace-bound tokens silently fail the `me { id }` probe).
3. Update the GitHub Actions secret:
   ```bash
   gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
   # Paste the new token when prompted
   ```
4. Verify token before re-deploying:
   ```bash
   gh workflow run railway-token-health.yml --repo alexsiri7/reli
   gh run watch <new-run-id> --repo alexsiri7/reli
   ```
5. Re-run the failed pipeline:
   ```bash
   gh run rerun 25242236208 --repo alexsiri7/reli --failed
   ```
6. Confirm the `Validate Railway secrets` step passes; close #860 with the green run URL.
7. (Optional but useful) Revoke the previous token in Railway after the new one verifies green, to limit overlap.

### Step 4: Verify (after human rotation)

- `Validate Railway secrets` step succeeds (`me.id` returned).
- `Deploy staging image to Railway` proceeds and `serviceInstanceUpdate` returns no `errors`.
- Health check on `RAILWAY_STAGING_URL` reports 200.
- `railway-token-health.yml` next scheduled run is green.

---

## Patterns to Follow

This issue's documentation pattern mirrors the prior 40 instances. Reference the most recent pair (issue #858, PR #859) for the docs-only investigation pattern.

The runbook itself (`docs/RAILWAY_TOKEN_ROTATION_742.md`) is the canonical procedure — do not duplicate or fork it.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires #860 before rotation completes | Issue is labelled `archon:in-progress`; the pickup cron skips while that label is present. Do not strip the label until the deploy goes green. |
| Cron re-fires #860 after PR merges (label cleared early) | Prior issues (#854) saw this; harmless but wasteful. Out of scope for this fix — track separately if it recurs. |
| New token rotates green but next deploy still fails | Likely a separate issue (e.g., revoked service ID, image registry permissions). Re-investigate from logs; do **not** assume same root cause. |
| Token created with workspace bound (silent rejection) | Web-research Finding #2: ensure the Railway dashboard token is created with **"No workspace"** selected, otherwise `me { id }` returns `Not Authorized` even on a fresh token. |
| Human believes agent rotated the token because of a `.github/RAILWAY_TOKEN_ROTATION_*.md` file | Do **not** create such a file. The runbook is the only canonical rotation doc. |
| Pickup cron fires for #860 after this PR — generating a duplicate investigation | Standard pattern: the next investigator should add a `(2nd pickup)` suffix and reuse the same artifact directory style as #850 (#853, #856). |

---

## Validation

### Automated Checks

```bash
# Agent-side: docs-only diff. Standard suite is vacuously passing.
# The actual signal lives in the deploy pipeline, which only goes green
# AFTER the human rotates the token:
gh workflow run railway-token-health.yml --repo alexsiri7/reli   # post-rotation sanity check
gh run rerun 25242236208 --repo alexsiri7/reli --failed
gh run watch <new-run-id> --repo alexsiri7/reli
```

### Manual Verification (post-rotation)

1. The re-run of [25242236208](https://github.com/alexsiri7/reli/actions/runs/25242236208) reaches the `Deploy staging image to Railway` step and exits 0.
2. `RAILWAY_STAGING_URL` returns the freshly-deployed SHA (`3570101`) on `/api/version` (or equivalent health endpoint).
3. `railway-token-health.yml` next scheduled run reports green.

---

## Scope Boundaries

**IN SCOPE (agent):**
- Investigate the failed run, identify the recurring root cause.
- Produce this investigation artifact under `artifacts/runs/31b45d722d1961ae59edfe9b72e7cf08/`.
- Post a summary comment on issue #860 directing the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**OUT OF SCOPE (do not touch):**
- Rotating the Railway API token (human-only — railway.com access required).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` "rotation done" marker (Category 1 error per `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml`, `railway-token-health.yml`, or `docs/RAILWAY_TOKEN_ROTATION_742.md` — none are wrong; the secret is.
- Adding the "No workspace" instruction to the runbook (separate scope — file as a follow-up issue if pursued; per Polecat Scope Discipline, surface as mail to mayor rather than expanding this PR).
- Designing token-expiration mitigations (longer-lived tokens, automatic rotation, OIDC federation) — Railway doesn't support OIDC today (web-research Finding #6); file separate issues if pursued.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/31b45d722d1961ae59edfe9b72e7cf08/investigation.md`
- **Failing run**: https://github.com/alexsiri7/reli/actions/runs/25242236208
- **Failing SHA**: `3570101c6de497ab5171c7a2c1fdd70baa411a57`
- **Prior occurrences**: 40 (this is #41)
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md`
- **Companion artifact**: `artifacts/runs/31b45d722d1961ae59edfe9b72e7cf08/web-research.md`
