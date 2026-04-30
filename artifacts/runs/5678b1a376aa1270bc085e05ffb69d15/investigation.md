# Investigation: Main CI red — Deploy to staging (18th `RAILWAY_TOKEN` expiration)

**Issue**: #793 (https://github.com/alexsiri7/reli/issues/793)
**Type**: BUG
**Investigated**: 2026-04-30T13:45:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The `Validate Railway secrets` pre-flight at `.github/workflows/staging-pipeline.yml:32-58` is still aborting every staging deploy on `main`. Run `25166984244` (13:04:41Z, the run this issue cites) and the sibling run `25166974929` (13:04:30Z, same SHA `73faa415`) both failed with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. No deploy can land until a human rotates the secret. |
| Complexity | LOW | No code change is permitted (per `CLAUDE.md` § "Railway Token Rotation"); the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md`. The artifact-only output mirrors PRs #780/#782/#784/#787/#788/#791/#792. |
| Confidence | HIGH | The CI log emits the canonical error string verbatim at `2026-04-30T13:04:54.1759439Z`: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`. Issues #789 (17th CI twin) and #790 (17th prod twin) were filed and merged via PRs #791/#792 only ~70 minutes before this run failed on the merge SHA `73faa415` — proving the secret was not rotated in that window. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` calls Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, and aborts the deploy.

This is the **18th identical recurrence**. Per `CLAUDE.md`, **agents cannot rotate the Railway API token**. This issue requires a human with access to https://railway.com/account/tokens.

---

## Analysis

