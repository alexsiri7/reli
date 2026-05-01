# Investigation: Prod deploy failed on main (31st RAILWAY_TOKEN expiration; duplicate of #828)

**Issue**: #829 (https://github.com/alexsiri7/reli/issues/829)
**Type**: BUG
**Investigated**: 2026-05-01T04:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→prod auto-promotion on every push to `main` is broken: `Validate Railway secrets` exits 1 on SHA `afbf134` (run `25199559238`) and the downstream `staging-e2e` and `deploy-production` jobs are skipped. No prod data is at risk and a documented (human-only) rotation workaround exists, so HIGH rather than CRITICAL. |
| Complexity | LOW | The immediate fix is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit. Bonus: closing this also resolves the sibling alert #828, since both reference the same run. |
| Confidence | HIGH | Run `25199559238` emits the exact branch the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 31st occurrence of an identical failure shape — the prior 30 investigations (`#825` → 30th, `#824` → 29th, `#821` → 28th, `#820` → 28th, `#818` → 27th, `#816` → 26th, `#814` → 25th, …) all share this root cause. The same SHA + run was already filed by the cron's main-CI-red trigger as #828 four seconds earlier. |

---

## Problem Statement

`pipeline-health-cron.sh` filed issue #829 ("Prod deploy failed on main") for run `25199559238` on SHA `afbf134`. The same run was already filed as issue #828 ("Main CI red: Deploy to staging") by the cron's main-CI-red trigger four seconds earlier. Both alerts share a single root cause: the `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml` exits 1 because the `RAILWAY_TOKEN` GitHub Actions secret has expired (or been silently revoked) — Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the staging deploy step exits 1, and the downstream `staging-e2e` and `deploy-production` jobs are skipped. That is also why #829 reports "prod deploy failed" even though no production code was ever pushed: prod is just downstream of the staging step that actually died.

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #825 (30th, prod duplicate of #824), #824 (29th), #821 (28th, prod companion), #820 (28th, staging), #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd), and 22 prior recurrences before that.

Issue #829 is a **duplicate alert** for the same failed run as #828 (`25199559238`, SHA `afbf134`, `2026-05-01T02:34:49Z`). `pipeline-health-cron.sh` runs two distinct triggers — one that fires on main-CI red (filed #828 at 03:00:18Z) and one that fires on prod-deploy failure (filed #829 at 03:00:22Z) — but in this run both triggers landed on the same single underlying failure: the staging `Validate Railway secrets` step exiting 1, which cascaded a `skipped` conclusion onto the `deploy-production` job. A single human rotation closes both.

Web research conducted in parallel (artifact: `artifacts/runs/e14f306e82038faa50405bf1eb41edce/web-research.md`) flags a structural cause beneath the immediate one: Railway has three token types with different headers, and the env-var name `RAILWAY_TOKEN` is — per a Railway community help-station thread — reserved for **project tokens** (header `Project-Access-Token:`), while the workflow's `{me{id}}` validator only works with **account/workspace tokens** (header `Authorization: Bearer`). The mismatch pushes rotators toward account tokens, which are subject to silent revocation via OAuth refresh-token rotation. That is why "rotate again with No expiration" has now failed 31 times in a row.

### Evidence Chain

WHY: Run `25199559238` conclusion is `failure`; `deploy-production` is `skipped`; `pipeline-health-cron.sh` files #829 with title "Prod deploy failed on main".
↓ BECAUSE: `deploy-production` was `skipped` because its `needs: [deploy-staging, staging-e2e]` upstream did not succeed.
  Evidence: workflow definition at `.github/workflows/staging-pipeline.yml:140-143` (`needs: [deploy-staging, staging-e2e]`).

↓ BECAUSE: `deploy-staging` → `Validate Railway secrets` exited with code 1.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-01T02:34:49.0994653Z`.

↓ BECAUSE: Railway GraphQL `{me{id}}` probe returned no `data.me.id`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-01T02:34:49.0983542Z`.

