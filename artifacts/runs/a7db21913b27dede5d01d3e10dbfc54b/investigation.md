# Investigation: Main CI red — Deploy to staging (33rd RAILWAY_TOKEN expiration, 2nd pickup)

**Issue**: #836 (https://github.com/alexsiri7/reli/issues/836)
**Type**: BUG
**Investigated**: 2026-05-01T07:38:04Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | `Deploy to staging` is failing at `Validate Railway secrets` on every CI completion of `main` (latest run `25203795132` on SHA `392291cb`, plus the originally reported `25202388806` on SHA `3db8f1b`); staging-deploy, staging-health, staging-E2E, and `Deploy to production` are all `skipped`, blocking auto-deploy. HIGH (not CRITICAL) because a documented human-only rotation runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) exists and prod is not yet down — only the deploy gate is blocked. |
| Complexity | LOW | Single human credential action — rotate the `RAILWAY_TOKEN` GitHub Actions secret. No code, workflow, or config edit required for #836's scope. |
| Confidence | HIGH | Job log emits the exact `Not Authorized` branch the validator surfaces (`.github/workflows/staging-pipeline.yml:53-58`); this is the 33rd identical-shape recurrence after 32 prior cycles (#832/#833, #828/#829, #824/#825, #821, #820, #818, …) and the 2nd pickup of #836 specifically (prior workflow `c2f4f36352b6bae6a5b97a5ca7802f0e` produced merged PR #837 but human rotation is still pending). |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` is failing at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret is rejected by Railway with `Not Authorized`. Railway's GraphQL `{me{id}}` probe returns no `data.me.id`, the validator step exits 1, and every downstream job — staging deploy, staging health, staging E2E, and `Deploy to production` — is skipped. **Agents cannot fix this** — rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`). PR #837 (merged 2026-05-01T05:30Z) documented the failure but did not — and could not — perform the rotation; this 2nd pickup re-confirms the same fix is still required and adds the operator-procedure detail uncovered in fresh web research.

---

## Analysis

### First-Principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Railway secret validator | `.github/workflows/staging-pipeline.yml:32-58` | Partial | Correct **for an Account-class personal token created with "No workspace" selected**. Conflates "expired" with "wrong-class token" in its error string — the `Not Authorized` reply is identical for either case. Out-of-scope to fix here; flag for structural bead. |
| `RAILWAY_TOKEN` GitHub secret | n/a (out-of-tree) | No (currently invalid) | Either expired, revoked, or the wrong class. The validator cannot tell which. |
| Rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Partial | Documents "No expiration" but is silent on **"No workspace"** at token creation. Web research strongly suggests this missing instruction is the 33-cycle recurrence driver. Updating the runbook is out-of-scope for #836; flag for structural bead. |

### Root Cause / Change Rationale

**Immediate cause** (this bead's scope): The `RAILWAY_TOKEN` GHA secret is currently rejected by Railway. The fix is a human-only secret rotation following `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**Structural cause** (out-of-scope, flagged): The 33-cycle recurrence is most likely driven by a **token-creation procedure mismatch**, not Railway-side TTL enforcement. Railway's official docs and support threads confirm that an Account token created with a workspace pre-selected cannot answer `{me{id}}` — it returns `Not Authorized` indistinguishably from genuine expiration. The 2026 Railway changelog has **no** entries on token-policy changes (verified by direct fetch in `web-research.md`). See `web-research.md` for the full evidence.

### Evidence Chain

```
WHY: Run 25202388806 (and the post-merge run 25203795132) conclusion is failure;
     Deploy to production is skipped.
↓ BECAUSE: Deploy to staging → Validate Railway secrets exited with code 1.
  Evidence: ##[error]Process completed with exit code 1. at 2026-05-01T04:35:00.11Z
            (run 25202388806); reproduced in run 25203795132 on SHA 392291cb.

↓ BECAUSE: Railway GraphQL {me{id}} probe returned no data.me.id.
  Evidence: ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized

↓ ROOT CAUSE (immediate, in scope): The RAILWAY_TOKEN GHA secret is rejected by Railway.
  Evidence: .github/workflows/staging-pipeline.yml:49-58 — validator issues
  Authorization: Bearer $RAILWAY_TOKEN against {me{id}} and exits 1 on missing
  data.me.id. PR #837 (merged 2026-05-01T05:30Z) did not perform rotation.

↓ ROOT CAUSE (structural, out of scope): Likely operator-procedure issue at token creation.
  The validator's {me{id}} + Bearer header shape ONLY matches an Account token created
  with "No workspace" selected. Workspace tokens have no `me`; project tokens require
  the Project-Access-Token header. "Not Authorized" is indistinguishable across these
  cases. Hence the 33-cycle pattern despite no documented Railway TTL.
  See web-research.md §3 and §8.
```

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| GitHub Actions secret `RAILWAY_TOKEN` | n/a (out-of-tree) | UPDATE (human) | Rotate to a new **Account-class** Railway token created with **"No workspace"** selected and **"No expiration"**. |
| `.github/workflows/staging-pipeline.yml` | 32-58 | NO CHANGE | Validator step that surfaces the failure — already correct for the chosen token class. Editing it would be out-of-scope. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | — | NO CHANGE (in scope) | Existing human runbook; the operator follows it. (Improving the runbook to require "No workspace" is out-of-scope — flag for structural bead.) |
| `artifacts/runs/a7db21913b27dede5d01d3e10dbfc54b/investigation.md` | NEW | CREATE | This file — the investigation receipt for the 2nd pickup of #836. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` (this is what fails; keep as-is for #836).
- `.github/workflows/staging-pipeline.yml:60-99` — `Deploy staging image` and `Wait for staging health` consume `RAILWAY_TOKEN` after validation.
- `.github/workflows/staging-pipeline.yml` — `Deploy to production` job; gated on staging success and currently `skipped`.
- `.github/workflows/railway-token-health.yml` — independent recurring liveness probe of the same secret; expected to flip green after rotation.
- `pipeline-health-cron.sh` (mayor side) — files this issue family on red main pipelines and re-queues if no live run + no linked PR are seen. The cron re-fired #836 because PR #837 merged-and-closed; the rotation itself remained unperformed.

### Git History

- **Validator introduced**: `a4bb03c` — "fix: Configure missing Railway secrets for deploy pipeline (#726)"
- **Runbook introduced**: `6f4202a` — "docs: investigate CI failure — expired Railway token (#742) (#743)"
- **Prior identical-shape recurrence (32nd)**: `3db8f1b` — "docs: investigation for issue #833 (32nd RAILWAY_TOKEN expiration) (#834)"
- **First pickup of this issue (33rd)**: `392291c` — "docs: investigation for issue #836 (33rd RAILWAY_TOKEN expiration) (#837)" — merged 2026-05-01T05:30Z; rotation pending.
- **Implication**: Long-standing structural recurrence, not a regression. The 33rd cycle is the 2nd pickup of the same issue because PR #837 closed the documentation loop without unblocking CI.

---

## Implementation Plan

### Step 1: Human credential rotation (out-of-tree)

**File**: GitHub Actions secret `RAILWAY_TOKEN` (no repository file)
**Action**: UPDATE (human only — agents cannot perform this)

**Required action** (human):

1. Sign in at https://railway.com/account/tokens.
2. Create a new token:
   - Name: `github-actions-permanent-2026-05-01`
   - Workspace selector: **"No workspace"** (CRITICAL — this is the most likely cause of the recurrence; see `web-research.md` §3 / Recommendation #1).
   - Expiration: **No expiration** (do not accept any default TTL).
3. Update the secret:
   ```bash
   gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
   # Paste the new token when prompted
   ```

**Why**: The validator at `.github/workflows/staging-pipeline.yml:49-58` issues `Authorization: Bearer $RAILWAY_TOKEN` against `{ me { id } }`. Per Railway docs, `me` resolves only for personal/Account tokens, and per a Railway support thread it resolves only when the token was created with **"No workspace"** selected. A workspace-scoped Account token, a Workspace token, or a Project token will all fail this validator immediately and present as `Not Authorized` — indistinguishable from genuine expiration in the current error string.

> ⚠️ **Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_836.md` receipt** claiming rotation is done. That is a Category 1 error. This investigation file (under `artifacts/runs/`) documents the failure; it does NOT claim rotation has occurred.

---

### Step 2: Re-trigger CI

**Action**: human or agent, after Step 1

```bash
# Re-run the failed jobs of the latest run (preferred):
gh run rerun 25203795132 --repo alexsiri7/reli --failed

# Fallback if the run is too stale to rerun: push an empty commit to main
git commit --allow-empty -m "chore: kick CI after RAILWAY_TOKEN rotation" && git push
```

**Why**: `staging-pipeline.yml` is `workflow_run`-triggered on CI completion and does not auto-restart on secret rotation. Either rerun the failed jobs or push a no-op commit to retrigger.

---

### Step 3: Confirm green and close

After CI is green, close #836 with a comment referencing the rotation timestamp and the new green run ID.

---

## Patterns to Follow

**From codebase — the validator step (no change in this bead, reference only):**

```yaml
# SOURCE: .github/workflows/staging-pipeline.yml:32-58
# Pattern: Account-token validator using {me{id}}
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

This shape is correct for the chosen token class and does not need to change for #836. The fix is the secret value, not the workflow.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Operator picks a Project or Workspace token | Step 1 explicitly calls for **Account/personal class**; project tokens use `Project-Access-Token` header (not `Bearer`); workspace tokens have no `me`. Both fail the existing validator. |
| Operator creates an Account token with a workspace pre-selected | Step 1 explicitly says **"No workspace"** — this is the **#1 suspected cause** of the 33-cycle pattern per `web-research.md` §3. The runbook is silent on this; the investigation comment must call it out. |
| Operator accepts a default TTL | Step 1 says **"No expiration"**; otherwise we file the 34th identical issue next week. |
| `gh run rerun` rejected because run is stale | Fallback in Step 2 — push an empty commit to `main`. |
| Sibling issue exists for the same run | None — `gh issue list --search "Main CI red"` returns only #836 for run `25202388806`; #833 is a prior run. |
| Agent attempts to "fix" by writing a `.github/RAILWAY_TOKEN_ROTATION_836.md` receipt | Forbidden by `CLAUDE.md > Railway Token Rotation` — Category 1 error. Investigation only. |
| Structural fix (validator/runbook/token-class swap) attempted in this bead | Out-of-scope per Polecat Scope Discipline. File a separate bead for the durable fix; mail mayor with `gt mail send mayor/ --subject "Found: ..." --body "..."` if a finding warrants it. |
| The cron re-fires #836 again before rotation completes | Expected — `pipeline-health-cron.sh` re-queues when no live run + no linked open PR are seen. PR #837 is merged-and-closed. The token-rotation human task is the only thing that can break the loop. |

---

## Validation

### Automated Checks (post-rotation)

```bash
# Re-run the latest failed staging pipeline:
gh run rerun 25203795132 --repo alexsiri7/reli --failed

# Replace <RERUN_RUN_ID> with the run ID printed by the rerun command:
gh run watch <RERUN_RUN_ID> --repo alexsiri7/reli --exit-status

# Confirm the secret is set:
gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN
```

### Manual Verification

1. `Validate Railway secrets` step in `Deploy to staging` exits 0 (`{me{id}}` returns a non-empty `data.me.id`).
2. `Deploy staging image to Railway` and `Wait for staging health` complete successfully.
3. `Deploy to production` runs (no longer `skipped`) and `${RAILWAY_PRODUCTION_URL}/healthz` returns `{"status":"ok"}`.
4. `.github/workflows/railway-token-health.yml` next scheduled run goes green.
5. Issue #836 closes; no new sibling issue is filed by `pipeline-health-cron.sh` on the next main push.

---

## Scope Boundaries

**IN SCOPE:**
- Document the 2nd-pickup failure mode, evidence chain, and affected workflow lines.
- Direct the human operator to `docs/RAILWAY_TOKEN_ROTATION_742.md` AND explicitly call out **"No workspace"** at token creation (the operator-procedure detail surfaced by the refreshed `web-research.md`).
- Post a GitHub comment on #836 with the implementation plan.

**OUT OF SCOPE (do not touch):**
- Rotating the `RAILWAY_TOKEN` secret itself (human-only — `CLAUDE.md`).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file claiming rotation is done (Category 1 error per `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml` — the validator is correct for the chosen token class.
- Editing `docs/RAILWAY_TOKEN_ROTATION_742.md` to add the "No workspace" instruction — belongs in a separate bead even though it would likely break the cycle.
- The durable structural fix (validator change to differentiate "expired" from "wrong shape", token-class swap to Workspace, env-var rename) — separate bead.
- Any non-Railway CI changes, dependency updates, or unrelated cleanup.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T07:38:04Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/a7db21913b27dede5d01d3e10dbfc54b/investigation.md`
- **Web research companion**: `artifacts/runs/a7db21913b27dede5d01d3e10dbfc54b/web-research.md`
- **Prior workflow** (1st pickup → merged PR #837): `artifacts/runs/c2f4f36352b6bae6a5b97a5ca7802f0e/`
- **Original failing run**: https://github.com/alexsiri7/reli/actions/runs/25202388806 (SHA `3db8f1b`)
- **Latest failing run** (post-#837-merge): https://github.com/alexsiri7/reli/actions/runs/25203795132 (SHA `392291c`)
- **Failed step**: `Validate Railway secrets` (step 4 of `Deploy to staging`)
