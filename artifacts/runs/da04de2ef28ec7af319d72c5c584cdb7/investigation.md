# Investigation: Prod deploy failed on main (30th RAILWAY_TOKEN expiration; duplicate of #824)

**Issue**: #825 (https://github.com/alexsiri7/reli/issues/825)
**Type**: BUG
**Investigated**: 2026-05-01T03:15:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→prod auto-promotion on every push to `main` is broken: `Validate Railway secrets` exits 1 on SHA `89e361a` and the downstream `staging-e2e` and `deploy-production` jobs are skipped. No prod data is at risk and a documented (human-only) rotation workaround exists, so HIGH rather than CRITICAL. |
| Complexity | LOW | The immediate fix is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit. Bonus: closing this also resolves the sibling alert #824 since both reference the same run. |
| Confidence | HIGH | Run `25198048549` emits the exact branch the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 30th occurrence of an identical failure shape — the prior 29 investigations (`#824` → 29th, `#821` → 28th, `#820` → 28th, `#818` → 27th, `#816` → 26th, `#814` → 25th, …) all share this root cause. The same SHA + run was already triaged for #824 ~20 minutes earlier (artifact `artifacts/runs/ea9654fc52896f5808b46ee3d34e790d/investigation.md`). |

---

## Problem Statement

`pipeline-health-cron.sh` filed issue #825 ("Prod deploy failed on main") for run `25198048549` on SHA `89e361a`. The same run was already filed as issue #824 ("Main CI red: Deploy to staging") by the cron's main-CI-red trigger. Both alerts share a single root cause: the `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml` exits 1 because the `RAILWAY_TOKEN` GitHub Actions secret has expired (or been silently revoked) — Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the deploy step exits 1, and the downstream `staging-e2e` and `deploy-production` jobs are skipped. That is also why #825 reports "prod deploy failed" even though no production code was ever pushed: prod is just downstream of the staging step that actually died.

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #824 (29th), #821 (28th), #820 (28th), #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd), and 22 prior recurrences before that.

Issue #825 is a **duplicate alert** for the same failed run as #824 (`25198048549`, SHA `89e361a`, `2026-05-01T01:35:00Z`). `pipeline-health-cron.sh` runs two distinct triggers — one that fires on main-CI red (filed #824) and one that fires on prod-deploy failure (filed #825) — but in this run both triggers landed on the same single underlying failure: the staging `Validate Railway secrets` step exiting 1, which cascaded a `skipped` conclusion onto the `deploy-production` job. A single human rotation closes both.

Web research conducted in parallel (artifact: `artifacts/runs/da04de2ef28ec7af319d72c5c584cdb7/web-research.md`) flags a structural cause beneath the immediate one: Railway has three token types with different headers, and the env-var name `RAILWAY_TOKEN` is — per a Railway community help-station thread — reserved for **project tokens** (header `Project-Access-Token:`), while the workflow's `{me{id}}` validator only works with **account/personal tokens** (header `Authorization: Bearer`). The mismatch pushes rotators toward account tokens, which are subject to silent revocation via OAuth refresh-token rotation. That is why "rotate again with No expiration" has now failed 30 times in a row.

### Evidence Chain

WHY: Run `25198048549` conclusion is `failure`; `deploy-production` is `skipped`; `pipeline-health-cron.sh` files #825 with title "Prod deploy failed on main".
↓ BECAUSE: `deploy-production` was `skipped` because its `needs: [deploy-staging, staging-e2e]` upstream did not succeed.
  Evidence: workflow definition at `.github/workflows/staging-pipeline.yml:140-143` (`needs: [deploy-staging, staging-e2e]`) plus run JSON showing `Deploy to production` `conclusion: skipped`, `Staging E2E smoke tests` `conclusion: skipped`.

↓ BECAUSE: `deploy-staging` → `Validate Railway secrets` exited with code 1.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-01T01:34:58.1232383Z` in the `Deploy to staging / Validate Railway secrets` log.

↓ BECAUSE: Railway GraphQL `{me{id}}` probe returned no `data.me.id`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-01T01:34:58.1216391Z`.

↓ ROOT CAUSE (immediate): The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked).
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the validate step issues
  `curl -sf -X POST https://backboard.railway.app/graphql/v2 ... '{"query":"{me{id}}"}'`
  and exits 1 when the response lacks `.data.me.id`. The error message is the exact
  branch the workflow takes when Railway rejects the token.

