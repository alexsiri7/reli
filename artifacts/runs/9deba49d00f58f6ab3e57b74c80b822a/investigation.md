# Investigation: Main CI red — Deploy to staging (31st RAILWAY_TOKEN expiration)

**Issue**: #828 (https://github.com/alexsiri7/reli/issues/828)
**Type**: BUG
**Investigated**: 2026-05-01T03:45:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→prod auto-promotion on every push to `main` is broken because `Validate Railway secrets` exits 1 on the failing SHA `afbf134`; downstream `staging-e2e` and `deploy-production` are skipped. No prod data is at risk and a documented (human-only) rotation workaround exists, so HIGH rather than CRITICAL. |
| Complexity | LOW | The immediate fix is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit. (The durable structural fix is deferred to a separate bead — see "Out of Scope".) |
| Confidence | HIGH | Run `25199559238` emits the exact branch the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 31st occurrence of an identical failure shape — the prior 30 investigations (`#825` → 30th, `#824` → 29th, `#821` → 28th [prod companion], `#820` → 28th [staging], `#818` → 27th, …) all share this root cause. |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked) again. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the deploy step exits 1, and the downstream `staging-e2e` and `deploy-production` jobs are skipped. `pipeline-health-cron.sh` then files this as "Main CI red: Deploy to staging".

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #825 (30th), #824 (29th), #821 (28th [prod companion]), #820 (28th [staging]), #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd), and 22 prior recurrences before that.

Web research conducted in parallel (artifact: `artifacts/runs/9deba49d00f58f6ab3e57b74c80b822a/web-research.md`) confirms the structural cause beneath the immediate one and refines the prior #824 finding: Railway has three token types with different validation surfaces. The workflow's env-var name `RAILWAY_TOKEN` is — per Railway's own help-station threads — reserved for **project tokens** (header `Project-Access-Token:`); meanwhile the validator's `Authorization: Bearer` + `{me{id}}` shape only resolves for **personal/account tokens** (workspace tokens *also* reject `{me{id}}`). The mismatch pushes rotators toward account tokens, which are subject to silent revocation via Railway's OAuth refresh-token rotation. That is why "rotate again with No expiration" has now failed 31 times in a row.

### Evidence Chain

