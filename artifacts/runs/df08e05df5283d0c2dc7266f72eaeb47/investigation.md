# Investigation: Main CI red — Deploy to staging (28th RAILWAY_TOKEN expiration)

**Issue**: #820 (https://github.com/alexsiri7/reli/issues/820)
**Type**: BUG
**Investigated**: 2026-05-01T01:45:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→prod auto-promotion is broken on every push to `main` because `Validate Railway secrets` exits 1; the downstream `Staging E2E smoke tests` and `Deploy to production` jobs are skipped. No prod data is at risk and a documented (human-only) rotation workaround exists, so this is HIGH rather than CRITICAL. |
| Complexity | LOW | Resolution is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config change is required. |
| Confidence | HIGH | The run log emits the exact error the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 28th occurrence of the identical failure mode (prior label was `27th` on #819 → `5f00e50`, the same SHA the failing run was triggered against). |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret has expired again. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the deploy step exits 1, and the downstream `Staging E2E smoke tests` and `Deploy to production` jobs are skipped. `pipeline-health-cron.sh` then files this as "Main CI red: Deploy to staging".

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd) — and 22 prior recurrences before that.

### Evidence Chain

WHY: Run #25196397105 conclusion is `failure`; `Deploy to production` and `Staging E2E smoke tests` are `skipped`.
↓ BECAUSE: `Deploy to staging` → `Validate Railway secrets` exited with code 1.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-01T00:34:51.5402052Z`.

↓ BECAUSE: Railway GraphQL `{me{id}}` probe returned no `data.me.id`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-01T00:34:51.5387076Z`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked).
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the validate step issues
  `curl -sf -X POST https://backboard.railway.app/graphql/v2 ... '{"query":"{me{id}}"}'`
  and exits 1 when the response lacks `.data.me.id`. The error message is the exact
  branch the workflow takes when Railway rejects the token.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change. Resolution is a credential rotation in GitHub Actions secrets. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the failing step).
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `deploy-staging` is fixed).
- `.github/workflows/railway-token-health.yml` — periodic token health probe; rotating the secret will turn this green.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook.
- `RAILWAY_SECRETS.md` — secret naming reference.

### Git History

- **Failing SHA**: `5f00e50` (the merge of #819, the 27th investigation) is the commit `pipeline-health-cron.sh` reports as the failed deploy. Each successive merge to `main` re-triggers the staging pipeline and re-surfaces the same auth failure until the token is rotated.
- **Pattern**: 27 prior commits on `main` carry the `RAILWAY_TOKEN expiration` label (issues #818, #816, #814, #811, #810, #808, #804/#805, #800/#801, #798, #793/#794, #790/#789, #786/#785, #781/#783, #779, #777, #774/#773, #769/#771, #762, #766, #751, plus earlier). This is the 28th.
- **Implication**: Long-standing operational issue, not a code regression. The fix is durable token hygiene, not a code change.

---

## Implementation Plan

> **No code change. Human-only credential rotation.** Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt claiming rotation is done. That is a Category 1 error.

### Step 1: Rotate the Railway token (HUMAN)

**File**: GitHub Actions secret `RAILWAY_TOKEN` (no file in repo).
**Action**: REPLACE secret value.

**Required actions:**

1. Sign in at https://railway.com/account/tokens.
2. Create a **workspace** token (NOT account, NOT project) named `github-actions-permanent` with **"No expiration"**.
3. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the new token.
4. `gh run rerun 25196397105 --repo alexsiri7/reli --failed`.
5. Close issue #820 once CI is green.

**Why a workspace token (and "No expiration"):**

- Railway officially recommends workspace tokens for "Team CI/CD" (`docs.railway.com/integrations/api`).
- Workspace tokens use the same `Authorization: Bearer $RAILWAY_TOKEN` header — no workflow change.
- The existing `{me{id}}` probe in `staging-pipeline.yml:49-58` and `:166-175` continues to work.
- They support **"No expiration"** — accepting the default short TTL is exactly why this has now recurred 28 times.
- **Do NOT pick a project token** — those use a `Project-Access-Token` header and `{me{id}}` would fail immediately even with a fresh token.

### Step 2: (No code or test changes)

This is a credential rotation, not a software change. There is nothing to type-check, lint, or test from the agent side.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#818, #816, #814, #811, #810, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_820.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human picks a project token instead of a workspace token. | The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) and Step 1 above explicitly call out workspace tier; the `{me{id}}` validate step would fail immediately with a project token, surfacing the mistake on the very next run. |
| New token also expires. | Use **"No expiration"** at creation time. This is the systemic fix; it has been recommended in every recent recurrence investigation and is the only thing that breaks the recurrence loop. |
| Re-run fails because GitHub workflow_run rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |

---

## Validation

### Automated Checks (after human rotation)

```bash
gh run rerun 25196397105 --repo alexsiri7/reli --failed
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

---

## Scope Boundaries

**IN SCOPE:**

- Documenting the 28th recurrence with evidence and pointing at the rotation runbook.
- Posting a structured investigation comment on issue #820.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden).
- Refactoring the validate step or the workflow to swallow auth errors.
- Replacing the cron health filer (`pipeline-health-cron.sh`).
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T01:45:00Z
- **Artifact**: `artifacts/runs/df08e05df5283d0c2dc7266f72eaeb47/investigation.md`