↓ ROOT CAUSE (immediate): The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked).
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the validate step issues
  `curl -sf -X POST https://backboard.railway.app/graphql/v2 ... '{"query":"{me{id}}"}'`
  and exits 1 when the response lacks `.data.me.id`. The error message is the exact
  branch the workflow takes when Railway rejects the token.

↓ ROOT CAUSE (structural, recurring): Token-class mismatch between env-var name and validator.
  Evidence: Railway Help Station thread `railway-token-invalid-or-expired-59011e20` (cited
  in web-research finding #2) — `RAILWAY_TOKEN` only accepts project tokens; account tokens
  must use `RAILWAY_API_TOKEN`. The Reli workflow validates with `Authorization: Bearer` +
  `{me{id}}`, which only works with account/workspace tokens — and those are subject to
  silent revocation per Railway's OAuth troubleshooting docs. This is why "rotate again"
  has not stuck for 31 cycles.

↓ ROOT CAUSE (cascade): `deploy-production` reports `skipped`, not `failure`.
  Evidence: `.github/workflows/staging-pipeline.yml:140-143` — `needs: [deploy-staging, staging-e2e]`
  forces the prod job to be skipped when staging fails. The cron's prod-deploy-failed
  trigger interprets this skip as a prod failure for issue-filing purposes, hence the
  duplicate alert pair (#828 staging, #829 prod) for a single underlying expiration.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change for the immediate fix. Resolution is a credential rotation in GitHub Actions secrets. The structural fix (rename env var to `RAILWAY_API_TOKEN`, or switch to project-token + `Project-Access-Token` header) is OUT OF SCOPE for this bead — see scope boundaries. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the failing step in run `25199559238`).
- `.github/workflows/staging-pipeline.yml:140-143` — `deploy-production` `needs: [deploy-staging, staging-e2e]` (why prod was reported `skipped` and triggered the second cron alert).
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `deploy-staging` is fixed, until the token is rotated).
- `.github/workflows/railway-token-health.yml` — periodic token health probe; rotating the secret will turn this green.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook.
- `DEPLOYMENT_SECRETS.md` — secret setup + rotation reference (the doc the workflow's own error messages point to at `staging-pipeline.yml:46, :56, :163, :173`).
- `RAILWAY_SECRETS.md` — supplementary secret naming reference.
- Sibling issue **#828** ("Main CI red: Deploy to staging") — same run, same expiration; closing one should close the other.

### Git History

- **Failing SHA**: `afbf134` (the merge of #826, the 29th investigation PR for #824). This is the SHA `pipeline-health-cron.sh` reports as the failed deploy in run `25199559238`.
- **Pattern**: 30 prior `RAILWAY_TOKEN expiration` recurrences (most recent: `#825` → SHA `89e361a` on `main`). This is the 31st, anchored sequentially after #826 / #827.
- **Implication**: Long-standing operational issue, not a code regression. The fix is durable token hygiene (and likely a structural rename of the env var / change of validator) — not a code change in `backend/` or `frontend/`. Notably, the very *act of merging* the prior recurrence's investigation PR (#826) is what produced the new SHA `afbf134` that triggered this 31st alert pair — the staging pipeline runs on every push to `main`, including pushes whose only content is a docs-only investigation receipt.

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
4. `gh run rerun 25199559238 --repo alexsiri7/reli --failed`.
5. Close issues #828 and #829 once CI is green.

**Why a workspace token (and "No expiration") for the IMMEDIATE fix:**

- Railway officially recommends workspace tokens for "Team CI/CD" (`docs.railway.com/integrations/api`).
- Workspace tokens use the same `Authorization: Bearer $RAILWAY_TOKEN` header that the current validator already issues at `staging-pipeline.yml:50` and `:167` — no workflow change required *today*.
- The existing `{me{id}}` probe at `staging-pipeline.yml:49-58` and `:166-175` continues to work with workspace tokens.
- They support **"No expiration"** — accepting the default short TTL is exactly why this has now recurred 31 times.
- **Do NOT pick a project token for this rotation** — those use a `Project-Access-Token` header and `{me{id}}` would fail immediately even with a fresh token. (If the human prefers project tokens for least-privilege, that is a *workflow change*, not a secret rotation, and belongs in the structural-fix bead — see "Out of Scope".)

### Step 2: (No code or test changes)

This is a credential rotation, not a software change. There is nothing to type-check, lint, or test from the agent side.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#827, #826, #823, #822, #819, #817, #815, #813, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

What carries forward from #825/#827: this is the prod-deploy-failed companion alert (filed at 03:00:22Z) to the main-CI-red sibling #828 (filed at 03:00:18Z). Both alerts originate from a single staging-side failure on run `25199559238`. The companion `web-research.md` in this same `runs/` directory identifies the structural cause (env-var-name vs. token-class mismatch) and pegs this as the 31st recurrence. The structural fix remains carved out as a separate bead per Polecat scope discipline.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_829.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human picks a project token instead of a workspace token while leaving the current validator in place. | The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) and Step 1 above explicitly call out workspace tier; the `{me{id}}` validate step would fail immediately with a project token, surfacing the mistake on the very next run. |
| Human resolves #828 but forgets #829 (or vice-versa) — leaving a phantom open issue after a successful rotation. | Step 1 lists both #828 and #829 in the close-out action; once CI on `main` is green, both can be closed safely as the same expiration. |
| New token also expires (32nd recurrence). | Use **"No expiration"** at creation time. Even with that, account/workspace tokens can be silently revoked (Railway OAuth troubleshooting docs); the durable fix is the structural change in the separate bead, not another rotation. |
| Re-run fails because GitHub workflow_run rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |
| Pipeline-health-cron files a 32nd issue before rotation completes. | The `archon:in-progress` label on #829 already prevents pickup-cron double-fire; if a *new* failed run produces a *new* issue, close it as duplicate of #829. |
| Merging *this* investigation produces yet another no-op SHA on `main` and re-triggers the staging pipeline before the human has rotated, generating a 32nd alert pair. | Have the human rotate the token *before* merging this investigation PR, OR merge this investigation PR with the `no-ntfy` label and accept that the next failed-run alert will be filed and immediately closeable as duplicate. |

---

## Validation

### Automated Checks (after human rotation)

```bash
gh run rerun 25199559238 --repo alexsiri7/reli --failed
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
3. Both #828 and #829 are closed by the human after CI is green.

---

## Scope Boundaries

**IN SCOPE:**

- Documenting the 31st recurrence with evidence and pointing at the rotation runbook.
- Explicitly tying #829 to its sibling alert #828 (same run, same expiration) so the human closes both.
- Posting a structured investigation comment on issue #829.
- Linking to the parallel web research that identifies the structural cause.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden by `CLAUDE.md`).
- Investigating the sibling alert #828 (different bead — Polecat scope discipline).
- The structural fix (rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`, or switch validator to `Project-Access-Token: ...` + a project-scoped probe, or move to a self-hosted Railway runner). These are real fixes, but they require human design decisions (which token class, which header, runner cost trade-off) and a separate bead/PR. Per Polecat scope discipline, send mail to mayor recommending a follow-up bead instead of widening this one.
- Refactoring the validate step or the workflow to swallow auth errors.
- Changing `pipeline-health-cron.sh` to dedupe staging-vs-prod companion alerts (real ergonomic improvement, but separate bead).
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T04:10:00Z
- **Artifact**: `artifacts/runs/e14f306e82038faa50405bf1eb41edce/investigation.md`
- **Companion**: `artifacts/runs/e14f306e82038faa50405bf1eb41edce/web-research.md` (structural-cause findings, 31st-recurrence count)
- **Sibling alert**: #828 (same run `25199559238`, same SHA `afbf134`, same expiration)
