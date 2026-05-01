# Investigation: Main CI red: Deploy to staging (33rd RAILWAY_TOKEN expiration)

**Issue**: #836 (https://github.com/alexsiri7/reli/issues/836)
**Type**: BUG
**Investigated**: 2026-05-01T05:15:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The `Deploy to staging` job in run `25202388806` (SHA `3db8f1b` on `main`) fails at `Validate Railway secrets` and the rest of the staging-pipeline (`Deploy staging image`, `Wait for staging health`, `Staging E2E`, `Deploy to production`) is `skipped`, blocking all auto-deploys; HIGH rather than CRITICAL because a documented human-only rotation runbook exists (`docs/RAILWAY_TOKEN_ROTATION_742.md`) and prod is not yet down — only the deploy gate is. |
| Complexity | LOW | A single human credential action — rotate the `RAILWAY_TOKEN` GitHub Actions secret. No code, workflow, or config edit is required. |
| Confidence | HIGH | The job log emits the exact branch the validator surfaces (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`; this is the 33rd identical-shape recurrence after 32 prior cycles (#832/#833, #828/#829, #824/#825, #821, #820, #818, …). |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` is failing at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked) again. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the validator step exits 1, and every downstream job — staging deploy, staging health, staging E2E, and `Deploy to production` — is skipped. **Agents cannot fix this** — rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

This is the 33rd RAILWAY_TOKEN expiration on `main`. The immediate cause is the same as the prior 32 occurrences: the personal-account token stored in GHA secret `RAILWAY_TOKEN` has been silently invalidated by Railway, causing the validator's `{me{id}}` probe to fail. The structural cause — token-class mismatch between env-var name and validator — is unchanged from prior cycles and is explicitly out-of-scope for this bead per the Polecat Scope Discipline rule.

### Evidence Chain

```
WHY: Run 25202388806 conclusion is failure; Deploy to production is skipped.
↓ BECAUSE: Deploy to staging → Validate Railway secrets exited with code 1.
  Evidence: ##[error]Process completed with exit code 1. at 2026-05-01T04:35:00.11Z

↓ BECAUSE: Railway GraphQL {me{id}} probe returned no data.me.id.
  Evidence: ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized

↓ ROOT CAUSE (immediate): The RAILWAY_TOKEN GitHub Actions secret has expired/been revoked.
  Evidence: .github/workflows/staging-pipeline.yml:49-58 — validator issues
  Authorization: Bearer $RAILWAY_TOKEN against {me{id}} and exits 1 on missing data.me.id.

↓ ROOT CAUSE (structural, recurring): Token-class mismatch between env-var name and validator.
  The validator only accepts personal/account tokens; project tokens require the
  Project-Access-Token header, and workspace tokens reject {me{id}}. Personal tokens are
  silently revoked via Railway's OAuth refresh-token rotation — hence the 33-cycle pattern.
  Out-of-scope for this bead.
```

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| GitHub Actions secret `RAILWAY_TOKEN` | n/a (out-of-tree) | UPDATE (human) | Rotate to a new personal/account Railway token with **No expiration** |
| `.github/workflows/staging-pipeline.yml` | 32-58 | NO CHANGE | Validator step that surfaces the failure — already correct for personal tokens |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | — | NO CHANGE | Existing human runbook — the operator follows this, not the agent |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` (this is what fails).
- `.github/workflows/staging-pipeline.yml:60-99` — `Deploy staging image` and `Wait for staging health` consume `RAILWAY_TOKEN` after validation passes.
- `.github/workflows/staging-pipeline.yml` (production-deploy job) — gated on staging success; currently `skipped`.
- `.github/workflows/railway-token-health.yml` — independent recurring liveness probe of the same secret; expected to flip green after rotation.

### Git History

- **Validator introduced**: a4bb03c — "fix: Configure missing Railway secrets for deploy pipeline (#726)"
- **Runbook introduced**: 6f4202a — "docs: investigate CI failure — expired Railway token (#742) (#743)"
- **Most recent identical-shape recurrence**: 3db8f1b — "docs: investigation for issue #833 (32nd RAILWAY_TOKEN expiration) (#834)"
- **Implication**: This is a **long-standing, structural recurrence**, not a regression. Each cycle is an artifact of Railway's silent personal-token rotation policy applied to a token class the validator was never designed to handle on a long horizon.

---

## Implementation Plan

### Step 1: Human credential rotation (out-of-tree)

**File**: GitHub Actions secret `RAILWAY_TOKEN` (no repository file)
**Action**: UPDATE (human)

**Required action (human only):**

1. Go to https://railway.com/account/tokens
2. Create a new **personal/account** token (NOT a project token, NOT a workspace token)
   - Name: `github-actions-permanent-<date>`
   - **Expiration: No expiration** (do not accept any default TTL)
3. Update the GHA secret:

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted
```

