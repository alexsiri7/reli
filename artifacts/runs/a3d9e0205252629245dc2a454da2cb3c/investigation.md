# Investigation: Prod deploy failed on main (#868)

**Issue**: #868 (https://github.com/alexsiri7/reli/issues/868)
**Type**: BUG
**Investigated**: 2026-05-02

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | The `Validate Railway secrets` pre-flight gates every step of the staging→prod deploy pipeline; with it failing, no release can land until the token is rotated — this is an authentication outage on the deploy pipeline, not a code defect. |
| Complexity | LOW | No source files change. Recovery is a manual rotation in the Railway dashboard plus `gh secret set` and a workflow re-run; the bug exists exclusively in external secret state. |
| Confidence | HIGH | The failed step's stderr (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) is unambiguous, the validator code is unchanged since `0040535` (#744), and this is the 45th occurrence of the identical pattern with a documented runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`). |

---

## Problem Statement

The `Validate Railway secrets` step in the `Deploy to staging` job (workflow `Staging → Production Pipeline`, run [25244367347](https://github.com/alexsiri7/reli/actions/runs/25244367347)) failed because Railway's GraphQL endpoint rejected `RAILWAY_TOKEN` with `Not Authorized` when probing `{ me { id } }`. Because this validation gates the actual `serviceInstanceUpdate` deploy mutation, no staging/production release can land until the GitHub Actions secret `RAILWAY_TOKEN` is rotated by a human with railway.com access.

This is the **45th** instance of this identical authentication failure on the prod deploy pipeline, and (continuing the prior investigation's counting convention) the **5th same-day rotation** after #860, #862, #864, and #866 — all filed earlier on 2026-05-02. The day's full set of RAILWAY_TOKEN-rooted issues also includes #858 (03:00 UTC) and the earlier #854 (filed under the "Main CI red" framing).

**Verify the same-day cadence** (re-derives the count from GitHub state, no privileges required):

```bash
gh issue list --repo alexsiri7/reli --state all --search 'RAILWAY_TOKEN created:2026-05-02' --json number,title,createdAt
# Returns #854, #858, #860, #862, #864, #866, #868 — all created 2026-05-02 UTC.
```

**Verify the prior-occurrence numbering ladder** (re-derives `#850=38th … #866=44th` from commit history):

```bash
git log --oneline --grep='RAILWAY_TOKEN expiration' | head -10
# Most recent first; counts back to #850 (38th) at the bottom of the list.
```

---

## Analysis

### Root Cause / Change Rationale

The token stored in the GitHub Actions secret `RAILWAY_TOKEN` is no longer accepted by Railway's GraphQL API. The workflow's pre-flight authentication probe (`.github/workflows/staging-pipeline.yml:32-58`) correctly catches this and refuses to proceed, which is the intended fail-fast behaviour — there is no code regression here. The fix lives entirely outside the repo: a human must mint a new account-scoped Railway API token and overwrite the GitHub secret.

The deploy whose failure was filed as this issue ran against SHA `b5ad0e6f6bacfcff80fc117beefab1d324b523ac` — itself a docs-only commit (the investigation merge for #864). That deploy was triggered at `2026-05-02T05:05:02Z`, only ~5 minutes after the prior investigation merged and ~30 minutes before #868 was filed by `pipeline-health-cron.sh`. The compressed cadence of same-day failures (now 5 in this chain, 7 if counting #854 and #858) strongly suggests one of:

- (a) The post-#866 token rotation has not yet been performed by a human — every merge in the meantime hits the same dead token.
- (b) The freshly-minted tokens are again being bound to a workspace or given a TTL, causing near-immediate rejection.

Either way, the action is the same: re-mint with **No expiration** and **No workspace** explicitly set; do not re-run the deploy until the new token has verified green via `railway-token-health.yml`.

### Evidence Chain

WHY: Why did the prod deploy run fail?
↓ BECAUSE: The `Deploy to staging` job exited 1 in the `Validate Railway secrets` step.
  Evidence: workflow log — `##[error]Process completed with exit code 1.` at `2026-05-02T05:05:00.2007476Z`.

↓ BECAUSE: Why did that step exit 1?
  Evidence: log line `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-02T05:05:00.1998546Z`.

↓ BECAUSE: Why was the token rejected?
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` posts `{me{id}}` to `https://backboard.railway.app/graphql/v2` with `Authorization: Bearer $RAILWAY_TOKEN` and inspects `.data.me.id`. Railway returned `errors[0].message == "Not Authorized"` instead of a `me.id`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an account-scoped Railway API token that has been revoked, has expired, or was minted with a workspace bound (silent rejection per Railway support).
  Evidence: Identical failure mode to 44 prior issues, all resolved by rotating the token via `docs/RAILWAY_TOKEN_ROTATION_742.md` with no source change. Commit-history numbering pins #850 = 38th, #854 = 39th, #858 = 40th, #860 = 41st, #862 = 42nd, #864 = 43rd, #866 = 44th, #868 = 45th.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none — code) | — | — | No source/workflow change is required or appropriate. |
| GitHub secret `RAILWAY_TOKEN` | n/a | ROTATE (human) | Replace with a freshly-issued account-scoped Railway API token (No expiration, No workspace). |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the failing pre-flight)
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` step (gated by the validate step; would fail equivalently if reached, since it uses the same `Authorization: Bearer $RAILWAY_TOKEN`)
- `.github/workflows/railway-token-health.yml` — independent token-health probe (daily cron); will also fail on the same secret until rotated
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical rotation runbook
- `DEPLOYMENT_SECRETS.md` — CI secret setup reference (linked from the validator's error message)

### Git History

- **Failing SHA**: `b5ad0e6f6bacfcff80fc117beefab1d324b523ac` ("docs: investigation for issue #864 (43rd RAILWAY_TOKEN expiration) (#865)") — docs-only, cannot have caused this.
- **Validator step provenance**: `git log --oneline .github/workflows/staging-pipeline.yml` shows the most recent edit was `0040535` ("fix: use curl -sf consistently in Railway token validate steps (#744)"); the auth-check pattern itself was added in `3dfb995` (#738). Neither is recent — the validator has been stable for many cycles.
- **Implication**: Not a regression. This is recurring secret-rotation toil — the token in `RAILWAY_TOKEN` was already rejected at the time of the b5ad0e6 merge-triggered deploy (which itself was the merge of the prior #866 investigation). Either no rotation has happened since #866, or the just-rotated token was again misconfigured.

---

## Implementation Plan

> **Agent-side: NO CODE CHANGES.** Per `CLAUDE.md` § "Railway Token Rotation":
>
> > Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. File a GitHub issue or send mail to mayor with the error details. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
>
> Producing such a marker file would be a Category 1 error.

### Step 1: Document the failure (agent action)

**File**: `artifacts/runs/a3d9e0205252629245dc2a454da2cb3c/investigation.md`
**Action**: CREATE (this file)

Captures the failing run URL, the exact error string, the rotation runbook pointer, and the prior-occurrence count so the human has a one-stop summary.

### Step 2: Post investigation comment on #868 (agent action)

Use `gh issue comment 868` with a formatted summary so the human can act without opening Actions logs. Emphasize the same-day-repeat angle (5th in the chain after #860/#862/#864/#866) and the "No workspace / No expiration" mint settings.

### Step 3: Human rotation per runbook (NOT an agent action)

Per `docs/RAILWAY_TOKEN_ROTATION_742.md` (with the additional setting flagged by prior web-research):

1. Sign in at https://railway.com/account/tokens.
2. Create a new **account-scoped** API token. Required settings:
   - Name: `gh-actions-2026-05-02e` (fifth in today's chain; disambiguates from the #860, #862, #864, and #866 rotations).
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
   gh run rerun 25244367347 --repo alexsiri7/reli --failed
   ```
6. Confirm the `Validate Railway secrets` step passes; close #868 with the green run URL.
7. (Optional but useful) Revoke the previous token in Railway after the new one verifies green, to limit overlap.

### Step 4: Verify (after human rotation)

- `Validate Railway secrets` step succeeds (`me.id` returned).
- `Deploy staging image to Railway` proceeds and `serviceInstanceUpdate` returns no `errors`.
- Health check on `RAILWAY_STAGING_URL` reports 200.
- `railway-token-health.yml` next scheduled run is green.

---

## Patterns to Follow

This issue's documentation pattern mirrors the prior 44 instances. Reference the most recent pair (issue #866, PR #867 — commit `7a22aaa`) for the docs-only investigation pattern — same artifact layout under `artifacts/runs/<hash>/investigation.md`.

The runbook itself (`docs/RAILWAY_TOKEN_ROTATION_742.md`) is the canonical procedure — do not duplicate or fork it.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires #868 before rotation completes | Issue is labelled `archon:in-progress`; the pickup cron skips while that label is present. Do not strip the label until the deploy goes green. |
| Cron re-fires #868 after PR merges (label cleared early) | Prior issues (#854, #850) saw this; harmless but wasteful. Out of scope for this fix — track separately if it recurs. |
| Same-day chain (5th in a row after #860, #862, #864, #866; 7th if #854 and #858 are counted) | Strongly suggests either (a) no human rotation has happened yet despite prior issues, or (b) the freshly-minted tokens are being bound to a workspace (silent rejection) or given a TTL. **Re-mint with No workspace AND No expiration explicitly set in the Railway dashboard.** If a sixth same-day rotation is still needed, escalate to Railway support — token churn this fast is not normal. |
| New token rotates green but next deploy still fails | Likely a separate issue (e.g., revoked service ID, image registry permissions). Re-investigate from logs; do **not** assume same root cause. |
| Human believes agent rotated the token because of a `.github/RAILWAY_TOKEN_ROTATION_*.md` file | Do **not** create such a file. The runbook is the only canonical rotation doc. |
| Pickup cron fires for #868 after this PR — generating a duplicate investigation | Standard pattern: the next investigator should add a `(2nd pickup)` suffix and reuse the same artifact directory style as #850 (#853, #856). |
| Five consecutive same-day rotations (or seven by the broader count) suggests a systemic issue with how tokens are being minted, or a race between rotation and pending workflow_run triggers | Out of scope for this fix (per Polecat Scope Discipline). Surface as mail to mayor: a follow-up should investigate whether the runbook's "No workspace / No expiration" steps are being followed and consider adding a screenshot or copy-paste UI checklist, plus a brief "wait until any in-flight workflow_run has been requeued post-rotation" note. |

---

## Validation

### Automated Checks

```bash
# Agent-side: docs-only diff. Standard suite is vacuously passing.
# The actual signal lives in the deploy pipeline, which only goes green
# AFTER the human rotates the token:
gh workflow run railway-token-health.yml --repo alexsiri7/reli   # post-rotation sanity check
gh run rerun 25244367347 --repo alexsiri7/reli --failed
gh run watch <new-run-id> --repo alexsiri7/reli
```

### Manual Verification (post-rotation)

1. The re-run of [25244367347](https://github.com/alexsiri7/reli/actions/runs/25244367347) reaches the `Deploy staging image to Railway` step and exits 0.
2. `RAILWAY_STAGING_URL` returns the freshly-deployed SHA (`b5ad0e6` or newer) on `/api/version` (or equivalent health endpoint).
3. `railway-token-health.yml` next scheduled run reports green.

---

## Scope Boundaries

**IN SCOPE (agent):**
- Investigate the failed run, identify the recurring root cause.
- Produce this investigation artifact under `artifacts/runs/a3d9e0205252629245dc2a454da2cb3c/`.
- Post a summary comment on issue #868 directing the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**OUT OF SCOPE (do not touch):**
- Rotating the Railway API token (human-only — railway.com access required).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` "rotation done" marker (Category 1 error per `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml`, `railway-token-health.yml`, or `docs/RAILWAY_TOKEN_ROTATION_742.md` — none are wrong; the secret is.
- Adding the "No workspace" instruction to the runbook (separate scope — file as a follow-up issue if pursued; per Polecat Scope Discipline, surface as mail to mayor rather than expanding this PR).
- Designing token-expiration mitigations (longer-lived tokens, automatic rotation, OIDC federation) — Railway doesn't support OIDC today; file separate issues if pursued.
- Investigating why same-day rotations are needed 5–7x in one day (separate scope — surface as mail to mayor).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02
- **Artifact**: `artifacts/runs/a3d9e0205252629245dc2a454da2cb3c/investigation.md`
- **Failing run**: https://github.com/alexsiri7/reli/actions/runs/25244367347
- **Failing SHA**: `b5ad0e6f6bacfcff80fc117beefab1d324b523ac`
- **Prior occurrences**: 44 (this is #45; 5th in the same-day chain after #860, #862, #864, #866)
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md`
