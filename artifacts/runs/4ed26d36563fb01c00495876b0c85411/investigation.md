# Investigation: Prod deploy failed on main (28th RAILWAY_TOKEN expiration)

**Issue**: #821 (https://github.com/alexsiri7/reli/issues/821)
**Type**: BUG
**Investigated**: 2026-05-01T02:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→prod auto-promotion is broken on every push to `main` because the staging validate step exits 1; downstream `staging-e2e` and `deploy-production` are skipped. No prod data is at risk and a documented (human-only) rotation workaround exists, so this is HIGH rather than CRITICAL. |
| Complexity | LOW | Resolution is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config change is required for the immediate fix. (A *durable* structural fix, deferred to a separate bead, is MEDIUM — see "Out of Scope" below.) |
| Confidence | HIGH | The run log emits the exact error the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 28th occurrence of an identical failure shape — the prior 27 investigations (`#818` → 27th, `#816` → 26th, `#814` → 25th, …) all share this root cause. |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret has expired again. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the deploy step exits 1, and the downstream `staging-e2e` and `deploy-production` jobs are skipped. `pipeline-health-cron.sh` then files this as "Prod deploy failed on main".

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd), and 22 prior recurrences before that.

Web research conducted in parallel (artifact: `artifacts/runs/4ed26d36563fb01c00495876b0c85411/web-research.md`) flags a structural cause beneath the immediate one: Railway has three token types with different headers, and the env-var name `RAILWAY_TOKEN` is — per current Railway docs and community help threads — reserved for **project tokens** (header `Project-Access-Token:`), while the workflow's `{me{id}}` validator only works with **account/workspace tokens** (header `Authorization: Bearer`). The mismatch means rotators are pushed toward account tokens, which are subject to silent revocation via OAuth refresh-token rotation and a 100-token cap. That is why "rotate again with No expiration" has now failed 28 times in a row.

### Evidence Chain

WHY: Run #25196397105 conclusion is `failure`; `deploy-production` is `skipped`.
↓ BECAUSE: `deploy-staging` → `Validate Railway secrets` exited with code 1.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-01T00:34:51.5402052Z`.

↓ BECAUSE: Railway GraphQL `{me{id}}` probe returned no `data.me.id`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-01T00:34:51.5387076Z`.

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
  has not stuck for 28 cycles.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change for the immediate fix. Resolution is a credential rotation in GitHub Actions secrets. The structural fix (rename env var to `RAILWAY_API_TOKEN`, or switch to project-token + `Project-Access-Token` header) is OUT OF SCOPE for this bead — see scope boundaries. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the failing step).
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `deploy-staging` is fixed).
- `.github/workflows/railway-token-health.yml` — periodic token health probe; rotating the secret will turn this green.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook.
- `RAILWAY_SECRETS.md` — secret naming reference.

### Git History

- **Failing SHA**: `5f00e50` (the merge of #819, the 27th investigation) is the commit `pipeline-health-cron.sh` reports as the failed deploy.
- **Pattern**: 27 prior `RAILWAY_TOKEN expiration` recurrences (most recent: `#818` → `5f00e50` on `main`). This is the 28th, anchored sequentially to the prior #819 label.
- **Implication**: Long-standing operational issue, not a code regression. The fix is durable token hygiene (and likely a structural rename of the env var / change of validator) — not a code change in `backend/` or `frontend/`.

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
4. `gh run rerun 25196397105 --repo alexsiri7/reli --failed`.
5. Close issue #821 once CI is green.

**Why a workspace token (and "No expiration") for the IMMEDIATE fix:**

- Railway officially recommends workspace tokens for "Team CI/CD" (`docs.railway.com/integrations/api`).
- Workspace tokens use the same `Authorization: Bearer $RAILWAY_TOKEN` header that the current validator already issues at `staging-pipeline.yml:50` and `:167` — no workflow change required *today*.
- The existing `{me{id}}` probe at `staging-pipeline.yml:49-58` and `:166-175` continues to work with workspace tokens.
- They support **"No expiration"** — accepting the default short TTL is exactly why this has now recurred 28 times.
- **Do NOT pick a project token for this rotation** — those use a `Project-Access-Token` header and `{me{id}}` would fail immediately even with a fresh token. (If the human prefers project tokens for least-privilege, that is a *workflow change*, not a secret rotation, and belongs in the structural-fix bead — see "Out of Scope".)

### Step 2: (No code or test changes)

This is a credential rotation, not a software change. There is nothing to type-check, lint, or test from the agent side.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#819, #817, #815, #813, #812, #809, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

What's *new* compared to prior recurrences: this artifact references the parallel web research (`web-research.md` in this same `runs/` directory) and explicitly carves out the structural fix as a separate bead so the next investigating agent does not have to re-derive it.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_821.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human picks a project token instead of a workspace token while leaving the current validator in place. | The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) and Step 1 above explicitly call out workspace tier; the `{me{id}}` validate step would fail immediately with a project token, surfacing the mistake on the very next run. |
| New token also expires (29th recurrence). | Use **"No expiration"** at creation time. Even with that, account/workspace tokens can be silently revoked (Railway OAuth troubleshooting docs); the durable fix is the structural change in the separate bead, not another rotation. |
| Re-run fails because GitHub workflow_run rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |
| Pipeline-health-cron files a 29th issue before rotation completes. | The `archon:in-progress` label on #821 already prevents pickup-cron double-fire; if a *new* failed run produces a *new* issue, close it as duplicate of #821. |

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
- Posting a structured investigation comment on issue #821.
- Linking to the parallel web research that identifies the structural cause.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden by `CLAUDE.md`).
- The structural fix (rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`, or switch validator to `Project-Access-Token: ...` + `{ projectToken { projectId } }`, or move to a self-hosted Railway runner). These are real fixes, but they require human design decisions (which token class, which header, runner cost trade-off) and a separate bead/PR. Per Polecat scope discipline, send mail to mayor recommending a follow-up bead instead of widening this one.
- Refactoring the validate step or the workflow to swallow auth errors.
- Replacing the cron health filer (`pipeline-health-cron.sh`).
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T02:10:00Z
- **Artifact**: `artifacts/runs/4ed26d36563fb01c00495876b0c85411/investigation.md`
- **Companion**: `artifacts/runs/4ed26d36563fb01c00495876b0c85411/web-research.md` (structural-cause findings)