↓ ROOT CAUSE (structural, recurring): Token-class mismatch between env-var name and validator.
  Evidence: Railway Help Station thread `railway-token-invalid-or-expired-59011e20` and
  `graph-ql-requests-returning-not-authoriz-56dacb52` (cited in companion web-research
  findings #3 and #4) — `{me{id}}` only resolves for personal/account tokens, while the
  CI/CD-recommended type is workspace or project. Account tokens are subject to silent
  revocation per Railway's OAuth troubleshooting docs. This is why "rotate again" has not
  stuck for 30 cycles.

↓ DUPLICATE-FILING CONTRIBUTOR: `pipeline-health-cron.sh` files both a "Main CI red" issue (#824) and a "Prod deploy failed" issue (#825) for the *same* run when the failure happens in the staging step that prod depends on. The `archon:in-progress` label only blocks pickup-cron double-fire on the same issue number; it does not deduplicate across triggers. Out of scope here — flag to mayor as a follow-up bead.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change for the immediate fix. Resolution is a credential rotation in GitHub Actions secrets. The structural fix (rename env var to `RAILWAY_API_TOKEN`, or switch to project-token + `Project-Access-Token` header, or fix `{me{id}}` validator) is OUT OF SCOPE for this bead — see scope boundaries. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the actual failing step in run `25198048549`).
- `.github/workflows/staging-pipeline.yml:140-143` — `deploy-production` `needs: [deploy-staging, staging-e2e]`, which is why "prod" appears in the #825 title even though prod itself never executed.
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `deploy-staging` is fixed and the same expired token reaches it).
- `.github/workflows/railway-token-health.yml` — periodic token health probe (daily 09:00 UTC); rotating the secret will turn this green within ~24h.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook.
- `RAILWAY_SECRETS.md` — secret naming reference.

### Git History

- **Failing SHA**: `89e361a` (the merge of #822, the 28th investigation). This is the SHA `pipeline-health-cron.sh` reports as the failed deploy in run `25198048549`. Same SHA as #824.
- **Pattern**: 29 prior `RAILWAY_TOKEN expiration` recurrences (most recent: `#824` → `89e361a` on `main`, ~20 minutes before #825 was filed). This is the 30th, anchored sequentially after #824.
- **Implication**: Long-standing operational issue, not a code regression. The fix is durable token hygiene (and a structural rename of the env var / change of validator) — not a code change in `backend/` or `frontend/`.

---

## Implementation Plan

> **No code change. Human-only credential rotation.** Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt claiming rotation is done. That is a Category 1 error.

### Step 1: Rotate the Railway token (HUMAN)

**File**: GitHub Actions secret `RAILWAY_TOKEN` (no file in repo).
**Action**: REPLACE secret value.

**Required actions:**

1. Sign in at https://railway.com/account/tokens.
2. Create a **workspace** token (NOT account-only, NOT project) named `github-actions-permanent` with **"No expiration"**.
3. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the new token.
4. `gh run rerun 25198048549 --repo alexsiri7/reli --failed` (this single rerun will resolve BOTH #824 and #825 since they reference the same run).
5. Close issue #825 as a duplicate of #824 once CI is green; close #824 as fixed.

**Why a workspace token (and "No expiration") for the IMMEDIATE fix:**

- Railway officially recommends workspace tokens for "Team CI/CD" (`docs.railway.com/integrations/api`).
- Workspace tokens use the same `Authorization: Bearer $RAILWAY_TOKEN` header that the current validator already issues at `staging-pipeline.yml:50` and `:167` — no workflow change required *today*.
- The existing `{me{id}}` probe at `staging-pipeline.yml:49-58` and `:166-175` continues to work with personal/account tokens *and* (in current Railway behavior) with workspace tokens scoped to a workspace whose member exposes a `me`. (The companion web-research notes a Railway help thread suggesting `{me{id}}` may *not* work with project tokens — which is why this rotation should NOT pick a project token.)
- They support **"No expiration"** — accepting the default short TTL is exactly why this has now recurred 30 times.
- **Do NOT pick a project token for this rotation** — those use a `Project-Access-Token` header and `{me{id}}` would fail immediately even with a fresh token. (If the human prefers project tokens for least-privilege, that is a *workflow change*, not a secret rotation, and belongs in the structural-fix bead — see "Out of Scope".)

### Step 2: (No code or test changes)

This is a credential rotation, not a software change. There is nothing to type-check, lint, or test from the agent side.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#824, #822, #823, #819, #817, #815, #813, #812, #809, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

What carries forward from #824: the parallel `web-research.md` in this same `runs/` directory identifies the structural cause (env-var-name vs. token-class mismatch and `{me{id}}` query-vs-token-type mismatch). The structural fix remains carved out as a separate bead per Polecat scope discipline.

What is **new** for #825: explicit recognition that #825 is a *duplicate alert* of #824 (same failed run, two cron triggers). This investigation does not re-do the rotation work; it cross-links the issues and notes the cron's deduplication gap as a candidate follow-up bead.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_825.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human rotates the token to fix #824 but does not realize #825 is the same failure and tries a second rotation, burning the new token slot. | This investigation explicitly states #825 is a duplicate of #824; the GitHub comment posted in Phase 5 will spell it out. One rotation closes both. |
| Human picks a project token instead of a workspace token while leaving the current validator in place. | The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) and Step 1 above explicitly call out workspace tier; the `{me{id}}` validate step would fail immediately with a project token, surfacing the mistake on the very next run. |
| New token also expires (31st recurrence). | Use **"No expiration"** at creation time. Even with that, account/workspace tokens can be silently revoked (Railway OAuth troubleshooting docs); the durable fix is the structural change in the separate bead, not another rotation. |
| Re-run fails because GitHub `workflow_run` rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |
| Pipeline-health-cron files a 31st issue before rotation completes (or files yet another duplicate variant). | The `archon:in-progress` label on #824 and #825 prevents the *pickup* cron from double-firing on those issue numbers; if a *new* failed run produces a *new* issue, close it as duplicate of #824. The cron's cross-trigger deduplication gap is a separate bead — flag to mayor. |

---

## Validation

### Automated Checks (after human rotation)

```bash
gh run rerun 25198048549 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
```

Expected outcome:

- `Validate Railway secrets` (staging) passes (Railway returns `{data:{me:{id:"..."}}}`).
- Staging deploy reaches Railway; staging E2E smoke tests run against `RAILWAY_STAGING_URL`.
- `Validate Railway secrets` (production) passes against the same now-valid token.
- `Deploy to production` proceeds and `/healthz` on `RAILWAY_PRODUCTION_URL` returns ok.
- `railway-token-health.yml` reports green on its next scheduled run (daily 09:00 UTC).

### Manual Verification

1. `gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN` shows an updated timestamp.
2. The new run for `Staging → Production Pipeline` against `main` completes successfully end-to-end.
3. Both #824 and #825 are closed (one as fixed, one as duplicate).

---

## Scope Boundaries

**IN SCOPE:**

- Documenting the 30th recurrence with evidence and pointing at the rotation runbook.
- Posting a structured investigation comment on issue #825 that explicitly cross-links to #824 as the originating alert for the same run.
- Linking to the parallel web research that identifies the structural cause.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden by `CLAUDE.md`).
- The structural fix (rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`, or switch validator to `Project-Access-Token: ...` + `{ projectToken { projectId } }`, or move to a self-hosted Railway runner). These are real fixes, but they require human design decisions (which token class, which header, runner cost trade-off) and a separate bead/PR. Per Polecat scope discipline, send mail to mayor recommending a follow-up bead instead of widening this one.
- Fixing `pipeline-health-cron.sh`'s cross-trigger deduplication gap that filed both #824 and #825 for the same run. Flag to mayor as a follow-up bead — do not edit the cron from this bead.
- Refactoring the validate step or the workflow to swallow auth errors.
- Replacing the cron health filer (`pipeline-health-cron.sh`).
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T03:15:00Z
- **Artifact**: `artifacts/runs/da04de2ef28ec7af319d72c5c584cdb7/investigation.md`
- **Companion**: `artifacts/runs/da04de2ef28ec7af319d72c5c584cdb7/web-research.md` (structural-cause findings, fetched in parallel)
- **Sibling alert**: #824 (`artifacts/runs/ea9654fc52896f5808b46ee3d34e790d/investigation.md`) — same run `25198048549`, same SHA `89e361a`; one human rotation resolves both.
