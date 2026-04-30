# Investigation: Prod deploy failed on main (19th `RAILWAY_TOKEN` expiration)

**Issue**: #798 (https://github.com/alexsiri7/reli/issues/798)
**Type**: BUG
**Investigated**: 2026-04-30T17:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The `Validate Railway secrets` pre-flight at `.github/workflows/staging-pipeline.yml:32-58` is still aborting every prod deploy on `main`. Run `25169904366` (event `workflow_run`, SHA `8dbd379`, Deploy-to-staging job `73786097385`) failed with `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`. No deploy can land until a human rotates the secret. |
| Complexity | LOW | No code change is permitted (per `CLAUDE.md` § "Railway Token Rotation"); the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md`. The artifact-only output mirrors PRs #780 / #782 / #784 / #787 / #788 / #791 / #792 / #795 / #796. |
| Confidence | HIGH | The CI summary emits the canonical error string verbatim: `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Sibling CI-pipeline issue #797 was filed at 14:30:29Z against the same SHA `8dbd379`, 5 seconds before #798 (14:30:34Z), proving both pipelines saw the identical secret-rejection. The 18th-occurrence investigation PRs (#795 for #793, #796 for #794) merged into `main` shortly before this run, and the post-merge `workflow_run` triggered on `8dbd379` failed within minutes — the rotation was not performed in that window. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` calls Railway's `{me{id}}` GraphQL probe over `Authorization: Bearer`, receives `Not Authorized`, and aborts the deploy.

This is the **19th identical recurrence**. Per `CLAUDE.md`, **agents cannot rotate the Railway API token**. This issue requires a human with access to https://railway.com/account/tokens.

---

## Analysis

### First-Principles Analysis

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| `Validate Railway secrets` pre-flight | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Failing closed correctly — surfaces the expired-token state before the actual deploy step would have failed silently mid-push. Do not edit. |
| Token rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Yes | Canonical, referenced by `CLAUDE.md`. No change needed. |
| `RAILWAY_TOKEN` secret itself | GitHub Actions secret store | **No** | Recurring expiry is the load-bearing root cause. The fix is exclusively human (mint a no-expiration account-scoped token; replace the secret). |
| `archon:in-progress` cron gate | `pipeline-health-cron.sh` (external) | Partial | Prevents *concurrent* duplicate filings, but does not prevent serial re-fires after each merge to `main`. See P0 follow-up. |

The primitive that is unsound is the secret itself, not any code in this repo. No code change resolves the failure; only secret rotation does.

### Root Cause

WHY: run `25169904366` failed at the `Deploy to staging / Validate Railway secrets` step
↓ BECAUSE: Railway returned `Not Authorized` to the `{me{id}}` GraphQL probe (`.github/workflows/staging-pipeline.yml:49-58`)
↓ BECAUSE: `secrets.RAILWAY_TOKEN` is still expired even after the merges of investigation PRs #795 (for #793) and #796 (for #794) earlier today
↓ ROOT CAUSE: prior rotations have used finite-TTL or workspace-scoped tokens, producing the recurring failure mode. **No human has yet performed the rotation that resolves the current expiry window.** See `web-research.md` Findings 1–4 for the token-type rationale (account-scoped, no expiration, Bearer-compatible).

### Evidence Chain

WHY: run `25169904366` failed
↓ BECAUSE: `Validate Railway secrets` step exited 1
  Evidence: `.github/workflows/staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' …; then echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"; exit 1; fi`

↓ BECAUSE: Railway responded `Not Authorized`
  Evidence: CI summary annotation `X RAILWAY_TOKEN is invalid or expired: Not Authorized` on Deploy-to-staging job `73786097385` of run `25169904366`.

↓ BECAUSE: the GraphQL probe was rejected
  Evidence: `.github/workflows/staging-pipeline.yml:49-52` — `curl -sf -X POST "https://backboard.railway.app/graphql/v2" -H "Authorization: Bearer $RAILWAY_TOKEN" … -d '{"query":"{me{id}}"}'`

↓ ROOT CAUSE: `secrets.RAILWAY_TOKEN` is expired/invalid
  Evidence: identical failure on the sibling CI-pipeline issue #797 (filed 14:30:29Z against the same SHA `8dbd379`, 5 seconds before #798 at 14:30:34Z); identical lineage across #793/#794/#789/#790/#785/#786/#783/#781/#779/#777/#774/#773/#771/#769/#766/#762/#755/#751/#742/#739/#733.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/e05e40431af32d76a870f3a95aa8b1a6/investigation.md` | NEW | CREATE | This investigation artifact |
| (no source files) | — | — | Per `CLAUDE.md`, do not edit `.github/workflows/staging-pipeline.yml`; it is failing closed correctly. Do not create `.github/RAILWAY_TOKEN_ROTATION_*.md` (Category 1 error). |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight that surfaces the failure
- `.github/workflows/staging-pipeline.yml:60-90` — `Deploy staging image to Railway` step (gated by the pre-flight)
- `.github/workflows/railway-token-health.yml` — manual health probe to verify a fresh secret
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook (referenced by `CLAUDE.md`)

### Git History

- `8dbd379 docs: investigation for issue #793 (18th RAILWAY_TOKEN expiration) (#795)` — the merge commit on which run `25169904366` was triggered (via `workflow_run`).
- `66f717a docs: investigation for issue #794 (18th RAILWAY_TOKEN expiration) (#796)` — sibling 18th-occurrence investigation PR.
- The pattern is well-established: each merge to `main` re-fires `staging-pipeline.yml` → `Validate Railway secrets` → fail → cron files a new issue (and its CI twin).

