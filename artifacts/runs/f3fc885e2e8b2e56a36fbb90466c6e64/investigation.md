# Investigation: Prod deploy failed on main (#769)

**Issue**: #769 (https://github.com/alexsiri7/reli/issues/769)
**Type**: BUG
**Investigated**: 2026-04-30T07:35:00Z
**Workflow**: `f3fc885e2e8b2e56a36fbb90466c6e64`

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Every staging+prod deploy is blocked at the pre-flight `Validate Railway secrets` step; nothing can ship until a human rotates the GitHub Actions secret. |
| Complexity | LOW | No code change is permitted — the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md` and the action is a single secret rotation in the Railway dashboard followed by `gh secret set`. |
| Confidence | HIGH | CI log on run `25150135217` emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized`; this is the 9th identical recurrence — the canonical (commit-message-numbered) chain is `#733 (1st) → #739 (2nd) → #742 (3rd) → #755 (4th) → #762 (5th) → #751 (6th) → #766 (7th) → #762 (8th, re-fire) → #769 (9th)` — and the next run `25151102981` (against the just-merged investigation #768) failed with the same error, proving the secret has not been rotated. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight step at `.github/workflows/staging-pipeline.yml:32-58` calls Railway's `me{id}` GraphQL probe, receives `Not Authorized`, and aborts the deploy. The pickup cron filed #769 at 2026-04-30T06:30Z against SHA `160757f` after run `25150135217` failed at 06:04Z — a fresh sister issue, not an internal re-fire of #762. As of 2026-04-30T07:35Z this is the 9th identical recurrence. The canonical chain (taken verbatim from the `(Nth RAILWAY_TOKEN expiration)` suffix in the merged investigation commits) is **8 unique issues with #762 firing twice = 9 occurrences**: `#733 (1st) → #739 (2nd) → #742 (3rd) → #755 (4th) → #762 (5th, PR #764) → #751 (6th, PR #765) → #766 (7th, PR #767) → #762 (8th, re-fire, PR #768) → #769 (9th, this PR)`. The staging pipeline run on the merge of investigation PR #768 (`25151102981`, SHA `777115e`) also failed at the same step — confirming the rotation has not yet been performed by a human.

> **Related-but-separate** (do NOT belong in the RAILWAY_TOKEN chain): #758 / #759 are an `HTTP 000000` lifespan/production-config defect (fixed by `93c8ce4`), not a token expiration. They appear in some informal listings but the title and root cause differ.

---

## Analysis

### First-Principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Pre-flight token probe | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Working as designed — emits `RAILWAY_TOKEN is invalid or expired: Not Authorized` and exits 1 when Railway rejects the bearer token. |
| Daily token health monitor | `.github/workflows/railway-token-health.yml` | Yes | Working as designed — last two scheduled runs (`25049349913` on 2026-04-28, `25105119767` on 2026-04-29) both failed, surfacing the expiry well before the prod deploy attempt. |
| Token lifecycle | (external — Railway dashboard) | Partial | The 9-occurrence recurrence pattern (8 unique issues, #762 fired twice) shows that prior rotations accepted Railway's default finite TTL instead of selecting **No expiration**. The repo cannot fix this; only a human at https://railway.com/account/tokens can. |
| Auto-pickup cron / `archon:in-progress` loop-stopper | `pipeline-health-cron.sh` (external) | No (deferred) | The cron filed #769 ~30 minutes *after* PR #768 (which investigates the very same expiry) merged. There is still no label-driven gate to prevent fresh sister-issue creation while a same-root-cause investigation is open. Documented as deferred follow-up #1 below. |
| Agent rotation guard | `CLAUDE.md` § "Railway Token Rotation" | Yes | Correctly forbids agents from creating `.github/RAILWAY_TOKEN_ROTATION_*.md` files claiming completion (Category 1 error). |

The primitives in the repo are sound. The failure is in the secret value, not in any tracked file.

### Root Cause / 5 Whys

WHY: Pipeline run `25150135217` failed.
↓ BECAUSE: Job `Deploy to staging` failed at step `Validate Railway secrets`.
  Evidence: `2026-04-30T06:04:56.9938282Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ BECAUSE: `curl -sf -X POST` to `https://backboard.railway.app/graphql/v2` with the stored bearer token returned an unauthorized response, so `jq -e '.data.me.id'` failed.
  Evidence: `.github/workflows/staging-pipeline.yml:49-58`
↓ BECAUSE: The token in `secrets.RAILWAY_TOKEN` has reached its expiry date and was not rotated when investigation #768 landed.
  Evidence: Run `25151102981` (created 2026-04-30T06:34:37Z, SHA `777115e` — i.e., the merge commit of investigation PR #768) failed with the identical error string. If the secret had been rotated between #762 closing and #769 firing, that run would have succeeded.
↓ ROOT CAUSE: Prior rotations created Railway tokens with a finite TTL instead of selecting **No expiration**, producing a recurrence cadence of roughly once every few weeks. No human has yet performed the rotation that resolves the current expiry window.
  Evidence: Canonical chain (per merged investigation commit messages) `#733 (1st) → #739 (2nd) → #742 (3rd) → #755 (4th) → #762 (5th) → #751 (6th) → #766 (7th) → #762 (8th, re-fire) → #769 (9th)` — 8 unique issues with #762 firing twice. Failed CI run IDs across these recurrences include `25028112865, 25126991550, 25142788611, 25145158555, 25148434478, 25150135217, 25151102981` (a partial list — the cron has produced more failed runs than there are issue numbers because each label-cleared issue can reopen and re-fire CI before rotation).

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| *(none)* | — | NONE | No code change is appropriate. The workflow YAML is correct — it is doing its job by failing closed when the token is bad. Editing it would mask the real defect. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight Railway token probe (working).
- `.github/workflows/staging-pipeline.yml:60-…` — staging deploy (`Authorization: Bearer $RAILWAY_TOKEN` at line 72) that consumes the same secret.
- `.github/workflows/railway-token-health.yml` — daily probe; red since 2026-04-28 (working as instrumentation).
- `secrets.RAILWAY_TOKEN` — the **single source of truth that needs rotating**; lives in GitHub repo secrets, mintable only via https://railway.com/account/tokens.

### Git History

- Latest commit on `main` at issue-fire time: `160757f docs: investigation for issue #766 (7th RAILWAY_TOKEN expiration) (#767)`.
- Latest commit on `main` now: `777115e docs: investigation for issue #762 (8th RAILWAY_TOKEN expiration) (#768)` — landed at 07:30Z, ~1 hour after #769 was filed; its post-merge `staging-pipeline.yml` run (`25151102981`) failed with the same `Not Authorized`.
- Sister/lineage issues: `#751` (6th, PR #765) and `#766` (7th, PR #767) are core members of the canonical chain — each numbered as the "Nth RAILWAY_TOKEN expiration" in its merge commit — and are CLOSED with investigation-only PRs landed but **without** rotation. `#762` is CLOSED with two investigation-only PRs landed (#764 as the 5th and #768 as the 8th re-fire), again **without** the human rotation step having been performed. `#755` (4th, PR #761) was investigated as "the 4th occurrence (previous: #733, #739, #742)" per its own investigation comment — confirming the chain through 1–4 from the issue side.
- **Implication**: The recurrence is a long-standing operational hazard caused by the long-lived PAT model and a missing pickup-cron loop-stopper. See "Suggested Follow-up" below.

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
  **not** offer "No expiration" (per `web-research.md` Finding 4 in PR
  #768's artifact: *Railway's published docs do not describe a "no
  expiration" option — the dashboard UI may or may not expose it; the
  human rotator should verify visually and report back*), select the
  longest available TTL, record the dropdown's actual options as a comment
  on #769, and proceed. A follow-up bead will amend
  `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Name suggestion: `github-actions-permanent`.

> Known failure mode: a Railway community thread reports that
> `RAILWAY_TOKEN` may have been tightened to project-only. If a fresh
> Workspace token still returns `Not Authorized`, see PR #768's
> `web-research.md` Finding 1 (*"RAILWAY_TOKEN now only accepts project
> tokens" — community-confirmed; account/workspace tokens emit the
> "invalid or expired" message even when freshly minted*). The remediation
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
gh run rerun 25151102981 --repo alexsiri7/reli --failed
# (run on 777115e — the most recent failure on main, on top of the just-landed investigation #768)
```

### Step 5 (Either): Close the issue and clear the label

- Close #769 with a comment linking to the green workflow run.
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

The companion investigation for the immediately-preceding occurrence is at
`artifacts/runs/0c44823de5470e5c9687e943e83f9414/investigation.md`
(landed via PR #768). Its `web-research.md` already enumerates the 5
findings (Workspace-vs-Project token contract, dashboard "No expiration"
gap, recurrence count, etc.); no new web research is required for #769
because the root cause and remediation are unchanged.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Rotator picks a Project token instead of a Workspace token | Step 1 explicitly calls out: must be Workspace; project tokens use a different header and will fail the `me{id}` probe. |
| Rotator accepts default TTL again | Step 1 explicitly calls out: **No expiration**. This is what fixed #742 and what subsequent rotators forgot. |
| Auto-pickup cron files a 10th sister issue before the rotation completes | The cron has now produced 8 unique issues with #762 firing twice = 9 occurrences without a single rotation. Loop-stopper requires both rotation **and** label removal **and** issue closure — Step 5 covers all three; deferred follow-up #1 hardens it. |
| Future Railway-side `.app` retirement | Defensive cleanup (P3) listed under "Suggested Follow-up"; not blocking. |
| Investigation churn | Filing investigation-only artifacts on every recurrence is itself becoming noise. If a 10th recurrence fires before rotation, agents should comment "duplicate of #769 — same expired token, see #768 for full investigation" and skip a new artifact, per the spirit of `CLAUDE.md` § Polecat Scope Discipline. |

---

## Validation

### Automated Checks

```bash
# Post-rotation, in this order:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1   # conclusion: success
gh run rerun 25151102981 --repo alexsiri7/reli --failed
gh run list --workflow staging-pipeline.yml --repo alexsiri7/reli --limit 1       # conclusion: success
```

### Manual Verification

1. Confirm in the Railway dashboard that the new token shows **No expiration**.
2. Confirm that prod URL `https://reli.interstellarai.net` returns 200 after the deploy completes.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation document.
- The GitHub comment on #769 summarising the 9th recurrence and the human action checklist.

**OUT OF SCOPE (do not touch):**
- Any source/workflow files. The workflow correctly fails when the token is bad — touching it would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical runbook is already correct.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — Category 1 error per `CLAUDE.md`.
- A new `web-research.md` companion — the existing one in `artifacts/runs/0c44823de5470e5c9687e943e83f9414/web-research.md` (landed via #768) is unchanged.
- Filing the suggested follow-up issues — defer until #769 is closed and rotation is verified.

### Suggested Follow-up Issues (file after #769 closes)

1. **Investigation-only loop-stopper for `archon:in-progress`** (P2) — the pickup cron has produced 9 occurrences across 8 unique issues (with #762 re-firing once) on the same expired secret because no PR ever lands on no-op investigations. Add a label-removal path tied to issue closure and/or de-dupe by error-string fingerprint.
2. **Migrate away from long-lived `RAILWAY_TOKEN` PAT** (P2) — 9 identical recurrences. Railway has no OIDC trust feature as of April 2026, so realistic options are a service-account token or a scheduled-rotation automation.
3. **Standardise on `backboard.railway.com` across all `curl` sites** (P3) — defensive against a future `.app` retirement; affects 7 `curl` calls in `staging-pipeline.yml` and `railway-token-health.yml`.
4. **Rename secret `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN`** (P3) — Railway CLI conventions now treat `RAILWAY_TOKEN` as project-only; rename reduces footgun risk for future rotators.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7)
- **Timestamp**: 2026-04-30T07:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/f3fc885e2e8b2e56a36fbb90466c6e64/investigation.md`
- **Companion artifact (re-used from #762/#768)**: `artifacts/runs/0c44823de5470e5c9687e943e83f9414/web-research.md`
- **Latest failed runs**:
  - https://github.com/alexsiri7/reli/actions/runs/25150135217 (issue-trigger, SHA `160757f`)
  - https://github.com/alexsiri7/reli/actions/runs/25151102981 (post-#768 merge, SHA `777115e`)
- **Recurrence number**: 9th overall (8 unique issues `#733, #739, #742, #755, #762, #751, #766, #769` with #762 firing twice — 5th in PR #764 and 8th re-fire in PR #768; canonical numbering taken from each merged investigation commit's `(Nth RAILWAY_TOKEN expiration)` suffix)
