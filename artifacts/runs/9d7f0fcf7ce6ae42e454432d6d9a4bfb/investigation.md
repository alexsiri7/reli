# Investigation: Prod deploy failed on main (17th `RAILWAY_TOKEN` expiration)

**Issue**: #790 (https://github.com/alexsiri7/reli/issues/790)
**Type**: BUG
**Investigated**: 2026-04-30T12:30:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The `Validate Railway secrets` pre-flight at `.github/workflows/staging-pipeline.yml:32-58` is still aborting every prod deploy on `main`. Run `25164454478` (12:07:21Z, the run this issue cites) and the sibling run `25164359158` (12:04:56Z, same SHA `2fbf1e60`) both failed with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. No deploy can land until a human rotates the secret. |
| Complexity | LOW | No code change is permitted (per `CLAUDE.md` § "Railway Token Rotation"); the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md`. The artifact-only output mirrors PRs #780/#782/#784/#787/#788. |
| Confidence | HIGH | The CI log emits the canonical error string verbatim at `2026-04-30T12:07:21.4404355Z`: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`. Issues #785 (16th CI twin) and #786 (16th prod twin) were filed at 11:30:28Z / 11:30:32Z and closed at 12:00:14Z / 12:00:19Z — within minutes before this run failed. #790 was then filed at 12:30:28Z on `2fbf1e60` (the merge commit of #787, the investigation PR for #786), proving the secret was not rotated in that window. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` calls Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, and aborts the deploy.

This is the **17th identical recurrence**. Per `CLAUDE.md`, **agents cannot rotate the Railway API token**. This issue requires a human with access to https://railway.com/account/tokens.

---

## Analysis

### Root Cause

WHY: run `25164454478` failed at the `Deploy to staging / Validate Railway secrets` step at 12:07:21Z
↓ BECAUSE: Railway returned `Not Authorized` to the `{me{id}}` GraphQL probe (`.github/workflows/staging-pipeline.yml:49-58`)
↓ BECAUSE: `secrets.RAILWAY_TOKEN` is still expired even after the merges of investigation PRs #780/#782/#784/#787/#788 at ~10:00Z–~12:00Z today
↓ ROOT CAUSE: prior rotations (or the latest one not yet performed) created Railway tokens with a finite TTL instead of selecting **No expiration**, *or* the token type does not match what the `{me{id}}` probe expects. **No human has yet performed the rotation that resolves the current expiry window.**

### Evidence Chain

WHY: run `25164454478` failed
↓ BECAUSE: `Validate Railway secrets` step exited 1
  Evidence: `staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' …; then echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"; exit 1; fi`

↓ BECAUSE: Railway responded `Not Authorized`
  Evidence: CI log `2026-04-30T12:07:21.4404355Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: the GraphQL probe was rejected
  Evidence: `staging-pipeline.yml:49-52` — `curl -sf -X POST "https://backboard.railway.app/graphql/v2" -H "Authorization: Bearer $RAILWAY_TOKEN" … -d '{"query":"{me{id}}"}'`

↓ ROOT CAUSE: `secrets.RAILWAY_TOKEN` is expired/invalid
  Evidence: identical failure on the sibling run `25164359158` at 12:04:56Z on the same SHA; identical lineage across #785/#786/#779/#777/#774/#771/#769/#762/#766/#751/#755/#762/#742/#739/#733.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/9d7f0fcf7ce6ae42e454432d6d9a4bfb/investigation.md` | NEW | CREATE | This investigation artifact |
| (no source files) | — | — | Per `CLAUDE.md`, do not edit `.github/workflows/staging-pipeline.yml`; it is failing closed correctly. Do not create `.github/RAILWAY_TOKEN_ROTATION_*.md` (Category 1 error). |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight that surfaces the failure
- `.github/workflows/staging-pipeline.yml:60-90` — `Deploy staging image to Railway` step (gated by the pre-flight)
- `.github/workflows/railway-token-health.yml` — manual health probe to verify a fresh secret
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook (referenced by `CLAUDE.md`)

### Git History

- `2fbf1e6 docs: investigation for issue #786 (16th RAILWAY_TOKEN expiration) (#787)` — the merge commit on which run `25164454478` was triggered. PRs #780/#782/#784/#787/#788 are the recent investigation-only follow-ups. The pattern is well-established: each merge to `main` re-fires staging-pipeline → validate-secrets → fail → cron files a new issue.

