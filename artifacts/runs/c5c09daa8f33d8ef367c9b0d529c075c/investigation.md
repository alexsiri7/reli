# Investigation: Prod deploy failed on main (20th `RAILWAY_TOKEN` expiration)

**Issue**: #801 (https://github.com/alexsiri7/reli/issues/801)
**Type**: BUG
**Investigated**: 2026-04-30T18:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | The `Validate Railway secrets` pre-flight at `.github/workflows/staging-pipeline.yml:32-58` aborted run `25180002128` with `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` on SHA `7b8fcc9` (the merge commit of PR #799 — the 19th-occurrence investigation). No prod deploy can land on `main` until a human rotates the secret. |
| Complexity | LOW | No code change is permitted (per `CLAUDE.md` § "Railway Token Rotation"); the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md`. The artifact-only output mirrors PRs #780 / #782 / #784 / #787 / #788 / #791 / #792 / #795 / #796 / #799. |
| Confidence | HIGH | The CI summary emits the canonical error string verbatim: `RAILWAY_TOKEN is invalid or expired: Not Authorized`. Sibling CI-pipeline issue #800 ("Main CI red: Deploy to staging") was filed at 18:00:26Z against the same SHA `7b8fcc9`, 4 seconds before #801 (18:00:30Z), proving both pipeline filings saw the identical secret-rejection. PR #799 (19th-occurrence investigation) merged into `main` ~30 minutes earlier; the post-merge `workflow_run` triggered on `7b8fcc9` failed at 17:34:56Z — the rotation was not performed in that window. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` calls Railway's `{me{id}}` GraphQL probe over `Authorization: Bearer`, receives `Not Authorized`, and aborts the deploy.

This is the **20th identical recurrence**. Per `CLAUDE.md`, **agents cannot rotate the Railway API token**. This issue requires a human with access to https://railway.com/account/tokens.

---

## Analysis

### First-Principles Analysis

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| `Validate Railway secrets` pre-flight | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Failing closed correctly — surfaces the expired-token state before the actual deploy step would have failed silently mid-push. Do not edit. |
| Token rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Partial | Canonical, referenced by `CLAUDE.md`. Per `web-research.md` Findings 1–4 in this run, the runbook's "No expiration" guidance and TTL claims are not corroborated by Railway's public docs and may steer operators toward the wrong token type — possibly explaining the 20-times-and-counting recurrence cadence. Recommend a follow-up issue to update the runbook (out of scope for this docs-only artifact). |
| `RAILWAY_TOKEN` secret itself | GitHub Actions secret store | **No** | Recurring expiry/rejection is the load-bearing root cause. The fix is exclusively human (mint a workspace-scoped token per Railway's "Team CI/CD" guidance; replace the secret). |
| `archon:in-progress` cron gate | `pipeline-health-cron.sh` (external) | Partial | Prevents *concurrent* duplicate filings, but does not prevent serial re-fires after each merge to `main`. Each investigation PR that merges re-triggers the staging-pipeline `workflow_run`, which fires another issue. See P0 follow-up. |

The primitive that is unsound is the secret itself, not any code in this repo. No code change resolves the failure; only secret rotation does.

### Root Cause

WHY: run `25180002128` failed at the `Deploy to staging / Validate Railway secrets` step
↓ BECAUSE: Railway returned `Not Authorized` to the `{me{id}}` GraphQL probe (`.github/workflows/staging-pipeline.yml:49-58`)
↓ BECAUSE: `secrets.RAILWAY_TOKEN` is still expired/invalid even after the merge of investigation PR #799 (for #798) ~30 minutes earlier
↓ ROOT CAUSE: prior rotations have used finite-TTL or wrong-type tokens, producing the recurring failure mode. **No human has yet performed the rotation that resolves the current expiry window.** See companion `web-research.md` Findings 1–6 for the token-type rationale (workspace-scoped, Bearer-compatible, "best for Team CI/CD" per Railway docs).

### Evidence Chain

WHY: run `25180002128` failed
↓ BECAUSE: `Validate Railway secrets` step exited 1
  Evidence: `.github/workflows/staging-pipeline.yml:53-58` — `if ! echo "$RESP" | jq -e '.data.me.id' …; then echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"; exit 1; fi`

↓ BECAUSE: Railway responded `Not Authorized`
  Evidence: CI summary annotation `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` on Deploy-to-staging job of run `25180002128` at 2026-04-30T17:34:56Z.

↓ BECAUSE: the GraphQL probe was rejected
  Evidence: `.github/workflows/staging-pipeline.yml:49-52` — `curl -sf -X POST "https://backboard.railway.app/graphql/v2" -H "Authorization: Bearer $RAILWAY_TOKEN" … -d '{"query":"{me{id}}"}'`

↓ ROOT CAUSE: `secrets.RAILWAY_TOKEN` is expired/invalid
  Evidence: identical failure on the sibling CI-pipeline issue #800 (filed 18:00:26Z against the same SHA `7b8fcc9`, 4 seconds before #801 at 18:00:30Z); identical lineage across #798/#797/#794/#793/#790/#789/#786/#785/#783/#781/#779/#777/#774/#773/#771/#769/#766/#762/#755/#751/#742/#739/#733.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/investigation.md` | NEW | CREATE | This investigation artifact |
| `artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/web-research.md` | (already present) | KEEP | Token-type research already produced earlier in this run; referenced from this artifact |
| (no source files) | — | — | Per `CLAUDE.md`, do not edit `.github/workflows/staging-pipeline.yml`; it is failing closed correctly. Do not create `.github/RAILWAY_TOKEN_ROTATION_*.md` (Category 1 error). |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight that surfaces the failure
- `.github/workflows/staging-pipeline.yml:60-90` — `Deploy staging image to Railway` step (gated by the pre-flight)
- `.github/workflows/railway-token-health.yml` — manual health probe to verify a fresh secret
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook (referenced by `CLAUDE.md`)
- `pipeline-health-cron.sh` (external mayor cron) — auto-files this issue on every red prod deploy

### Git History

- `7b8fcc9 docs: investigation for issue #798 (19th RAILWAY_TOKEN expiration) (#799)` — the merge commit on which run `25180002128` was triggered (via `workflow_run`).
- `8dbd379 docs: investigation for issue #793 (18th RAILWAY_TOKEN expiration) (#795)` — prior 18th-occurrence investigation.
- `66f717a docs: investigation for issue #794 (18th RAILWAY_TOKEN expiration) (#796)` — sibling 18th-occurrence investigation PR.
- The pattern is well-established: each merge to `main` re-fires `staging-pipeline.yml` → `Validate Railway secrets` → fail → cron files a new issue (and its CI twin).

---

## Lineage (20 occurrences across 20+ unique issues)

| # | Issue (CI / Prod) | Investigation PR |
|---|-------------------|------------------|
| 1–13 | #733 → #739 → #742 → #755 → #762 → #751 → #766 → #762 (re-fire) → #769 → #771 → #773 / #774 → #777 → #779 | (see prior PRs) |
| 14 | #781 | #782 |
| 15 | #783 | #784 |
| 16 (CI) | #785 | #788 |
| 16 (prod) | #786 | #787 |
| 17 (CI) | #789 | #792 |
| 17 (prod) | #790 | #791 |
| 18 (prod) | #793 | #795 |
| 18 (CI) | #794 | #796 |
| 19 (CI / prod) | #797 / #798 | #799 (covers #798; #797 reused or auto-closed) |
| **20 (CI)** | **#800** | (sibling — separate investigation if cron re-fires) |
| **20 (prod)** | **#801 (this issue)** | **(this PR)** |

---

## Implementation Plan

This is a docs-only artifact. The implementation steps below describe what the **investigation PR** does, not a code fix. The actual fix (token rotation) must be performed by a human per `CLAUDE.md`.

### Step 1: Land this investigation artifact

**File**: `artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/investigation.md`
**Action**: CREATE

Mirror the prior investigation pattern (PR #799 for #798) — docs-only, no source-file edits, references the canonical rotation runbook.

**Why**: per `CLAUDE.md` § "Railway Token Rotation" (Category 1 error) — agents cannot rotate the secret, must not create rotation-claim files, must escalate via issue/mail and direct the human to the runbook.

---

### Step 2: Open PR titled `docs: investigation for issue #801 (20th RAILWAY_TOKEN expiration)`

**Body** must include:

- `Fixes #801`
- 1-paragraph summary: 20th consecutive recurrence; PR #799 merged ~30 minutes earlier and the post-merge `workflow_run` on SHA `7b8fcc9` failed; sibling CI-pipeline issue #800 was filed 4 seconds before #801; per `CLAUDE.md` agents cannot rotate the secret, escalating to human.
- Pointer to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**Why**: matches the established lineage of PRs #780 / #782 / #784 / #787 / #788 / #791 / #792 / #795 / #796 / #799.

---

### Step 3 (optional, deferred): File a follow-up issue against the runbook

Consider filing a *separate* GH issue (NOT addressed in this PR) to update `docs/RAILWAY_TOKEN_ROTATION_742.md` per `web-research.md` recommendations:

- Specify *workspace token* (Railway's documented "Team CI/CD" recommendation) instead of unspecified token type.
- Drop the unverified "No expiration" instruction unless an operator can confirm that UI option exists.
- Add a verification step: run the same `curl … {me{id}}` validation locally before pasting into GitHub secrets.

This is a docs follow-up, not a fix for #801. Out of scope here per Polecat Scope Discipline (`CLAUDE.md`).

---

## Patterns to Follow

**From codebase — mirror the established investigation pattern (PR #799 for #798):**

```
artifacts/runs/<run-hash>/investigation.md   # this file
```

Single-file, docs-only, no source edits. Same heading structure, same Assessment/Problem/Analysis/Lineage/Implementation/Validation/Scope sections. The PR description references the GitHub issue (`Fixes #801`) per `CLAUDE.md` § "GitHub Issue Linking".

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Reviewer asks why no code change | The `Validate Railway secrets` step is failing closed correctly. Editing it would mask the error. The bug is the secret value, not the workflow. Per `CLAUDE.md`, agents cannot rotate the secret. |
| Cron re-fires another `Prod deploy failed` issue when this PR merges | Expected. Each merge to `main` triggers `staging-pipeline.yml` via `workflow_run`. Until the human rotates the token, this loop continues. The investigation-only PRs at least produce a paper trail. |
| Tempting to "fix" this by switching validation to `{ projectToken { projectId } }` | Out of scope here. Would change the token-type contract for the entire deploy step. File as a separate issue (see `web-research.md` § Recommendations). |
| Tempting to create `.github/RAILWAY_TOKEN_ROTATION_801.md` claiming rotation done | **DO NOT.** This is an explicit Category 1 error per `CLAUDE.md`. Agents have no access to https://railway.com/account/tokens. |
| Risk of merging this PR while a human is mid-rotation | Low. Merging this docs-only file does not interact with the secret. A successful rotation will simply make the next `workflow_run` go green. |

---

## Validation

### Automated Checks

```bash
# This PR contains no code; CI checks are docs-only.
# The deploy-pipeline failure that filed this issue will continue until a human rotates the token.
# After rotation, manually trigger to verify:
gh workflow run railway-token-health.yml
```

### Manual Verification

1. Confirm `gh issue view 801` shows the canonical error: `RAILWAY_TOKEN is invalid or expired: Not Authorized`.
2. Confirm `docs/RAILWAY_TOKEN_ROTATION_742.md` exists and is the runbook the human will follow.
3. After this PR merges and a human rotates the token, the next `staging-pipeline.yml` run on `main` should pass `Validate Railway secrets` and proceed to the actual deploy.

---

## Scope Boundaries

**IN SCOPE:**
- Create `artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/investigation.md` (this file).
- Reference companion `artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/web-research.md` (already produced).
- Post a GH issue comment summarizing the investigation.
- Open the investigation PR with `Fixes #801`.

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — failing closed correctly; do not edit.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook; updates belong in a separate follow-up issue.
- `secrets.RAILWAY_TOKEN` — agents have no access; Category 1 error to claim rotation.
- Switching validation from `{me{id}}` to `{ projectToken { … } }` — separate design decision, separate issue.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation done — explicit `CLAUDE.md` prohibition.
- Cron-loop mitigation in `pipeline-health-cron.sh` — external repo, separate issue.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T18:10:00Z
- **Run hash**: `c5c09daa8f33d8ef367c9b0d529c075c`
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/investigation.md`
- **Companion**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/c5c09daa8f33d8ef367c9b0d529c075c/web-research.md`
