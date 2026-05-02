# Investigation: Main CI red — Deploy to staging (#917, 65th RAILWAY_TOKEN expiration)

**Issue**: #917 (https://github.com/alexsiri7/reli/issues/917)
**Type**: BUG (operational — external credential rejection)
**Investigated**: 2026-05-02T21:10:00Z
**Run**: https://github.com/alexsiri7/reli/actions/runs/25261266464
**SHA under test**: `7df1bfd6fa3b2e7cefa61f33652149c214a63a91` (merge of PR #916, the investigation of #915)

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | `HIGH` | Prod deploy is gated by the staging deploy job, which fails at the Railway-secret validator on every main push; no in-repo workaround for the bleeding without a human at railway.com. |
| Complexity | `LOW` (rotation) / `MEDIUM` (durable fix) | Like-for-like rotation is zero code (human-only). The durable fix (switch `RAILWAY_TOKEN` to a Project token, change auth header on six call sites, replace `{me{id}}` validator) is contained to one workflow file plus the runbook. |
| Confidence | `HIGH` | Failure message, endpoint, and step are byte-for-byte identical to the prior 64 incidents. The token-class hypothesis from PR #916 / `web-research.md` still applies; nothing new in this run's logs contradicts it. |

---

## Problem Statement

The "Validate Railway secrets" step in the "Deploy to staging" job failed on run [25261266464](https://github.com/alexsiri7/reli/actions/runs/25261266464) because Railway's auth backend rejected the token currently held in `secrets.RAILWAY_TOKEN`. This is the **65th** recurrence of the same failure mode and the **25th today**.

Chain: `#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #903/#904 → #907 → #909 → #911/#912 → #915 → #917`.

The SHA under test (`7df1bfd`) is the merge of PR #916 — the investigation of #915. So a docs-only investigation merged, the next scheduled "Staging → Production Pipeline" run picked up that SHA, and predictably failed in the exact same place because the underlying token has not been rotated.

---

## Analysis

### Root Cause / Change Rationale

Two layers — unchanged from the #915 investigation:

**Proximate cause** (what makes this run red): The token in `secrets.RAILWAY_TOKEN` is still rejected by Railway with `Not Authorized`. Like-for-like rotation per `docs/RAILWAY_TOKEN_ROTATION_742.md` will turn this run green.

**Underlying cause** (why we're here for the 65th time): The workflow puts an **Account/Personal token** into the `RAILWAY_TOKEN` slot and calls Railway with `Authorization: Bearer`. Per Railway's own docs, `RAILWAY_TOKEN` is the slot for a **Project token**, which uses a different header (`Project-Access-Token:`). See `artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/web-research.md` (committed in PR #916) §§1–3 for primary sources; nothing has changed since that investigation.

### Evidence Chain

WHY: Why did "Deploy to staging" fail on run 25261266464?
↓ BECAUSE: The "Validate Railway secrets" step exited 1.
  Evidence: `##[error]Process completed with exit code 1.` at 2026-05-02T20:34:52.945Z.

↓ BECAUSE: The validator's `me{id}` probe to Railway returned `Not Authorized`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at 2026-05-02T20:34:52.943Z.

↓ BECAUSE: The token currently in `secrets.RAILWAY_TOKEN` is still rejected by Railway's auth backend (expired, revoked, or — most likely — wrong token class). It has not been rotated since the previous failure on #915 (run 25260091455 at 2026-05-02T19:34Z, ~1 hour earlier).

↓ **ROOT CAUSE (durable)**: `RAILWAY_TOKEN` only accepts a Project token. The workflow currently sends `Authorization: Bearer $RAILWAY_TOKEN` (Account-token shape) and validates with `{me{id}}` (Account-token-only query). Both must change for the rotation treadmill to stop.
  Evidence: `.github/workflows/staging-pipeline.yml:50` (`-H "Authorization: Bearer $RAILWAY_TOKEN"`) and `:52` (`-d '{"query":"{me{id}}"}'`). Validator block unchanged across all 65 incidents.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `.github/workflows/staging-pipeline.yml` | 32-58 | UPDATE (durable fix, deferred) | Validator: swap `Authorization: Bearer` → `Project-Access-Token`, replace `{me{id}}` query with `{ projectToken { projectId environmentId } }`. |
| `.github/workflows/staging-pipeline.yml` | 60-end | UPDATE (durable fix, deferred) | Both deploy steps (staging + prod): change auth header on every Railway API call. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | 24-26 | UPDATE (durable fix, deferred) | Point operators at *Project Settings → Tokens*, not `https://railway.com/account/tokens`. |
| `secrets.RAILWAY_TOKEN` | n/a | **HUMAN ONLY** | Rotate the existing Account token like-for-like, OR mint a new Project token and reinstall as `RAILWAY_TOKEN`. |
| `artifacts/runs/bac9855cea89d9bb2f237189ad8f26a7/investigation.md` | NEW | CREATE | This file. |

### Integration Points

- `.github/workflows/staging-pipeline.yml` — the only consumer of `RAILWAY_TOKEN` in the repo.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — operator runbook; rotation is gated on this file.
- `pipeline-health-cron.sh` — auto-files this issue on every red main run, so the bleeding shows up as one issue per failed pipeline run until the token is fixed.

### Git History

- The validator block at `.github/workflows/staging-pipeline.yml:32-58` is unchanged across the entire failure chain (`#878 … #917`).
- Prior investigations: PR #916 (for #915), commit 9117b40 (#911), 1397e3d (#912), fdf6393 (#909), e4dc1c5 (#907), 3521481 (#903).
- **Implication**: this is a long-standing class-mismatch bug, not a regression.

---

## Implementation Plan

### Step 1 (this bead) — Investigation artifact + GitHub comment

**File**: `artifacts/runs/bac9855cea89d9bb2f237189ad8f26a7/investigation.md`
**Action**: CREATE (this file)
**Why**: Documents the failure on run 25261266464 and routes the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`, without claiming the agent performed the rotation.

**Action on GitHub**: post a comment on issue #917 routing the human to the runbook. Per `CLAUDE.md` § Railway Token Rotation, **do not** create `.github/RAILWAY_TOKEN_ROTATION_917.md` — that would be a Category 1 error.

---

### Step 2 (HUMAN-ONLY) — Rotate the token

The agent cannot perform this step. Two options — same as #915, repeated here for convenience:

**Option A — Like-for-like (fastest, but reproduces the treadmill):**
1. Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`.
2. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` with the new token.
3. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` to verify it authenticates.
4. `gh run rerun 25261266464 --repo alexsiri7/reli --failed` to retry the failed pipeline.

**Option B — Durable (recommended, breaks the cycle):**
1. In the Railway dashboard, navigate to **Project Settings → Tokens** (NOT Account → Tokens).
2. Mint a Project token scoped to the staging environment; install as `RAILWAY_TOKEN`.
3. Open the follow-up PR (Step 3 below) so the workflow speaks the Project-token protocol; the new token will fail the *current* validator (`{me{id}}` does not work for Project tokens), so Step 2B and Step 3 must land together.

After 25 expirations in a single day, Option A is no longer a real option — it just buys ~1 hour before the next issue files itself. Option B is the only path that closes the cycle.

---

### Step 3 (DEFERRED — separate PR) — Make the workflow speak the Project-token protocol

**Out of scope for this bead** (Polecat Scope Discipline). Captured here for the eventual implementer; identical to PR #916 § Step 3.

**File**: `.github/workflows/staging-pipeline.yml` lines 32-58 (validator) plus equivalent header changes in every Railway-API call site downstream.

**Current code (validator):**
```yaml
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  ...
fi
```

**Required change (validator):**
```yaml
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}')
if ! echo "$RESP" | jq -e '.data.projectToken.projectId' > /dev/null 2>&1; then
  ...
fi
```

**Why**: A Project token has no associated `me` user, so the current query returns null even when the token is valid. The deploy mutations themselves accept Project tokens but require the `Project-Access-Token:` header.

**File**: `docs/RAILWAY_TOKEN_ROTATION_742.md` lines 24-26 — replace the `https://railway.com/account/tokens` URL with the Project-Settings → Tokens path, plus a one-line note that `RAILWAY_TOKEN` must be a Project token.

---

## Patterns to Follow

Mirror the prior investigation skeleton (PRs #908, #910, #913, #914, #916). The GitHub comment uses the same `## 🔍 Investigation` heading, Assessment table, Problem Statement, Root Cause Analysis, Implementation Plan table, Validation block, Next Step.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Like-for-like rotation succeeds but expires within ~1 hour again | Has happened 25 times today. Recommend Option B (Project token) instead. |
| Project token installed without Step 3 landing | Current validator's `{me{id}}` query rejects a healthy Project token; Step 2B and Step 3 must land in the same change window. |
| Project token is environment-scoped (staging vs prod) | A single Project token covers one environment. Repo has separate `RAILWAY_STAGING_*` and `RAILWAY_PRODUCTION_*` secrets, so two Project tokens are likely needed. |
| Agent accidentally creates `.github/RAILWAY_TOKEN_ROTATION_917.md` claiming rotation done | Forbidden by `CLAUDE.md` § Railway Token Rotation (Category 1 error). This bead does NOT do that. |
| `pipeline-health-cron.sh` files yet another duplicate before rotation | #917 is tagged `archon:in-progress`, blocking re-pickup of *this* issue. The cron will keep filing new issues per failed run until the token is fixed; rotator closes them in a batch. |

---

## Validation

### Automated checks for this bead (docs-only)

```bash
# This bead writes only an investigation artifact; no code or tests change.
gh issue view 917 --repo alexsiri7/reli --comments
git diff --name-only origin/main..HEAD
# Expect: only files under artifacts/runs/bac9855cea89d9bb2f237189ad8f26a7/
```

### Manual verification (after the human rotates the token)

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run watch --repo alexsiri7/reli
gh run rerun 25261266464 --repo alexsiri7/reli --failed
```

Expect: validator step prints no `::error::`, the staging deploy job goes green, the gated production job runs.

---

## Scope Boundaries

**IN SCOPE for this bead:**
- Create `artifacts/runs/bac9855cea89d9bb2f237189ad8f26a7/investigation.md` (this file).
- Post a GitHub comment on #917 routing the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` and surfacing the durable-fix recommendation.

**OUT OF SCOPE (do NOT touch in this bead):**
- The `RAILWAY_TOKEN` secret itself — agents cannot rotate it (`CLAUDE.md` § Railway Token Rotation).
- `.github/workflows/staging-pipeline.yml` — the durable fix is a separate PR per Polecat Scope Discipline.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` URL fix — same; deferred to the durable-fix PR.
- Closing #911, #912, #915, #917 — they should be closed together once the token is rotated and CI is green; that is the rotator's call.
- Re-running the `web-research.md` deep dive — already committed in PR #916 (`artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/web-research.md`); referenced from this artifact rather than duplicated.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T21:10:00Z
- **Artifact**: `artifacts/runs/bac9855cea89d9bb2f237189ad8f26a7/investigation.md`
- **Companion artifact (referenced, not duplicated)**: `artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/web-research.md` (committed in PR #916 — primary-source evidence for token-class hypothesis)
- **Run under investigation**: 25261266464 (Staging → Production Pipeline, SHA `7df1bfd`)
- **Failure mode**: 65th `RAILWAY_TOKEN is invalid or expired: Not Authorized`, 25th today