---

## Lineage (19 occurrences across 19+ unique issues)

| # | Issue (CI / Prod) | Investigation PR |
|---|-------------------|------------------|
| 1–13 | #733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #773 / #774 → #777 → #779 | (see prior PRs) |
| 14 | #781 | #782 |
| 15 | #783 | #784 |
| 16 (CI) | #785 | #788 |
| 16 (prod) | #786 | #787 |
| 17 (CI) | #789 | #792 |
| 17 (prod) | #790 | #791 |
| 18 (CI) | #793 | #795 |
| 18 (prod) | #794 | #796 |
| **19 (CI)** | **#797** | (separate task) |
| **19 (prod)** | **#798** | **(this PR)** |

---

## Implementation Plan

> **If anything below differs from `docs/RAILWAY_TOKEN_ROTATION_742.md`, the runbook wins.** This Implementation Plan is a convenience summary, not the source of truth.

### Step 1: (Human-only) Mint a new Railway token with no expiration

**Action**: Visit https://railway.com/account/tokens → create a token (account-scoped — leave the **Workspace** field blank / "NO TEAM" per `web-research.md` Finding 3) with **Expiration: No expiration**. Suggested name: `github-actions-permanent`. Defer to `docs/RAILWAY_TOKEN_ROTATION_742.md` for any conflict.

**Why**: Prior rotations have used finite-TTL or workspace-scoped tokens, producing the recurring failure mode. An account-scoped, no-expiration token authenticated via `Authorization: Bearer` breaks the cycle without requiring a probe change while the secret is expired (`web-research.md` Findings 1–3 and Edge Case "Token-type mismatch").

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

### Step 4: Re-run the failed deploy

**Action**:
```bash
gh run rerun 25169904366 --repo alexsiri7/reli --failed
```

**Expect**: green deploy.

---

### Step 5: Close both halves of the 19th occurrence and clear labels

**Action**:
```bash
gh issue close 797 --repo alexsiri7/reli --reason completed
gh issue edit 797 --repo alexsiri7/reli --remove-label archon:in-progress
gh issue close 798 --repo alexsiri7/reli --reason completed
gh issue edit 798 --repo alexsiri7/reli --remove-label archon:in-progress
```

---

## Patterns to Follow

This investigation mirrors the immediately prior occurrences:

- PR #780 (issue #779, 13th) — investigation-only artifact + lineage update
- PR #782 (issue #781, 14th) — same shape
- PR #784 (issue #783, 15th) — same shape
- PR #787 / #788 (issues #786 / #785, 16th twins) — same shape
- PR #791 / #792 (issues #790 / #789, 17th twins) — same shape
- PR #795 / #796 (issues #793 / #794, 18th twins) — same shape

Mirror the file structure: artifact + comment, no workflow edits, no `.github/RAILWAY_TOKEN_ROTATION_*.md`.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires another duplicate issue while #797 / #798 are open | The cron checks the `archon:in-progress` label; do not remove the label until rotation lands. |
| Human masks the failure by editing the `Validate Railway secrets` step | **Do not.** That step is failing closed correctly — masking it would let the deploy step silently fail later, in the middle of a real production push. |
| Newly-minted token expires again in 30 days | Insist on **No expiration** at token creation. Anything else perpetuates the loop. |
| Token-type mismatch (account vs. workspace token) for `{me{id}}` probe | Tracked as a P2 follow-up (filed below). Do not change the probe while the secret is expired — the failure signal is currently load-bearing. |
| Investigation PR for #797 (CI twin) lands separately and re-fires the merge cycle | Expected. Both #797 and #798 will be closed by the human rotation; no extra investigation work is needed beyond the lineage entry. |

---

## Validation

### Automated Checks

```bash
git diff --stat HEAD~1 HEAD
gh pr view --json checks
```

There is no source code change, so type-check / lint / tests are N/A.

### Manual Verification (post-rotation)

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25169904366 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 3
```

Expect three consecutive `success` conclusions on `staging-pipeline.yml`.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact
- GitHub comment on #798
- Lineage update (18 → 19)

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — failing closed correctly, do not mask
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical, no change needed
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` — Category 1 error per `CLAUDE.md`
- Performing the rotation — agent-out-of-scope per `CLAUDE.md`
- Investigating #797 (CI twin) — handled as a separate task

---

## Suggested Follow-up Issues

To be filed by a human after rotation lands (carried forward from prior occurrences):

1. **Cron loop-stopper for `archon:in-progress` re-fire** (P0) — 19 occurrences on the same expired secret across 19+ issues. Gate cron re-firing on a successful `railway-token-health` run, not just the absence of an open sibling.
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — service-account or scheduled-rotation automation.
3. **Reconcile `{me{id}}` validation-query token-type mismatch** (P2) — switch to `{__typename}` if migrating to workspace tokens. **Do not do this while the secret is expired** — masks the failure signal.
4. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against `.app` retirement. The current code, the investigation evidence above, and the `curl` examples in `web-research.md` all use `backboard.railway.app` (which is what is deployed today); keep `.app` in the code until `.com` is verified working with `Authorization: Bearer` for the `{me{id}}` probe.
5. **Rename `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI now treats `RAILWAY_TOKEN` as project-only; renaming avoids ambiguity (`web-research.md` Finding 4).

---

## Runbook

See `docs/RAILWAY_TOKEN_ROTATION_742.md` for the canonical rotation steps.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T17:10:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/e05e40431af32d76a870f3a95aa8b1a6/investigation.md`
