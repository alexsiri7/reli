# Investigation: Prod deploy failed on main (#762)

**Issue**: #762 (https://github.com/alexsiri7/reli/issues/762)
**Type**: BUG
**Investigated**: 2026-04-30T07:05:00Z
**Workflow**: `0c44823de5470e5c9687e943e83f9414`

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | All staging+prod deploys are blocked at the pre-flight `Validate Railway secrets` step; nothing can ship to prod until a human rotates the GitHub Actions secret. |
| Complexity | LOW | No code change is needed or permitted — the runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md` and the action is a single secret rotation in the Railway dashboard + `gh secret set`. |
| Confidence | HIGH | CI log emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized` (verified on run `25148434478`); this is the 8th identical recurrence in lineage `#733 → #739 → #742 → #755 → #762`. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret has expired again. The `Validate Railway secrets` pre-flight step in `.github/workflows/staging-pipeline.yml` calls Railway's `me{id}` GraphQL probe, receives `Not Authorized`, and aborts the deploy. As of 2026-04-30T05:06Z this has produced 5 consecutive failed `staging-pipeline.yml` runs (`25148434478, 25145158555, 25142788611, 25126991550, 25028112865`) and 2 consecutive failed `railway-token-health.yml` runs (`25105119767, 25049349913`). This is the 8th identical recurrence (decomposition: 5 sister issues `#733 → #739 → #742 → #755 → #762` + 3 internal re-fires of #762 = 8 total) and the 6th internal re-fire of #762 itself.

---

## Analysis

### First-Principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Pre-flight token probe | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Working as designed — correctly emits the failure when Railway rejects the bearer token. |
| Daily token health monitor | `.github/workflows/railway-token-health.yml` | Yes | Working as designed — has been red since 2026-04-28, surfacing the expiry one day before the prod deploy attempted. |
| Token lifecycle | (external — Railway dashboard) | Partial | The recurrence pattern (8 instances) shows that prior rotations accepted Railway's default finite TTL instead of selecting **No expiration**. The repo cannot fix this; only a human at https://railway.com/account/tokens can. |
| Agent rotation guard | `CLAUDE.md` § "Railway Token Rotation" | Yes | Correctly forbids agents from creating `.github/RAILWAY_TOKEN_ROTATION_*.md` files claiming completion. |

The primitives in the repo are sound. The failure is in the secret value, not in any tracked file.

### Root Cause / 5 Whys

WHY: Pipeline `25148434478` failed.
↓ BECAUSE: Job `Deploy to staging` failed at step `Validate Railway secrets`.
  Evidence: `2026-04-30T05:06:28.1734266Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ BECAUSE: `curl` to `https://backboard.railway.app/graphql/v2` with the stored bearer token returned an unauthorized response and `jq -e '.data.me.id'` failed.
  Evidence: `.github/workflows/staging-pipeline.yml:49-55`
↓ BECAUSE: The token in `secrets.RAILWAY_TOKEN` has reached its expiry date.
↓ ROOT CAUSE: Prior rotations created Railway tokens with a finite TTL instead of selecting **No expiration**, producing a recurrence cadence of roughly once every few weeks.
  Evidence: Lineage `#733 → #739 → #742 → #755 → #762`, plus internal re-fires `e2590c72… → 7aff6779… → a7fa2891… → 35fa9a45… → 6cdcd6bf… → 0c44823d…` (this run).

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| *(none)* | — | NONE | No code change is appropriate. The workflow YAML is correct — it is doing its job by failing closed when the token is bad. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight Railway token probe (working).
- `.github/workflows/railway-token-health.yml` — daily probe; red since 2026-04-28 (working as instrumentation).
- `secrets.RAILWAY_TOKEN` — the **single source of truth that needs rotating**; lives in GitHub repo secrets, mintable only via https://railway.com/account/tokens.

### Git History

- Latest commit on `main`: `160757f docs: investigation for issue #766 (7th RAILWAY_TOKEN expiration) (#767)` — investigation-only doc PR; no behaviour change.
- Sister/lineage issues: `#751` and `#766` are now CLOSED (resolved as duplicates of the same root cause).
- **Implication**: Long-standing operational hazard — long-lived PAT model is the wrong primitive for this dependency. See "Suggested Follow-up" below.

---

## Implementation Plan