---

## Lineage (17 occurrences across 16 unique issues)

| # | Issue | Investigation PR |
|---|-------|------------------|
| 1-13 | #733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #773 / #774 → #777 → #779 | (see prior PRs) |
| 14 | #781 | #782 |
| 15 | #783 | #784 |
| 16 | #785 | #788 |
| 16 (prod twin) | #786 | #787 |
| **17** | **#790** | **(this PR)** |

---

## Implementation Plan

> **If anything below differs from `docs/RAILWAY_TOKEN_ROTATION_742.md`, the runbook wins.** This Implementation Plan is a convenience summary, not the source of truth.

### Step 1: (Human-only) Mint a new Railway token with no expiration

**Action**: Visit https://railway.com/account/tokens → create a token (account- or workspace-scoped to match the prior working token; the existing `{me{id}}` probe at `staging-pipeline.yml:49-52` requires Bearer-compatible auth) with **Expiration: No expiration**. Suggested name: `github-actions-permanent`. Defer to `docs/RAILWAY_TOKEN_ROTATION_742.md` for any conflict.

**Why**: Prior rotations have used finite-TTL tokens, producing a recurring failure mode. A no-expiration token of the **same type that previously authenticated `{me{id}}` over Bearer** breaks the cycle without requiring a probe change while the secret is expired (see `web-research.md` Findings 3 & 7 and Edge Case "Token-type mismatch").

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
gh run rerun 25164454478 --repo alexsiri7/reli --failed
gh run rerun 25164359158 --repo alexsiri7/reli --failed
```

**Expect**: green deploys.

---

### Step 5: Close the issue and clear the label

**Action**:
```bash
gh issue close 790 --repo alexsiri7/reli --reason completed
gh issue edit 790 --repo alexsiri7/reli --remove-label archon:in-progress
```

---

## Patterns to Follow

This investigation mirrors the immediately prior occurrences:

- PR #780 (issue #779, 13th) — investigation-only artifact + lineage update
- PR #782 (issue #781, 14th) — same shape
- PR #784 (issue #783, 15th) — same shape
- PR #788 (issue #785, 16th CI-pipeline twin) — same shape
- PR #787 (issue #786, 16th prod twin) — same shape

Mirror the file structure: artifact + comment, no workflow edits, no `.github/RAILWAY_TOKEN_ROTATION_*.md`.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires another duplicate issue while #790 is open | The cron checks the `archon:in-progress` label; do not remove the label until rotation lands. |
| Human masks the failure by editing the validate-secrets step | **Do not.** That step is failing closed correctly — masking it would let the deploy step silently fail later, in the middle of a real production push. |
| Newly-minted token expires again in 30 days | Insist on **No expiration** at token creation. Anything else perpetuates the loop. |
| Token-type mismatch (account vs. workspace token) for `{me{id}}` probe | Tracked as a P2 follow-up (filed below). Do not change the probe while the secret is expired — the failure signal is currently load-bearing. |

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
gh run rerun 25164454478 --repo alexsiri7/reli --failed
gh run rerun 25164359158 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 3
```

Expect three consecutive `success` conclusions on `staging-pipeline.yml`.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact
- GitHub comment on #790
- Lineage update (16 → 17)

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — failing closed correctly, do not mask
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical, no change needed
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` — Category 1 error per `CLAUDE.md`
- Performing the rotation — agent-out-of-scope per `CLAUDE.md`

---

## Suggested Follow-up Issues

To be filed by a human after rotation lands (carried forward from #786/#788):

1. **Cron loop-stopper for `archon:in-progress` re-fire** (P0) — 17 occurrences across 16 issues on the same expired secret. Gate cron re-firing on a successful `railway-token-health` run, not just the absence of an open sibling.
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — service-account or scheduled-rotation automation.
3. **Reconcile `{me{id}}` validation-query token-type mismatch** (P2) — switch to `{__typename}` if migrating to workspace tokens. **Do not do this while the secret is expired** — masks the failure signal.
4. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against `.app` retirement.
5. **Rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI now treats `RAILWAY_TOKEN` as project-only; renaming avoids ambiguity.

---

## Runbook

See `docs/RAILWAY_TOKEN_ROTATION_742.md` for the canonical rotation steps.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T12:30:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/9d7f0fcf7ce6ae42e454432d6d9a4bfb/investigation.md`