WHY: Run `25199559238` conclusion is `failure`; `deploy-production` is `skipped`.
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
  Evidence: Web-research finding #1 (`Project-Access-Token` header required for project tokens) and
  finding #2 (workspace tokens *also* fail `{me{id}}`, not only project tokens). The Reli workflow
  validates with `Authorization: Bearer` + `{me{id}}`, which only works with personal/account tokens —
  and those are subject to silent revocation per Railway's OAuth troubleshooting docs. This is why
  "rotate again" has not stuck for 31 cycles.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change for the immediate fix. Resolution is a credential rotation in GitHub Actions secrets. The structural fix (rename env var to `RAILWAY_API_TOKEN`, or switch to project-token + `Project-Access-Token` header, or replace the validator with one compatible with workspace tokens) is OUT OF SCOPE for this bead — see scope boundaries. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the failing step in run `25199559238`).
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `deploy-staging` is fixed).
- `.github/workflows/railway-token-health.yml` — periodic token health probe; rotating the secret will turn this green.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook.
- `DEPLOYMENT_SECRETS.md` — secret setup + rotation reference (the doc the workflow's own error messages point to at `staging-pipeline.yml:46, :56, :163, :173`).
- `RAILWAY_SECRETS.md` — supplementary secret naming reference.

### Git History

- **Failing SHA**: `afbf134` (the merge of #826, the 29th investigation). This is the SHA `pipeline-health-cron.sh` reports as the failed deploy in run `25199559238`.
- **Pattern**: 30 prior `RAILWAY_TOKEN expiration` recurrences (most recent: `#825` → run `25198048549` on `main`). This is the 31st, anchored sequentially after #826 / #827.
- **Implication**: Long-standing operational issue, not a code regression. The fix is durable token hygiene (and likely a structural rename of the env var / change of validator) — not a code change in `backend/` or `frontend/`.

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
4. `gh run rerun 25199559238 --repo alexsiri7/reli --failed`.
5. Close issue #828 once CI is green.

**Why a personal/account token for the IMMEDIATE fix (refined from #824/#825):**

- The current validator at `staging-pipeline.yml:49-58` (and `:166-175`) issues `Authorization: Bearer $RAILWAY_TOKEN` against `{me{id}}`. Per web-research finding #2, **workspace tokens reject `{me{id}}`** ("cannot be performed [...] including printing information about the user"); per finding #1, project tokens require the `Project-Access-Token` header instead. **Personal/account is the only token class that the existing validate step accepts.**
- Personal tokens are subject to silent revocation via OAuth refresh-token rotation — this is why the 31-cycle pattern persists. The durable fix is to change the validator (so a workspace or project token can be used), not to keep rotating personal tokens.
- **Do NOT pick a project token for this rotation** — `{me{id}}` would fail immediately even with a fresh token.
- **Do NOT pick a workspace token for this rotation** either — same reason; the `{me{id}}` probe rejects it. (This is a refinement over the #824/#825 guidance, which suggested workspace tokens would work; web research finding #2 in this run shows that recommendation was incorrect for the *current* validator shape.)
- If the human prefers workspace or project tokens for least-privilege, that is a *workflow change*, not a secret rotation, and belongs in the structural-fix bead — see "Out of Scope".

### Step 2: (No code or test changes)

This is a credential rotation, not a software change. There is nothing to type-check, lint, or test from the agent side.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#826/#827, #822/#823, #819, #817, #815, #813, #812, #809, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

What carries forward from #824/#825: the parallel `web-research.md` in this same `runs/` directory identifies the structural cause (env-var-name vs. token-class mismatch) — and *refines* the prior workspace-token recommendation now that the workflow validator's incompatibility with workspace tokens has been confirmed. The structural fix remains carved out as a separate bead per Polecat scope discipline.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_828.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human picks a workspace or project token while leaving the current validator in place. | Per web-research finding #2, workspace tokens reject `{me{id}}`; per finding #1, project tokens use the wrong header. Step 1 above explicitly directs the human to a personal/account token; the `{me{id}}` validate step would fail immediately on the wrong class, surfacing the mistake on the very next run. |
| New token also expires (32nd recurrence). | Personal tokens can be silently revoked even with "No expiration" set (Railway OAuth troubleshooting docs); the durable fix is the structural change in the separate bead, not another rotation. Mail to mayor recommending the structural fix is a prerequisite for breaking the cycle. |
| Re-run fails because GitHub workflow_run rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |
| Pipeline-health-cron files a 32nd issue (and a sibling "Prod deploy failed" alert) before rotation completes. | The `archon:in-progress` label on #828 already prevents pickup-cron double-fire on the same number. The cross-trigger duplicate-filing gap (#824 ↔ #825) is a known cron bug already mailed to mayor; if a new failed run produces a new issue, close as duplicate of #828. |

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

---

## Scope Boundaries

**IN SCOPE:**

- Documenting the 31st recurrence with evidence and pointing at the rotation runbook.
- Posting a structured investigation comment on issue #828.
- Linking to the parallel web research that identifies the structural cause and refines the prior token-class recommendation.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden by `CLAUDE.md`).
- The structural fix (rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`, or switch validator to `Project-Access-Token: ...` + a project-scoped query, or replace `{me{id}}` with a workspace-compatible probe, or move to a self-hosted Railway runner). These are real fixes, but they require human design decisions (which token class, which header, runner cost trade-off) and a separate bead/PR. Per Polecat scope discipline, send mail to mayor recommending a follow-up bead instead of widening this one.
- Refactoring the validate step or the workflow to swallow auth errors.
- Replacing the cron health filer (`pipeline-health-cron.sh`).
- Fixing the cross-trigger duplicate-filing gap (#824 ↔ #825) — already mailed to mayor.
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T03:45:00Z
- **Artifact**: `artifacts/runs/9deba49d00f58f6ab3e57b74c80b822a/investigation.md`
- **Companion**: `artifacts/runs/9deba49d00f58f6ab3e57b74c80b822a/web-research.md` (structural-cause findings, refining #824/#825 token-class guidance)
