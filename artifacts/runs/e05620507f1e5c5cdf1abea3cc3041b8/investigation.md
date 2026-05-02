# Investigation: Main CI red — Deploy to staging (#915, 64th RAILWAY_TOKEN expiration)

**Issue**: #915 (https://github.com/alexsiri7/reli/issues/915)
**Type**: BUG (operational — external credential rejection)
**Investigated**: 2026-05-02T19:55:00Z
**Run**: https://github.com/alexsiri7/reli/actions/runs/25260091455
**SHA under test**: `9117b40e4b41132efb660ecc195651c18dbae40f` (merge of PR #913, the investigation of #911)

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | `HIGH` | Prod deploy is gated by the staging deploy job, which fails at the Railway-secret validator on every main push; no in-repo workaround for the bleeding without a human at railway.com. |
| Complexity | `LOW` (rotation) / `MEDIUM` (durable fix) | Like-for-like rotation is zero code (human-only). The durable fix (switch `RAILWAY_TOKEN` to a Project token, change auth header on six call sites, replace `{me{id}}` validator) is contained to one workflow file plus the runbook. |
| Confidence | `HIGH` | Failure message, endpoint, and step are byte-for-byte identical to the prior 63 incidents. Web research (`web-research.md`) corroborates the token-class hypothesis with primary Railway docs and the Help Station thread quoting the same `invalid or expired` string. |

---

## Problem Statement

The "Validate Railway secrets" step in the "Deploy to staging" job failed on run [25260091455](https://github.com/alexsiri7/reli/actions/runs/25260091455) because Railway's auth backend rejected the token currently held in `secrets.RAILWAY_TOKEN`. This is the **64th** recurrence of the same failure mode and the **24th today**.

Chain: `#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #903/#904 → #907 → #909 → #911/#912 → #915`.

---

## Analysis

### Root Cause / Change Rationale

Two layers:

**Proximate cause** (what makes this run red): The token in `secrets.RAILWAY_TOKEN` is rejected by Railway with `Not Authorized`. Like-for-like rotation per `docs/RAILWAY_TOKEN_ROTATION_742.md` will turn this run green.

**Underlying cause** (why we're here for the 64th time): The workflow puts an **Account/Personal token** into the `RAILWAY_TOKEN` slot and calls Railway with `Authorization: Bearer`. Per Railway's own docs, `RAILWAY_TOKEN` is the slot for a **Project token**, which uses a different header (`Project-Access-Token:`). Account tokens are not the right class for unattended CI use; community reports show them returning `invalid or expired` even when freshly minted, which matches the rotation cadence we are seeing (24 expirations today). See `web-research.md` §§1–3 for primary sources.

### Evidence Chain

WHY: Why did "Deploy to staging" fail on run 25260091455?
↓ BECAUSE: The "Validate Railway secrets" step exited 1.
  Evidence: `##[error]Process completed with exit code 1.` at 2026-05-02T19:34:54Z.

↓ BECAUSE: The validator's `me{id}` probe to Railway returned `Not Authorized`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at 2026-05-02T19:34:54Z.

↓ BECAUSE: The token currently in `secrets.RAILWAY_TOKEN` is rejected by Railway's auth backend (expired, revoked, or — most likely — wrong token class).
  Evidence: `.github/workflows/staging-pipeline.yml:32-58` — validator code is unchanged across all 64 incidents.

↓ **ROOT CAUSE (durable)**: `RAILWAY_TOKEN` only accepts a Project token. The workflow currently sends `Authorization: Bearer $RAILWAY_TOKEN` (Account-token shape) and validates with `{me{id}}` (Account-token-only query). Both must change for the rotation treadmill to stop.
  Evidence: Railway Help Station — "RAILWAY_TOKEN now only accepts **project token**, if u put the normal account token … it literally says 'invalid or expired' even if u just made it 2 seconds ago." (`web-research.md` §2)

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `.github/workflows/staging-pipeline.yml` | 32-58 | UPDATE (durable fix) | Validator: swap `Authorization: Bearer` → `Project-Access-Token`, replace `{me{id}}` query with `{ projectToken { projectId environmentId } }`, change jq path. |
| `.github/workflows/staging-pipeline.yml` | 60-end | UPDATE (durable fix) | Both deploy steps (staging + prod jobs): change auth header on every Railway API call. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | 24-26 | UPDATE (durable fix) | Point operators at *Project Settings → Tokens*, not `https://railway.com/account/tokens`. |
| `secrets.RAILWAY_TOKEN` | n/a | **HUMAN ONLY** | Rotate the existing Account token like-for-like, OR mint a new Project token and reinstall as `RAILWAY_TOKEN`. |

### Integration Points

- `.github/workflows/staging-pipeline.yml` — the only consumer of `RAILWAY_TOKEN` in the repo.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — operator runbook; rotation is gated on this file's URL.
- `pipeline-health-cron.sh` — auto-files this issue on every red main run, so the bleeding shows up as one issue per failed pipeline run until the token is fixed.

### Git History

- The validator block at `.github/workflows/staging-pipeline.yml:32-58` is unchanged across the entire failure chain (`#878 … #915`).
- Prior investigations: PR #913 (for #911), and the docs-only investigation commits 1397e3d (#912), fdf6393 (#909), e4dc1c5 (#907), 3521481 (#903).
- **Implication**: this is a long-standing class-mismatch bug, not a regression.

---

## Implementation Plan

### Step 1 (this bead) — Investigation artifact + GitHub comment

**File**: `artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/investigation.md`
**Action**: CREATE (this file)
**Why**: Documents the failure on run 25260091455, points the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`, and surfaces the durable fix without claiming the agent performed the rotation.

**Companion artifact**: `web-research.md` (already in this run directory) — primary-source evidence for the token-class hypothesis.

**Action on GitHub**: post a comment on issue #915 routing the human to the runbook. Per `CLAUDE.md` § Railway Token Rotation, **do not** create `.github/RAILWAY_TOKEN_ROTATION_915.md` — that would be a Category 1 error.

---

### Step 2 (HUMAN-ONLY) — Rotate the token

The agent cannot perform this step. Two options:

**Option A — Like-for-like (fastest, but reproduces the treadmill):**
1. Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`.
2. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` with the new token.
3. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` to verify it authenticates.
4. `gh run rerun 25260091455 --repo alexsiri7/reli --failed` to retry the failed pipeline.

**Option B — Durable (recommended, breaks the cycle):**
1. In the Railway dashboard, navigate to **Project Settings → Tokens** (NOT Account → Tokens).
2. Mint a Project token scoped to the staging environment; install as `RAILWAY_TOKEN`.
3. (Optional, for cleaner separation) mint a second Project token for production and store as a separate secret; if the workflow keeps a single `RAILWAY_TOKEN`, ensure it is the staging one and that production has its own credential.
4. Open a follow-up PR per Step 3 below to make the workflow speak the Project-token protocol; the new token will fail validation under the *current* validator (`{me{id}}` does not work for Project tokens), so Step 2 and Step 3 must land together.

---

### Step 3 (DEFERRED — separate PR) — Make the workflow speak the Project-token protocol

This is **out of scope for this bead** (the bead is investigation-only and CLAUDE.md says to mail mayor on out-of-scope discoveries — see Polecat Scope Discipline). Capturing here so the eventual implementer has the diff.

**File**: `.github/workflows/staging-pipeline.yml`
**Lines**: 32-58 (validator), plus equivalent header changes in every Railway-API call site downstream.

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

**Why**: A Project token has no associated `me` user, so the current query returns null even when the token is valid. The deploy mutations themselves (`serviceInstanceUpdate`, `serviceInstanceDeploy`) accept Project tokens but require the `Project-Access-Token:` header, not `Authorization: Bearer`. See `web-research.md` §§1, 3, 5.

**File**: `docs/RAILWAY_TOKEN_ROTATION_742.md`
**Lines**: 24-26
**Required change**: Replace the `https://railway.com/account/tokens` URL with the Project-Settings → Tokens path, plus a one-line note that `RAILWAY_TOKEN` must be a Project token, not an Account token.

---

## Patterns to Follow

**Investigation artifact shape — mirror this exactly (from prior bead, comment on #912):**

```markdown
## 🔍 Investigation: <title>
**Type**: `BUG`
### Assessment
| Metric | Value | Reasoning |
| Severity | `HIGH` | ... |
| Complexity | `LOW` | ... |
| Confidence | `HIGH` | ... |
### Problem Statement
### Root Cause Analysis
### Implementation Plan
| Step | File | Change |
### Validation
### Next Step
```

The series of prior investigations (#903, #907, #909, #912) all use the same skeleton; this bead follows it.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Like-for-like rotation in Step 2A succeeds but expires again within hours | This has happened 24 times today; recommend Step 2B (Project token) instead. |
| Step 2B (mint Project token) installed without Step 3 (workflow update) | The current validator's `{me{id}}` query will reject a healthy Project token; the validator must be updated in the same change window. Either land Step 3 first behind a feature flag, or hold Step 2B until Step 3's PR is ready. |
| Project token is environment-scoped — staging vs prod | A single Project token covers one environment. Confirm whether the staging and production deploys point at separate Railway environments (likely yes given the separate `RAILWAY_STAGING_*` and `RAILWAY_PRODUCTION_*` secrets). If so, two Project tokens are needed. |
| Agent accidentally creates `.github/RAILWAY_TOKEN_ROTATION_915.md` claiming rotation done | Explicitly forbidden by `CLAUDE.md` § Railway Token Rotation (Category 1 error). This bead does NOT do that. |
| `pipeline-health-cron.sh` fires another duplicate issue before the token is rotated | Issue #915 is tagged `archon:in-progress`, which prevents re-pickup. Subsequent main runs may still file new issues — acceptable noise; the token rotation closes them in a batch. |

---

## Validation

### Automated checks for this bead (docs-only)

```bash
# This bead writes only an investigation artifact; no code or tests change.
# Verify the artifact renders and the comment posts cleanly.
gh issue view 915 --repo alexsiri7/reli --comments
```

### Manual verification (after the human rotates the token)

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run watch --repo alexsiri7/reli
gh run rerun 25260091455 --repo alexsiri7/reli --failed
```

Expect: validator step prints no `::error::`, the staging deploy job goes green, the gated production job runs.

---

## Scope Boundaries

**IN SCOPE for this bead:**
- Create `artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/investigation.md` (this file).
- Post a GitHub comment on #915 routing the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` and surfacing the durable-fix recommendation.

**OUT OF SCOPE (do NOT touch in this bead):**
- The `RAILWAY_TOKEN` secret itself — agents cannot rotate it (`CLAUDE.md` § Railway Token Rotation).
- `.github/workflows/staging-pipeline.yml` — the durable fix is a separate PR per Polecat Scope Discipline.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` URL fix — same; mail mayor instead of fixing in-bead.
- Closing #911, #912, #915 — they should be closed together once the token is rotated and CI is green; that is the rotator's call.

**Mail to mayor (per Polecat Scope Discipline)**: the durable fix described in Step 3 is out of scope for this bead but warranted given 64 occurrences. Attempted `gt mail send mayor/` from both the worktree and the alexsiri7 workspace; both rejected with `Error: not in a Gas Town workspace`. The recommendation is captured in the GitHub comment on #915 (visible to mayor) and in the committed `web-research.md` (eight primary sources), which is the same surface area the mail would have reached.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T19:55:00Z
- **Artifact**: `artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/investigation.md`
- **Companion artifact**: `artifacts/runs/e05620507f1e5c5cdf1abea3cc3041b8/web-research.md` (primary-source evidence for token-class hypothesis)
- **Run under investigation**: 25260091455 (Staging → Production Pipeline, SHA `9117b40`)
- **Failure mode**: 64th `RAILWAY_TOKEN is invalid or expired: Not Authorized`, 24th today
