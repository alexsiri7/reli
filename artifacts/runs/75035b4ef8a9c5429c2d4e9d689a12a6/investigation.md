# Investigation: Main CI red — Deploy to staging (32nd RAILWAY_TOKEN expiration)

**Issue**: #832 (https://github.com/alexsiri7/reli/issues/832)
**Type**: BUG
**Investigated**: 2026-05-01T05:05:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging→prod auto-promotion on every push to `main` is broken because `Validate Railway secrets` exits 1 on the failing SHA `d01d31c` (the merge of #830, the 31st investigation); downstream `staging-e2e` and `deploy-production` are skipped. No prod data is at risk and a documented (human-only) rotation workaround exists, so HIGH rather than CRITICAL. |
| Complexity | LOW | The immediate fix is a single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit. (The durable structural fix is deferred to a separate bead — see "Out of Scope".) |
| Confidence | HIGH | Run `25201008471` emits the exact branch the validate step is designed to surface (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `.github/workflows/staging-pipeline.yml:55`, and this is the 32nd occurrence of an identical failure shape — the prior 31 investigations (`#828`/`#829` → 31st, `#825` → 30th, `#824` → 29th, `#821`/`#820` → 28th, `#818` → 27th, …) all share this root cause. |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at `Validate Railway secrets` because the `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked) again. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, the deploy step exits 1, and the downstream `staging-e2e` and `deploy-production` jobs are skipped. `pipeline-health-cron.sh` then files this as "Main CI red: Deploy to staging" (#832), with a sibling "Prod deploy failed on main" (#833) filed seconds later by the cross-trigger.

**Agents cannot fix this** — the rotation requires a human with railway.com dashboard access (per `CLAUDE.md > Railway Token Rotation`).

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` secret is again expired/revoked. This is the same failure mode as #828/#829 (31st), #825 (30th), #824 (29th), #821/#820 (28th), #818 (27th), #816 (26th), #814 (25th), #811 (24th), #810 (23rd), and 22 prior recurrences before that. Cadence is now ~daily, not ~weekly.

Web research conducted in parallel (companion artifact: `artifacts/runs/75035b4ef8a9c5429c2d4e9d689a12a6/web-research.md`) confirms the structural cause beneath the immediate one and **materially refines** the prior #828/#829 finding:

- Per Railway's own help-station thread (web-research finding #1), **`RAILWAY_TOKEN` now only accepts project tokens** — account tokens fail with the same "invalid or expired" message regardless of how recently they were issued.
- Per Railway's API docs (finding #2), **project tokens use the `Project-Access-Token` header**, not `Authorization: Bearer …`.
- Per finding #2, the `{me{id}}` query the validator uses is an *account-level* query — **project tokens are rejected by it** even when they work for `railway up`.

This means the workflow's `Validate Railway secrets` step at `.github/workflows/staging-pipeline.yml:49-58` and `:166-175` is in a **structural deadlock**: the env-var name (`RAILWAY_TOKEN`) only accepts a token class the validator's probe rejects. Whatever token has been keeping the pipeline green between rotations is doing so under a transient condition (e.g. an account token that Railway has not yet enforced the new project-only rule against, or a token still inside an OAuth refresh window). That window is closing — and that is why the cadence has shortened from ~weekly to ~daily and why "rotate again" no longer holds. **The 31st rotation guidance ("use a personal/account token") is now actively wrong.**

### Evidence Chain

WHY: Run `25201008471` conclusion is `failure`; `staging-e2e` and `deploy-production` are `skipped`.
↓ BECAUSE: `deploy-staging` → `Validate Railway secrets` exited with code 1.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-01T03:35:25.3473833Z`.

↓ BECAUSE: Railway GraphQL `{me{id}}` probe returned no `data.me.id`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-01T03:35:25.3464082Z`.

↓ ROOT CAUSE (immediate): The `RAILWAY_TOKEN` GitHub Actions secret has expired (or been revoked).
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the validate step issues
  `curl -sf -X POST https://backboard.railway.app/graphql/v2 ... '{"query":"{me{id}}"}'`
  and exits 1 when the response lacks `.data.me.id`. The error message is the exact
  branch the workflow takes when Railway rejects the token.

↓ ROOT CAUSE (structural, recurring): Token-class deadlock between env-var name and validator.
  Evidence: Web-research finding #1 (`RAILWAY_TOKEN` *only* accepts project tokens; account
  tokens fail with the same "invalid or expired" message), web-research finding #2
  (project tokens require `Project-Access-Token` header AND the `{me{id}}` query is
  account-level — project tokens are rejected by it). The Reli workflow uses
  `Authorization: Bearer` + `{me{id}}`, which is the **account-token** API shape against
  an env var (`RAILWAY_TOKEN`) that **rejects account tokens**. There is no token class
  that satisfies both layers as currently written. This is why the 32-cycle pattern persists
  and why the cadence is shortening: the historical pattern of "rotate to an account token
  and pray" is colliding with Railway's tightening of the project-only rule.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source/workflow change for the immediate fix. Resolution is a credential rotation in GitHub Actions secrets. The structural fix (rename env var to `RAILWAY_API_TOKEN` + use account token, OR switch validator to `Project-Access-Token` header + a project-scoped query, OR drop the `{me{id}}` preflight entirely) is OUT OF SCOPE for this bead — see scope boundaries. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging-side `Validate Railway secrets` (the failing step in run `25201008471`).
- `.github/workflows/staging-pipeline.yml:149-175` — production-side `Validate Railway secrets` (would fail identically once `deploy-staging` is fixed).
- `.github/workflows/railway-token-health.yml` — periodic token health probe; rotating the secret will turn this green.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook. **Now known to direct operators to the wrong page** (`railway.com/account/tokens` is the *account* tokens page; per finding #1, `RAILWAY_TOKEN` requires a *project* token from Project Settings → Tokens). Updating the runbook is part of the structural-fix bead, not this one.
- `DEPLOYMENT_SECRETS.md` — secret setup + rotation reference (the doc the workflow's own error messages point to at `staging-pipeline.yml:46, :56, :163, :173`).
- `RAILWAY_SECRETS.md` — supplementary secret naming reference.

### Git History

- **Failing SHA**: `d01d31c4b2967bade1b7fd20d1b928b2866821d1` (the merge of #830, the 31st investigation PR for #828). This is the SHA `pipeline-health-cron.sh` reports as the failed deploy in run `25201008471`.
- **Pattern**: 31 prior `RAILWAY_TOKEN expiration` recurrences (most recent: `#828`/`#829` → 31st on 2026-05-01 ~02:30Z, this run ~03:35Z — under one hour later). This is the 32nd, anchored sequentially after #830/#831.
- **Implication**: Long-standing operational issue, not a code regression. The accelerating cadence (weekly → daily → hourly) is consistent with Railway tightening enforcement of the project-token-only rule on `RAILWAY_TOKEN`. The fix is a structural workflow change, not another rotation.

---

## Implementation Plan

> **No code change. Human-only credential rotation.** Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt claiming rotation is done. That is a Category 1 error.

### Step 1: Rotate the Railway token (HUMAN) — REVISED FROM #828/#829

**File**: GitHub Actions secret `RAILWAY_TOKEN` (no file in repo).
**Action**: REPLACE secret value, AND coordinate a workflow change because of the validator deadlock.

**Required actions (read this carefully — guidance differs from prior cycles):**

1. **Generate a project token** from the Railway *project* dashboard: Project → Settings → Tokens. **Do not use** `https://railway.com/account/tokens` (that creates an account token, which `RAILWAY_TOKEN` now rejects per web-research finding #1).
2. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the new project token.
3. **Expect the validate step to still fail** even with a fresh project token, because `{me{id}}` is an account-level query and rejects project tokens (web-research finding #2). To unblock the pipeline you will need EITHER (a) a one-line workflow patch that drops or replaces the `{me{id}}` preflight, OR (b) bypass via `workflow_dispatch` skipping the validate step. This is the structural-fix bead — see "Out of Scope" — but it has now become a prerequisite for the next green run, not a nice-to-have.
4. After the workflow change AND the rotation are both in place: `gh run rerun 25201008471 --repo alexsiri7/reli --failed` (or push a no-op commit to retrigger).
5. Close issues #832 and #833 once CI is green.

**Why the #828/#829 guidance ("use a personal/account token") is now wrong:**

- #828 advised the human to install a personal/account token because the validator's `{me{id}}` probe accepts only that class. That guidance was based on *which class the validator accepts* without checking *which class the env var accepts* on the deploy side.
- Web-research finding #1 in this run shows `RAILWAY_TOKEN` only accepts project tokens. Account tokens now produce the exact "invalid or expired: Not Authorized" message we are seeing — even when freshly created.
- The accelerating cadence (31st → 32nd in under one hour) is consistent with Railway enforcing the project-only rule more aggressively. Continuing to rotate account tokens will produce a 33rd, 34th, … in shorter and shorter intervals.
- **Bottom line**: rotating alone will not break the cycle this time. The validator deadlock must be resolved in the same change.

### Step 2: (No code or test changes in this bead)

This investigation is a credential rotation + a recommendation that the structural fix bead (separate) is now load-bearing. There is nothing to type-check, lint, or test from the agent side.

### Step 3: Send mail to mayor recommending the structural fix bead

Per Polecat scope discipline, the workflow change cannot be made inside this bead. Send mail recommending a follow-up bead that:

- Updates `.github/workflows/staging-pipeline.yml:49-58` and `:166-175` to use a project-token-compatible probe (e.g. `Project-Access-Token: $RAILWAY_TOKEN` + a project-scoped GraphQL query, or just drop the preflight and let `serviceInstanceUpdate` surface auth errors).
- Updates `docs/RAILWAY_TOKEN_ROTATION_742.md` to direct operators to **Project Settings → Tokens**, not `railway.com/account/tokens`.
- Optionally replaces the validate step entirely with `railway whoami` against the project token, which is the canonical CLI check.

Without this bead, the next rotation will fail the same way and we will be back at issue #834+ within hours.

---

## Patterns to Follow

This investigation follows the established pattern from prior recurrences (#830/#831, #826/#827, #822/#823, #819, #817, …): document the failure mode, point at the runbook, and stop. No documentation receipt, no code edit, no fabricated "fixed" PR.

What changes vs. #828/#829: the parallel `web-research.md` (in the same `runs/` directory) found Railway's project-token-only enforcement on `RAILWAY_TOKEN`, which **invalidates the prior cycle's "use a personal/account token" recommendation**. The structural fix is no longer optional — it is the prerequisite for the next green run.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_832.md` claiming rotation is done. | Forbidden by `CLAUDE.md > Railway Token Rotation` (Category 1 error). This investigation explicitly does NOT create such a file. |
| Human follows the prior cycle's guidance and installs another account token. | Per web-research finding #1, account tokens are now rejected by `RAILWAY_TOKEN` itself — the rotation will produce the same `Not Authorized` on the very next run. Step 1 above explicitly directs the human to a *project* token from Project Settings → Tokens. |
| Human installs a project token but leaves the validator untouched. | The `{me{id}}` probe will reject the project token (finding #2), the rotation will appear to "fail" even though the deploy itself would succeed. Step 1 calls this out and Step 3 mails mayor for the workflow change that must accompany the rotation. |
| New token also fails (33rd recurrence inside the day). | Cadence has accelerated from weekly → hourly. Without the structural fix, each rotation buys less time than the last. The mail to mayor (Step 3) treats the structural fix as load-bearing, not optional. |
| Re-run fails because GitHub workflow_run rerun is not allowed for completed runs from a different SHA. | If `gh run rerun --failed` is rejected, push a no-op commit to `main` (or use `workflow_dispatch`) to retrigger the staging pipeline. |
| Pipeline-health-cron files a 33rd issue (and a sibling "Prod deploy failed" alert) before rotation+structural-fix completes. | The `archon:in-progress` label on #832 already prevents pickup-cron double-fire on the same number. The cross-trigger duplicate filing already produced sibling #833; close #833 as duplicate of #832 once CI is green. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` runbook contains the "No expiration" instruction with no public Railway docs to corroborate (web-research finding #3). | This is a known runbook bug; the structural-fix bead must update the runbook. Out of scope for #832. |

---

## Validation

### Automated Checks (after human rotation + workflow patch)

```bash
gh run rerun 25201008471 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
```

Expected outcome:

- `Validate Railway secrets` passes (with the new project-token-compatible probe).
- Staging deploy reaches Railway; staging E2E smoke tests run against `RAILWAY_STAGING_URL`.
- `Deploy to production` proceeds and `/healthz` on `RAILWAY_PRODUCTION_URL` returns ok.
- `railway-token-health.yml` reports green on its next scheduled run.

### Manual Verification

1. `gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN` shows an updated timestamp.
2. The new run for `Staging → Production Pipeline` against `main` completes successfully end-to-end.
3. No new "Main CI red" or "Prod deploy failed" issues filed within the next 24 hours.

---

## Scope Boundaries

**IN SCOPE:**

- Documenting the 32nd recurrence with evidence and pointing at the rotation runbook.
- Posting a structured investigation comment on issue #832.
- Linking to the parallel web research that *invalidates* the #828/#829 token-class recommendation.
- Recommending (via mail to mayor) that the structural fix bead is now a prerequisite, not optional.

**OUT OF SCOPE (do not touch):**

- Rotating the token (human-only).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` receipt file (forbidden by `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml` to fix the validator deadlock (real fix, separate bead).
- Updating `docs/RAILWAY_TOKEN_ROTATION_742.md` to direct operators to Project Settings → Tokens (separate bead).
- Replacing `{me{id}}` with a project-scoped probe or a `railway whoami` invocation (separate bead).
- Refactoring the validate step or the workflow to swallow auth errors.
- Replacing the cron health filer (`pipeline-health-cron.sh`).
- Closing #833 (sibling cross-trigger issue) — that is a separate housekeeping action after the green run.
- Migrating off Railway (tracked separately in #629).
- Any code change in `backend/`, `frontend/`, or `docker-compose.yml`.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-01T05:05:00Z
- **Artifact**: `artifacts/runs/75035b4ef8a9c5429c2d4e9d689a12a6/investigation.md`
- **Companion**: `artifacts/runs/75035b4ef8a9c5429c2d4e9d689a12a6/web-research.md` (refines #828/#829 token-class guidance — `RAILWAY_TOKEN` only accepts project tokens, validator's `{me{id}}` rejects them)