**Why**: The validator at `.github/workflows/staging-pipeline.yml:49-58` issues `Authorization: Bearer $RAILWAY_TOKEN` against the `{me{id}}` GraphQL query, which only resolves for personal/account tokens. A project or workspace token will fail this validator immediately.

> ⚠️ **Per `CLAUDE.md`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_836.md` receipt** claiming rotation is done. That is a Category 1 error.

---

### Step 2: Re-run the failed CI

**Action**: human or agent, after Step 1

```bash
# Re-run the specific failed run
gh run rerun 25202388806 --repo alexsiri7/reli --failed

# Fallback if the run is too stale to rerun: push an empty commit to main
git commit --allow-empty -m "chore: kick CI after RAILWAY_TOKEN rotation" && git push
```

**Why**: `workflow_run`-triggered staging pipelines do not auto-restart on secret rotation. Either rerun the failed jobs or push a no-op to trigger a fresh `staging-pipeline.yml` run.

---

### Step 3: Close the issue

After CI is green, close #836 with a comment referencing the rotation timestamp.

---

## Patterns to Follow

**From codebase — the validator step (no change needed, just for reference):**

```yaml
# SOURCE: .github/workflows/staging-pipeline.yml:32-58
# Pattern: personal-token validator using {me{id}}
- name: Validate Railway secrets
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
    ...
  run: |
    ...
    RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
      -H "Authorization: Bearer $RAILWAY_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"query":"{me{id}}"}')
    if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
      MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
      echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
      ...
      exit 1
    fi
```

This shape is correct and does not need to change. The fix is the secret value, not the workflow.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Operator picks a project or workspace token | Step 1 explicitly calls for **personal/account**; project tokens require `Project-Access-Token` header (not `Bearer`) and would fail the existing `{me{id}}` query. |
| Operator accepts a default TTL (1d/7d) | Step 1 explicitly says **No expiration**; otherwise we file the 34th identical issue next week. |
| `gh run rerun` is rejected because run is stale | Fallback in Step 2 — push an empty commit to `main` to retrigger `staging-pipeline.yml`. |
| Sibling issue exists for the same run | None today — `gh issue list --search "Main CI red"` shows #836 alone for run `25202388806`; #833 is from a prior run. |
| Agent attempts to "fix" by writing a `.github/RAILWAY_TOKEN_ROTATION_836.md` receipt | Forbidden by `CLAUDE.md > Railway Token Rotation` — Category 1 error. Investigation only. |
| Structural fix (validator/token-class swap) attempted in this bead | Out-of-scope per Polecat Scope Discipline. File a separate bead/issue for the durable fix. |

---

## Validation

### Automated Checks (post-rotation)

```bash
gh run rerun 25202388806 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN
```

### Manual Verification

1. `Validate Railway secrets` step in `Deploy to staging` job exits 0 (`{me{id}}` returns a non-empty `data.me.id`).
2. `Deploy staging image to Railway` and `Wait for staging health` complete successfully.
3. `Deploy to production` job runs (no longer `skipped`) and `${RAILWAY_PRODUCTION_URL}/healthz` returns `{"status":"ok"}`.
4. `.github/workflows/railway-token-health.yml` next scheduled run goes green.
5. Issue #836 is closed; no new sibling issue is filed by `pipeline-health-cron.sh` on the next main push.

---

## Scope Boundaries

**IN SCOPE:**
- Document the failure mode, evidence chain, and affected workflow lines.
- Direct the human operator to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the runbook.
- Post a GitHub comment on #836 with the implementation plan.

**OUT OF SCOPE (do not touch):**
- Rotating the `RAILWAY_TOKEN` secret itself (human-only — `CLAUDE.md`).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file claiming rotation is done (Category 1 error per `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml` — the validator is correct for the chosen token class.
- The durable structural fix (token-class swap, validator change, env-var rename) — belongs in a separate bead.
- Any non-Railway CI changes, dependency updates, or unrelated cleanup.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T05:15:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/c2f4f36352b6bae6a5b97a5ca7802f0e/investigation.md`
- **Run**: https://github.com/alexsiri7/reli/actions/runs/25202388806
- **SHA**: `3db8f1b5ab8f7c97ac6f855e6d57fc21b2dbb87b`
- **Failed step**: `Validate Railway secrets` (step 4 of `Deploy to staging` job 73895919947)
