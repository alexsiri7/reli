# Investigation: Prod deploy failed on main

**Issue**: #755 (https://github.com/alexsiri7/reli/issues/755)
**Type**: BUG
**Investigated**: 2026-04-29T18:15:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Automated staging and production deploys are completely blocked until the token is rotated. |
| Complexity | LOW | No application code changes required; the fix involves rotating a secret and re-running a workflow. |
| Confidence | HIGH | CI logs explicitly state `RAILWAY_TOKEN is invalid or expired`, and history confirms this as the 4th occurrence. |

---

## Problem Statement

The production deployment pipeline failed on `main` because the `RAILWAY_TOKEN` stored in GitHub Secrets has expired. This is a recurring infrastructure incident (previously #733, #739, #742) caused by tokens being created with short TTLs instead of "No expiration".

---

## Analysis

### Root Cause / Change Rationale

The root cause is the expiration of the `RAILWAY_TOKEN` secret. While PR #757 was recently merged to increase health check frequency from weekly to daily (reducing MTTD), it does not automatically rotate the token.

### Evidence Chain

WHY: Deployment fails at "Validate Railway secrets"
↓ BECAUSE: Railway API returns `Not Authorized`
  Evidence: [Run 25105119767](https://github.com/alexsiri7/reli/actions/runs/25105119767) — `RAILWAY_TOKEN is invalid or expired`

↓ BECAUSE: The token in `secrets.RAILWAY_TOKEN` has reached its expiration date.

↓ ROOT CAUSE: Previous rotations did not select "No expiration" in the Railway dashboard.
  Evidence: Recurring failures (#733, #739, #742, #755) and documentation in `docs/RAILWAY_TOKEN_ROTATION_742.md`.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `.github/workflows/railway-token-health.yml` | N/A | VERIFY | Already updated to daily in PR #757 |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | N/A | FOLLOW | Canonical runbook for rotation |

### Integration Points

- GitHub Actions Secret `RAILWAY_TOKEN` is used by all deployment workflows.
- Railway GraphQL API endpoint `https://backboard.railway.app/graphql/v2`.

### Git History

- **Last relevant change**: `6a0d232` - 2026-04-28 - "ci: run Railway token health check daily instead of weekly (#757)"
- **Implication**: Monitoring is now robust (daily), but the actual secret must still be updated manually.

---

## Implementation Plan

### Step 1: Rotate Railway Token (Human Action Required)

**Action**: MANUAL

1. Go to https://railway.com/account/tokens.
2. Create a new token named `github-actions-permanent`.
3. **CRITICAL**: Select **Expiration: No expiration**.
4. Copy the new token.

---

### Step 2: Update GitHub Secret (Human or Agent)

**Action**: UPDATE

1. Run: `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`
2. Paste the new token when prompted.

---

### Step 3: Verify Token Health

**Action**: VERIFY

1. Run the health check workflow manually:
   ```bash
   gh workflow run railway-token-health.yml --repo alexsiri7/reli
   ```
2. Monitor the run to ensure it passes.

---

### Step 4: Unblock Deployment

**Action**: RERUN

1. Re-run the failed deployment jobs:
   ```bash
   gh run rerun 25105119767 --repo alexsiri7/reli --failed
   ```
2. Confirm that "Validate Railway secrets" passes and the deploy completes.

---

## Patterns to Follow

**From codebase - health check logic:**

```yaml
# SOURCE: .github/workflows/railway-token-health.yml
          RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
            -H "Authorization: Bearer $RAILWAY_TOKEN" \
            -H "Content-Type: application/json" \
            -d '{"query":"{me{id}}"}')
```

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| New token still has expiry | Human must double-check "No expiration" is selected in Railway UI. |
| Workflow rerun fails elsewhere | Inspect logs for unrelated flakes; the token fix only unblocks the validation step. |

---

## Validation

### Automated Checks

```bash
# Verify the token via the health check workflow
gh workflow run railway-token-health.yml
```

### Manual Verification

1. Check Railway dashboard to confirm the token is "Active" and has "No expiration".
2. Confirm the "Validate Railway secrets" step in CI turns green.

---

## Scope Boundaries

**IN SCOPE:**
- Rotating `RAILWAY_TOKEN` secret.
- Verifying the new token unblocks CI.

**OUT OF SCOPE:**
- Changes to application code.
- Changes to deployment workflow logic (already improved in #757).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-29T18:15:00Z
- **Artifact**: `/mnt/ext-fast/reli/artifacts/runs/f1aad5a4c565a621f7bd50a32068e729/investigation.md`