### First-Principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Validate-Railway-secrets pre-flight | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Failing closed correctly. The probe (`Authorization: Bearer` + `{me{id}}`) is account/workspace-token-shaped — it is not the bug. |
| `RAILWAY_TOKEN` GitHub secret | (GitHub Actions secret store) | No | The token itself has expired again. Recurring-failure surface. |
| Token rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Yes | Canonical, no edit required. |
| Re-fire suppression label | `archon:in-progress` on the issue | Partial | Stops *this* issue from re-firing, but a fresh staging-pipeline run on the next merge files a *new* duplicate (e.g. #793 is one of 18). The cron loop-stopper is the missing primitive (P0 follow-up below). |

The primitive that is unsound is **the secret itself** (a long-lived PAT whose TTL keeps lapsing). The validate step is the messenger. Do not shoot the messenger.

### Root Cause

WHY: run `25166984244` failed at the `Deploy to staging / Validate Railway secrets` step at 13:04:54Z
↓ BECAUSE: Railway returned `Not Authorized` to the `{me{id}}` GraphQL probe (`.github/workflows/staging-pipeline.yml:49-58`)
↓ BECAUSE: `secrets.RAILWAY_TOKEN` is still expired even after the merges of investigation PRs #780/#782/#784/#787/#788/#791/#792 at ~10:00Z–~13:00Z today
↓ ROOT CAUSE: prior rotations (or the latest one not yet performed) created Railway tokens with a finite TTL instead of selecting **No expiration**, *or* the token type does not match what the `{me{id}}` probe expects. **No human has yet performed the rotation that resolves the current expiry window.**

### Evidence Chain

WHY: run `25166984244` failed
↓ BECAUSE: `Validate Railway secrets` step exited 1
  Evidence: `staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' …; then echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"; exit 1; fi`

↓ BECAUSE: Railway responded `Not Authorized`
  Evidence: CI log `2026-04-30T13:04:54.1759439Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: the GraphQL probe was rejected
  Evidence: `staging-pipeline.yml:49-52` — `curl -sf -X POST "https://backboard.railway.app/graphql/v2" -H "Authorization: Bearer $RAILWAY_TOKEN" … -d '{"query":"{me{id}}"}'`

↓ ROOT CAUSE: `secrets.RAILWAY_TOKEN` is expired/invalid
  Evidence: identical failure on the sibling run `25166974929` at 13:04:30Z on the same SHA `73faa415`; identical lineage across 17 prior issues (#789/#790/#785/#786/#783/#781/#779/#777/#774/#773/#771/#769/#766/#762/#755/#751/#742).

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/5678b1a376aa1270bc085e05ffb69d15/investigation.md` | NEW | CREATE | This investigation artifact |
| `artifacts/runs/5678b1a376aa1270bc085e05ffb69d15/web-research.md` | NEW | CREATE | Companion web-research (already produced for this run) |
| (no source files) | — | — | Per `CLAUDE.md`, do not edit `.github/workflows/staging-pipeline.yml`; it is failing closed correctly. Do not create `.github/RAILWAY_TOKEN_ROTATION_*.md` (Category 1 error). |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight that surfaces the failure
- `.github/workflows/staging-pipeline.yml:60-90` — `Deploy staging image to Railway` step (gated by the pre-flight)
- `.github/workflows/railway-token-health.yml` — manual health probe to verify a fresh secret
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook (referenced by `CLAUDE.md`)

### Git History

- `73faa41 docs: investigation for issue #790 (17th RAILWAY_TOKEN expiration) (#791)` — the merge commit on which run `25166984244` was triggered. PRs #780/#782/#784/#787/#788/#791/#792 are the recent investigation-only follow-ups. The pattern is well-established: each merge to `main` re-fires staging-pipeline → validate-secrets → fail → cron files a new issue.

---

## Lineage (18 occurrences)

| # | Issue | Investigation PR |
|---|-------|------------------|
| 1-13 | #733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #773 / #774 → #777 → #779 | (see prior PRs) |
| 14 | #781 | #782 |
| 15 | #783 | #784 |
| 16 (CI twin) | #785 | #788 |
| 16 (prod twin) | #786 | #787 |
| 17 (CI twin) | #789 | #792 |
| 17 (prod twin) | #790 | #791 |
| **18 (CI twin)** | **#793** | **(this PR)** |
| 18 (prod twin) | #794 | (separate sibling task) |

> **Counting note**: Row `1-13` is a compressed history. `#733` and `#739` are precursor issues that predate the canonical `RAILWAY_TOKEN` expiration pattern (which starts at `#742`); they are listed for historical traceability but are **not** part of the "17 prior issues" enumerated in the prose at line 58. `#762` appears twice within the row because the original issue re-fired and is counted as a separate occurrence; `#773 / #774` share a slot because they were filed for the same occurrence (CI/prod twins). The total — `13` (row 1) + `4` rows for #14–#17 + `1` for #18 = `18` — agrees with the prose; the row-1 label compresses 13 occurrences spread across 14 issue references.

---

## Implementation Plan

> **If anything below differs from `docs/RAILWAY_TOKEN_ROTATION_742.md`, the runbook wins.** This Implementation Plan is a convenience summary, not the source of truth.

### Step 1: (Human-only) Mint a new Railway token with no expiration

**Action**: Visit https://railway.com/account/tokens → create a token (account- or workspace-scoped to match the prior working token; the existing `{me{id}}` probe at `staging-pipeline.yml:49-52` requires Bearer-compatible auth) with **Expiration: No expiration**. Suggested name: `github-actions-permanent`. Defer to `docs/RAILWAY_TOKEN_ROTATION_742.md` for any conflict.

**Why**: Prior rotations have used finite-TTL tokens, producing this recurring failure mode. A no-expiration token of the **same type that previously authenticated `{me{id}}` over Bearer** breaks the cycle without requiring a probe change while the secret is expired (see `web-research.md` Findings 1, 2, 3 & 5 and the third item under "Gaps and Conflicts" on token-type mismatch).

---

### Step 2: (Human-only) Update the GitHub secret

**Action**:
```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# paste the token from Step 1
```

**Why**: This is the only fix that resolves the root cause. Agents cannot perform this step.

---

### Step 3: Verify with the health-probe workflow

**Action**:
```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1
```

**Expect**: success.

---

### Step 4: Re-run the failed deploys

**Action**:
```bash
gh run rerun 25166984244 --repo alexsiri7/reli --failed
gh run rerun 25166974929 --repo alexsiri7/reli --failed
```

**Expect**: green deploys.

---

### Step 5: Close the issues and clear the labels

**Action**:
```bash
gh issue close 793 --repo alexsiri7/reli --reason completed
gh issue edit 793 --repo alexsiri7/reli --remove-label archon:in-progress
gh issue close 794 --repo alexsiri7/reli --reason completed
gh issue edit 794 --repo alexsiri7/reli --remove-label archon:in-progress
```

---

## Patterns to Follow

This investigation mirrors the immediately prior occurrences:

- PR #780 (issue #779, 13th) — investigation-only artifact + lineage update
- PR #782 (issue #781, 14th) — same shape
- PR #784 (issue #783, 15th) — same shape
- PR #788 (issue #785, 16th CI-pipeline twin) — same shape
- PR #787 (issue #786, 16th prod twin) — same shape
- PR #792 (issue #789, 17th CI-pipeline twin) — same shape
- PR #791 (issue #790, 17th prod twin) — same shape

Mirror the file structure: artifact + comment, no workflow edits, no `.github/RAILWAY_TOKEN_ROTATION_*.md`.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires another duplicate issue while #793 is open | The cron checks the `archon:in-progress` label; do not remove the label until rotation lands. |
| Human masks the failure by editing the validate-secrets step | **Do not.** That step is failing closed correctly — masking it would let the deploy step silently fail later, in the middle of a real production push. |
| Newly-minted token expires again in 30 days | Insist on **No expiration** at token creation. Anything else perpetuates the loop. |
| Token-type mismatch (account vs. workspace token) for `{me{id}}` probe | Tracked as a P2 follow-up (filed below). Do not change the probe while the secret is expired — the failure signal is currently load-bearing. |
| Sibling issue #794 re-fires from the same root cause | Single rotation resolves both. Close both after Step 4. |

---

## Validation

### Automated Checks

```bash
# Verify the artifact lands and the PR opens
git diff --stat HEAD~1 HEAD
gh pr view --json checks
```

There is no source code change, so type-check / lint / tests are N/A.

### Manual Verification (post-rotation)

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25166984244 --repo alexsiri7/reli --failed
gh run rerun 25166974929 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 3
```

Expect three consecutive `success` conclusions on `staging-pipeline.yml`.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact
- Companion `web-research.md` (already produced)
- GitHub comment on #793
- Lineage update (17 → 18)

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — failing closed correctly, do not mask
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical, no change needed
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` — Category 1 error per `CLAUDE.md`
- Performing the rotation — agent-out-of-scope per `CLAUDE.md`
- Issue #794 (prod twin) — handled in its own sibling task; same root cause, single rotation fixes both

---

## Suggested Follow-up Issues

To be filed by a human after rotation lands (carried forward from #786/#788/#789/#790):

1. **Cron loop-stopper for `archon:in-progress` re-fire** (P0) — 18 occurrences on the same expired secret. Gate cron re-firing on a successful `railway-token-health` run, not just the absence of an open sibling.
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — service-account or scheduled-rotation automation. Web research confirms Railway does not yet support GitHub OIDC, so the realistic options are no-expiration token + scheduled rotation tooling.
3. **Reconcile `{me{id}}` validation-query token-type mismatch** (P2) — switch to a project-scoped probe if migrating to project tokens (which would also require swapping `Authorization: Bearer` → `Project-Access-Token` everywhere in `staging-pipeline.yml`). **Do not do this while the secret is expired** — masks the failure signal.
4. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against `.app` retirement.
5. **Rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI now treats `RAILWAY_TOKEN` as project-only; renaming avoids ambiguity if the workflow ever moves from raw GraphQL to the CLI.

---

## Runbook

See `docs/RAILWAY_TOKEN_ROTATION_742.md` for the canonical rotation steps.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T13:45:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/5678b1a376aa1270bc085e05ffb69d15/investigation.md`
