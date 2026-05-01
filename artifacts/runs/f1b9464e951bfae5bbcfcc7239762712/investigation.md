# Investigation: Prod deploy failed on main (32nd RAILWAY_TOKEN expiration)

**Issue**: #833 (https://github.com/alexsiri7/reli/issues/833)
**Type**: BUG
**Investigated**: 2026-05-01T04:05:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Production auto-deploy on every push to `main` is broken because the staging-gate `Validate Railway secrets` step exits 1 on SHA `d01d31c` (run `25201008471`); `Deploy to production` is `skipped` as a result. No prod data is at risk and a documented (human-only) rotation workaround exists, so HIGH rather than CRITICAL. |
| Complexity | LOW | The immediate fix is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit. (The durable structural fix is deferred to a separate bead — see "Out of Scope".) |
| Confidence | HIGH | Run `25201008471` emits the exact branch the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 32nd occurrence of an identical failure shape — the prior 31 investigations (`#828/#829` → 31st pair, `#824/#825` → 29th/30th, `#821` → 28th, `#820` → 28th [staging], `#818` → 27th, …) all share this root cause. |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked) again. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the deploy step exits 1, and the downstream `Staging E2E smoke tests` and `Deploy to production` jobs are skipped. `pipeline-health-cron.sh` then files this as "Prod deploy failed on main" (#833) alongside its staging sibling (#832).

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #828/#829 (31st pair), #825 (30th), #824 (29th), #821 (28th [prod companion]), #820 (28th [staging]), #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd), and 22 prior recurrences before that.

The structural cause has been documented across the recent investigations (#824–#829): Railway has three token classes (personal/account, workspace, project) with different validation surfaces. The Reli workflow's env-var name `RAILWAY_TOKEN` semantically points at project tokens (header `Project-Access-Token:`), but the validator's `Authorization: Bearer` + `{me{id}}` probe only resolves for personal/account tokens — and those are subject to silent revocation via Railway's OAuth refresh-token rotation. That is why "rotate again with No expiration" has now failed 32 times in a row.

### Evidence Chain

WHY: Run `25201008471` conclusion is `failure`; `Deploy to production` is `skipped`.
↓ BECAUSE: `Deploy to staging` → `Validate Railway secrets` exited with code 1.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-01T03:35:25.3473833Z`.

↓ BECAUSE: Railway GraphQL `{me{id}}` probe returned no `data.me.id`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-01T03:35:25.3464082Z`.

↓ ROOT CAUSE (immediate): The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked).
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the validate step issues
  `curl -sf -X POST https://backboard.railway.app/graphql/v2 ... '{"query":"{me{id}}"}'`
  with header `Authorization: Bearer $RAILWAY_TOKEN` and exits 1 when the response lacks
  `.data.me.id`. The error message is the exact branch the workflow takes when Railway
  rejects the token.

↓ ROOT CAUSE (structural, recurring): Token-class mismatch between env-var name and validator.
  Evidence: Investigations #824–#829 have repeatedly identified that the validator at
  `.github/workflows/staging-pipeline.yml:49-58` and `:166-175` only accepts personal/account
  tokens (project tokens require `Project-Access-Token:` header; workspace tokens reject
  `{me{id}}`). Personal tokens are silently revoked via Railway's OAuth refresh-token rotation.
  Until the validator/env-var-name structural fix lands, every rotation is at most a temporary
  patch.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change for the immediate fix. Resolution is a credential rotation in GitHub Actions secrets. The structural fix (rename env var to `RAILWAY_API_TOKEN`, or switch to project-token + `Project-Access-Token` header, or replace the validator with one compatible with workspace tokens) is OUT OF SCOPE for this bead — see scope boundaries. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the failing step in run `25201008471`).
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `Deploy to staging` is fixed, but the immediate failure here is on the staging gate; prod is `skipped` because staging didn't pass).
- `.github/workflows/railway-token-health.yml` — periodic token health probe; rotating the secret will turn this green.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook.
- `DEPLOYMENT_SECRETS.md` — secret setup + rotation reference (the doc the workflow's own error messages point to at `staging-pipeline.yml:46, :56, :163, :173`).
- `RAILWAY_SECRETS.md` — supplementary secret naming reference.

### Git History

- **Failing SHA**: `d01d31c` — the merge of #830 (the 31st-staging investigation). This is the SHA `pipeline-health-cron.sh` reports as the failed deploy in run `25201008471`.
- **Sibling**: #832 ("Main CI red: Deploy to staging") — same run, same SHA, same root cause. #833 (this issue) is the prod-deploy-failed companion filed by the same cron pass.
- **Pattern**: 31 prior `RAILWAY_TOKEN expiration` recurrences (most recent: #828 staging + #829 prod → 31st pair). This is the 32nd, anchored sequentially after #830/#831.
- **Implication**: Long-standing operational issue, not a code regression. The fix is durable token hygiene (and likely the structural rename of the env var / change of validator) — not a code change in `backend/` or `frontend/`.

---

## Implementation Plan

> **No code change. Human-only credential rotation.** Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt claiming rotation is done. That is a Category 1 error.

### Step 1: Rotate the Railway token (HUMAN)

**File**: GitHub Actions secret `RAILWAY_TOKEN` (no file in repo).
**Action**: REPLACE secret value.

**Required actions:**

1. Sign in at https://railway.com/account/tokens.
2. Create a **personal/account** token (the only class that resolves `{me{id}}` against the current validator) named `github-actions-permanent` with **"No expiration"** if Railway offers it for the chosen tier.
3. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the new token.
4. `gh run rerun 25201008471 --repo alexsiri7/reli --failed` (or push a no-op commit to `main` if `workflow_run` rerun is rejected).
5. Close issues #832 and #833 once CI is green.

**Why a personal/account token for the IMMEDIATE fix:**

- The validator at `staging-pipeline.yml:49-58` (and `:166-175`) issues `Authorization: Bearer $RAILWAY_TOKEN` against `{me{id}}`. As established in #828's web-research companion, **workspace tokens reject `{me{id}}`** and **project tokens require the `Project-Access-Token` header instead**. **Personal/account is the only token class that the existing validate step accepts.**
- Personal tokens are subject to silent revocation via OAuth refresh-token rotation — this is why the 32-cycle pattern persists. The durable fix is to change the validator (so a workspace or project token can be used), not to keep rotating personal tokens.
- **Do NOT pick a project token for this rotation** — `{me{id}}` would fail immediately even with a fresh token.
- **Do NOT pick a workspace token for this rotation** either — same reason; the `{me{id}}` probe rejects it.
- If the human prefers workspace or project tokens for least-privilege, that is a *workflow change*, not a secret rotation, and belongs in the structural-fix bead — see "Out of Scope".

### Step 2: (No code or test changes)

This is a credential rotation, not a software change. There is nothing to type-check, lint, or test from the agent side.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#828/#830, #829/#831, #826/#827, #822/#823, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

The structural fix (env-var rename and/or validator swap) remains carved out as a separate bead per Polecat scope discipline. Mail to mayor recommending that bead has been sent in prior cycles; the cycle continues to recur because the structural fix has not yet landed, not because the diagnosis is unclear.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_833.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human picks a workspace or project token while leaving the current validator in place. | Workspace tokens reject `{me{id}}`; project tokens use the wrong header. Step 1 above explicitly directs the human to a personal/account token; the `{me{id}}` validate step would fail immediately on the wrong class, surfacing the mistake on the very next run. |
| New token also expires (33rd recurrence). | Personal tokens can be silently revoked even with "No expiration" set (Railway OAuth troubleshooting docs); the durable fix is the structural change in the separate bead, not another rotation. |
| Re-run fails because GitHub `workflow_run` rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |
| Pipeline-health-cron files a 33rd issue before rotation completes. | The `archon:in-progress` label on #833 (and #832) prevents pickup-cron double-fire on the same number. If a new failed run produces a new issue, close as duplicate of #833. |
| #832 (sibling staging issue) is also active. | #832 and #833 describe the *same* run/SHA from the staging vs. prod perspective. The single rotation in Step 1 resolves both — close them together once CI is green. Per Polecat scope, this bead handles only #833; the sibling has its own bead. |

---

## Validation

### Automated Checks (after human rotation)

```bash
gh run rerun 25201008471 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
```

Expected outcome:

- `Validate Railway secrets` passes (Railway returns `{data:{me:{id:"..."}}}`).
- Staging deploy reaches Railway; staging E2E smoke tests run against `RAILWAY_STAGING_URL`.
- `Deploy to production` proceeds and `/healthz` on `RAILWAY_PRODUCTION_URL` returns ok.
- `railway-token-health.yml` reports green on its next scheduled run.

### Manual Verification

1. `gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN` shows an updated timestamp.
2. The new run for `Staging → Production Pipeline` against `main` completes successfully end-to-end.
3. Issues #832 and #833 close together once CI is green.

---

## Scope Boundaries

**IN SCOPE:**

- Documenting the 32nd recurrence with evidence and pointing at the rotation runbook.
- Posting a structured investigation comment on issue #833.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden by `CLAUDE.md`).
- The structural fix (rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`, or switch validator to `Project-Access-Token: ...` + a project-scoped query, or replace `{me{id}}` with a workspace-compatible probe, or move to a self-hosted Railway runner). These are real fixes, but they require human design decisions and a separate bead/PR. Per Polecat scope discipline, they remain mailed-to-mayor follow-ups, not part of this bead.
- Refactoring the validate step or the workflow to swallow auth errors.
- Replacing the cron health filer (`pipeline-health-cron.sh`).
- Investigating sibling issue #832 — it has its own bead (same run, same fix, separate scope).
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T04:05:00Z
- **Artifact**: `artifacts/runs/f1b9464e951bfae5bbcfcc7239762712/investigation.md`