This is an **investigation-only, no-PR incident by design**. There is no agent-actionable code change. The plan below is the human-action checklist.

### Step 1 (Human): Mint a new Railway token

- Go to https://railway.com/account/tokens.
- Create a **Workspace token** (NOT a project token — `staging-pipeline.yml`
  uses the `Authorization: Bearer` header at line 50, which is the
  account/workspace contract; project tokens require the
  `Project-Access-Token` header and will fail the `me{id}` probe).
- Set **Expiration: No expiration** if available — this is the
  recurrence-breaker; do not accept the default TTL. If the dashboard does
  **not** offer "No expiration" (`web-research.md` Finding 4 documents this
  gap), select the longest available TTL, record the dropdown's actual
  options as a comment on #762, and proceed. A follow-up bead will amend
  `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Name suggestion: `github-actions-permanent`.

> Known failure mode: a Railway community thread reports that `RAILWAY_TOKEN`
> may have been tightened to project-only. If a fresh Workspace token still
> returns `Not Authorized`, see `web-research.md` Finding 1 — the remediation
> is to switch the workflow header to `Project-Access-Token` in a separate
> bead, *not* to mint a project token against the current Bearer header.

### Step 2 (Human): Update the GitHub secret

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token value when prompted.
```

### Step 3 (Either): Verify the token

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1
# Expect: conclusion: success
```

### Step 4 (Either): Unblock the latest deploy

```bash
gh run rerun 25148434478 --repo alexsiri7/reli --failed
```

### Step 5 (Either): Close the issue and clear the label

- Close #762 with a comment linking to the green workflow run.
- Remove the `archon:in-progress` label so the auto-pickup cron stops re-firing.

---

## Patterns to Follow

The canonical playbook for this rotation is already documented:

```
docs/RAILWAY_TOKEN_ROTATION_742.md
```

> ⚠️ Per `CLAUDE.md` § "Railway Token Rotation", agents must NOT create a
> `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming completion. That is a
> Category 1 error.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Rotator picks a Project token instead of a Workspace token | Step 1 explicitly calls out: must be Workspace; project tokens use a different header and will fail the `me{id}` probe. |
| Rotator accepts default TTL again | Step 1 explicitly calls out: **No expiration**. This is what fixed #742 and what subsequent rotators forgot. |
| Auto-pickup cron re-fires #762 again before close | Loop-stopper requires both rotation **and** label removal **and** issue closure — Step 5 covers all three. |
| Future Railway-side `.app` retirement | Defensive cleanup (P3) listed under "Suggested Follow-up"; not blocking. |

---

## Validation

### Automated Checks

```bash
# Post-rotation, in this order:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1   # conclusion: success
gh run rerun 25148434478 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 1       # conclusion: success
```

### Manual Verification

1. Confirm in the Railway dashboard that the new token shows **No expiration**.
2. Confirm that prod URL `https://reli.interstellarai.net` returns 200 after the deploy completes.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation document.
- The GitHub comment summarising the 8th recurrence and the human action checklist.

**OUT OF SCOPE (do not touch):**
- Any source/workflow files. The workflow correctly fails when the token is bad — touching it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical runbook is already correct.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — Category 1 error per `CLAUDE.md`.
- Filing the suggested follow-up issues — defer until #762 is closed and rotation is verified.

### Suggested Follow-up Issues (file after #762 closes)

1. **Investigation-only loop-stopper for `archon:in-progress`** (P2) — the pickup cron has re-fired #762 six internal times because no PR ever lands on no-op investigations. Add a label-removal path tied to issue closure.
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — 8 identical recurrences. Railway has no OIDC trust feature as of April 2026, so the realistic options are a service-account token or a scheduled-rotation automation.
3. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against a future `.app` retirement; affects 7 `curl` calls in `staging-pipeline.yml` and `railway-token-health.yml`.
4. **Rename secret `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI conventions now treat `RAILWAY_TOKEN` as project-only; rename reduces footgun risk for future rotators.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7)
- **Timestamp**: 2026-04-30T07:05:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/0c44823de5470e5c9687e943e83f9414/investigation.md`
- **Companion artifact**: `web-research.md` (already present in same directory)
- **Latest failed run**: https://github.com/alexsiri7/reli/actions/runs/25148434478
- **Recurrence number**: 8th overall · 6th internal re-fire of #762
