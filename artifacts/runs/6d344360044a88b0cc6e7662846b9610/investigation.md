# Investigation: Main CI red: Deploy to staging (#771)

**Issue**: #771 (https://github.com/alexsiri7/reli/issues/771)
**Type**: BUG
**Investigated**: 2026-04-30T07:50:00Z
**Workflow**: `6d344360044a88b0cc6e7662846b9610`

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Every staging+prod deploy is blocked at the pre-flight `Validate Railway secrets` step on `.github/workflows/staging-pipeline.yml:32-58`; nothing can ship to staging or production until a human rotates the GitHub Actions secret. |
| Complexity | LOW | No code change is permitted — the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md` and the action is a single secret rotation in the Railway dashboard followed by `gh secret set`. |
| Confidence | HIGH | The CI log on run `25151102981` emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized`; this is the 10th identical recurrence — the canonical (commit-message-numbered) chain is `#733 (1st) → #739 (2nd) → #742 (3rd) → #755 (4th) → #762 (5th) → #751 (6th) → #766 (7th) → #762 (8th, re-fire) → #769 (9th) → #771 (10th)` — and the very same run (`25151102981`) is already cited verbatim in PR #770's investigation as proof the secret has not yet been rotated. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. Pipeline run `25151102981` (workflow `Staging → Production Pipeline`, SHA `777115e` — the merge of investigation PR #768) failed at the pre-flight `Validate Railway secrets` step at 2026-04-30T06:34:42Z with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. The pickup cron filed #771 at 2026-04-30T07:00:26Z — **30 minutes after #769 (the 9th expiration) was filed at 06:30:27Z, and ~20 minutes after PR #768 (the 8th investigation) merged at 07:30Z**. #771 is therefore a sister/re-fire of #769 driven by the same unrotated secret on a different downstream run, not an independent root cause.

> **Important — duplicate observation:** PR #770 (the in-flight investigation for #769) explicitly cites run `25151102981` as the post-merge confirmation that the secret has not been rotated. That is the very same run that triggered #771. Issue #771 exists only because the auto-pickup cron filed a fresh sister issue while a same-root-cause investigation was already open. This is the missing primitive previously logged as PR #770's deferred follow-up #1 (no `archon:in-progress` open-investigation gate on the cron).

---

## Analysis

### First-Principles

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Pre-flight token probe | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Working as designed — emits `RAILWAY_TOKEN is invalid or expired: Not Authorized` and exits 1 when Railway rejects the bearer token. |
| Daily token health monitor | `.github/workflows/railway-token-health.yml` | Yes | Working as designed — has been red since 2026-04-28, surfacing the expiry well before each prod-deploy attempt. |
| Token lifecycle | (external — Railway dashboard) | Partial | The 10-occurrence recurrence pattern (8 unique issues, #762 fired twice) shows that prior rotations accepted Railway's default finite TTL instead of selecting **No expiration**. The repo cannot fix this; only a human at https://railway.com/account/tokens can. |
| Auto-pickup cron / `archon:in-progress` loop-stopper | `pipeline-health-cron.sh` (external) | No (still deferred) | The cron filed #771 at 07:00Z while #769 was already open with `archon:in-progress` and PR #770 was in flight. The label-stopper guards a single issue against double-pickup, but does **not** guard against fresh sister-issue creation when the same root cause re-fires on a different run/SHA. PR #770's investigation already identified this gap as deferred follow-up #1; #771 is the empirical second observation of the same gap and strengthens the case. |
| Agent rotation guard | `CLAUDE.md` § "Railway Token Rotation" | Yes | Correctly forbids agents from creating `.github/RAILWAY_TOKEN_ROTATION_*.md` files claiming completion (Category 1 error). |

The primitives in the repo are sound. The failure is in the secret value, not in any tracked file. The cron-side primitive is unsound, but it lives outside this repo and is correctly out-of-scope here per Polecat Scope Discipline (file separately to mayor as a follow-up — see "Suggested Follow-up" below).

### Root Cause / 5 Whys

WHY: Pipeline run `25151102981` failed.
↓ BECAUSE: Job `Deploy to staging` failed at step `Validate Railway secrets`.
  Evidence: `2026-04-30T06:34:42.8397613Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`
↓ BECAUSE: `curl -sf -X POST` to `https://backboard.railway.app/graphql/v2` with the stored bearer token returned an unauthorized response, so `jq -e '.data.me.id'` failed.
  Evidence: `.github/workflows/staging-pipeline.yml:49-58`
↓ BECAUSE: The token in `secrets.RAILWAY_TOKEN` has reached its expiry date and was not rotated when investigations #768 (8th) merged or when #769 (9th) was filed earlier this morning.
  Evidence: Run `25151102981` (created 2026-04-30T06:34:37Z, SHA `777115e` — i.e., the merge commit of investigation PR #768) and the immediately-preceding run `25150135217` (06:04Z, SHA `160757f`) both failed with the identical error string. If the secret had been rotated between #768 closing and #771 firing, run `25151102981` would have succeeded.
↓ ROOT CAUSE: Prior rotations created Railway tokens with a finite TTL instead of selecting **No expiration**, producing a recurrence cadence of roughly once every few weeks. No human has yet performed the rotation that resolves the current expiry window. Additionally, the auto-pickup cron's missing open-investigation gate is amplifying the pattern by filing fresh sister issues (#771 → #769) while same-root-cause investigations are already in flight, multiplying the human triage cost per actual rotation cycle.
  Evidence: Canonical chain `#733 (1st) → #739 (2nd) → #742 (3rd) → #755 (4th) → #762 (5th) → #751 (6th) → #766 (7th) → #762 (8th, re-fire) → #769 (9th) → #771 (10th)`. Failed CI run IDs across these recurrences include `25028112865, 25126991550, 25142788611, 25145158555, 25148434478, 25150135217, 25151102981` — and the cron has produced more failed runs than there are issue numbers because each label-cleared issue can reopen and re-fire CI before rotation.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| *(none)* | — | NONE | No code change is appropriate. The workflow YAML is correct — it is doing its job by failing closed when the token is bad. Editing it would mask the real defect. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight Railway token probe (working).
- `.github/workflows/staging-pipeline.yml:60-80` — staging deploy (`Authorization: Bearer $RAILWAY_TOKEN` at line 72) that consumes the same secret.
- `.github/workflows/railway-token-health.yml` — daily probe; red since 2026-04-28 (working as instrumentation).
- `secrets.RAILWAY_TOKEN` — the **single source of truth that needs rotating**; lives in GitHub repo secrets, mintable only via https://railway.com/account/tokens.
- PR #770 — currently OPEN, addressing #769 with the same root cause; this investigation should be considered a sister and is functionally a duplicate of #770's analysis.

### Git History

- Latest commit on `main` at issue-fire time (07:00:26Z): `777115e docs: investigation for issue #762 (8th RAILWAY_TOKEN expiration) (#768)`, merged ~07:30Z (the merge of which is the SHA against which #771's failing run was triggered).
- Sister/lineage issues: `#751` (6th, PR #765), `#766` (7th, PR #767), `#762` (5th and 8th, PRs #764 and #768) are CLOSED with investigation-only PRs landed — each numbered as the "Nth RAILWAY_TOKEN expiration" in its merge commit — but **without** the human rotation step having been performed. `#769` (9th) is OPEN with PR #770 in flight.
- Workflow file last-touched: `git log -1 --format="%h %s" -- .github/workflows/staging-pipeline.yml` shows the validation step itself is unchanged across this entire chain — corroborating that the YAML is sound and the defect is the secret value.
- **Implication**: The recurrence is a long-standing operational hazard caused by the long-lived PAT model and a missing pickup-cron loop-stopper. The fact that #771 fired on the merge of an investigation PR for the *same* expiry, while another investigation PR (#770) for the *same* expiry was already open, is the strongest empirical signal yet that the cron-side gate is the next operational improvement to make.

---

## Implementation Plan

This is an **investigation-only, no-PR incident by design**. There is no agent-actionable code change. The plan below is the human-action checklist.

### Step 1 (Human): Mint a new Railway token

- Go to https://railway.com/account/tokens.
- Create a **Workspace token** (NOT a project token — `staging-pipeline.yml` uses the `Authorization: Bearer` header at line 50, which is the account/workspace contract; project tokens require the `Project-Access-Token` header and will fail the `me{id}` probe).
- Set **Expiration: No expiration** if available — this is the recurrence-breaker; do not accept the default TTL. If the dashboard does not offer "No expiration", select the longest available TTL and record the dropdown's actual options as a comment on #771 so a follow-up bead can amend `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Name suggestion: `github-actions-permanent`.

### Step 2 (Human): Update the GitHub secret

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted
```

### Step 3 (Human): Re-run the failed CI

```bash
gh run rerun 25151102981 --repo alexsiri7/reli --failed
```

A successful re-run validates the rotation and unblocks the staging→production pipeline. Once green, **both #769 and #771 will close together** (same root cause, same secret value, no per-issue work).

### Step 4 (Agent — already done by this artifact)

- Open this docs-only PR with `Fixes #771`.
- Do **not** create `.github/RAILWAY_TOKEN_ROTATION_*.md`.
- Do **not** edit `.github/workflows/staging-pipeline.yml`.
- Direct the human in the PR body and the issue comment to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Patterns to Follow

This investigation mirrors the pattern of PR #770 (issue #769, 9th expiration), PR #768 (issue #762, 8th re-fire), and PR #767 (issue #766, 7th expiration): a docs-only artifact, no code or workflow edits, all guidance pointing at the existing `docs/RAILWAY_TOKEN_ROTATION_742.md` runbook.

```markdown
<!-- SOURCE: artifacts/runs/f3fc885e2e8b2e56a36fbb90466c6e64/investigation.md (PR #770, issue #769) -->
This is an **investigation-only, no-PR incident by design**. There is no
agent-actionable code change. The plan below is the human-action checklist.
```

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Human rotates the token but does not re-run the failed staging-pipeline run | The `workflow_run` trigger will fire on the next CI completion on `main`. Even without a manual re-run, the next merge will validate the rotation. The pickup cron will, however, continue filing fresh sister issues until either the token is rotated or the cron is gated. |
| Newly-minted Workspace token still returns `Not Authorized` | Per PR #768's `web-research.md` Finding 1, Railway may have tightened `RAILWAY_TOKEN` to project-only. If a fresh Workspace token still fails, the human should mint a project token, switch the `Authorization: Bearer` header at `.github/workflows/staging-pipeline.yml:50` and `:72` to `Project-Access-Token: $RAILWAY_TOKEN`, and re-test. That workflow edit would be a separate, human-authorized PR — not appropriate for this investigation. |
| #769 closes before #771 (or vice versa) | Both issues will resolve on the same rotation. Closing one before the other is fine — the open one will go green on the next workflow run. |
| Cron fires an 11th sister issue before rotation lands | This would further confirm the deferred follow-up #1 from PR #770. Suggested response: link the new issue back to #769 / #770 / #771 as duplicates and continue waiting on the human rotation; do not produce an 11th investigation artifact. |

---

## Validation

### Automated Checks

This is a docs-only artifact. No code-level automated checks apply.

```bash
# Confirm no source files were changed
git diff origin/main...HEAD -- '*.py' '*.ts' '*.tsx' '*.js' '*.jsx' '*.yml' '*.yaml' '*.json'
# Expected output: empty
```

### Manual Verification

1. Human rotates the token per `docs/RAILWAY_TOKEN_ROTATION_742.md` (steps 1–2 above).
2. Human re-runs the failed staging-pipeline run: `gh run rerun 25151102981 --repo alexsiri7/reli --failed`.
3. Confirm the `Validate Railway secrets` step passes and the deploy succeeds.
4. Both #769 and #771 close (either via `Fixes` references in the merged investigation PRs or manually).
5. The next daily run of `.github/workflows/railway-token-health.yml` goes green.

---

## Scope Boundaries

**IN SCOPE:**
- Documenting the 10th recurrence and updating the canonical chain.
- Pointing the human operator at `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Recording the new empirical evidence for PR #770's deferred follow-up #1 (cron open-investigation gate is missing — confirmed twice now).

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — failing closed correctly; editing it would mask the defect.
- `.github/workflows/railway-token-health.yml` — instrumentation working as designed.
- Any `.github/RAILWAY_TOKEN_ROTATION_*.md` file — explicitly forbidden by `CLAUDE.md` § "Railway Token Rotation" (Category 1 error).
- The `pipeline-health-cron.sh` open-investigation gate — lives outside the repo and was already filed to mayor as deferred follow-up #1 by PR #770. Sending a second mail would be redundant; this artifact is sufficient corroboration.
- Updating `docs/RAILWAY_TOKEN_ROTATION_742.md` to reflect the new occurrence count or the (hypothetical) project-vs-workspace token tightening — defer until a human has actually rotated and reported back what dropdown options the dashboard exposed.

---

## Suggested Follow-up

After the human rotation lands, the highest-leverage next operational improvement is the same one PR #770 identified: gate the auto-pickup cron on open-`archon:in-progress` issues for the same workflow/error fingerprint, so a single root cause does not generate a stream of sister issues (#769 + #771 in this cycle alone). #771's existence — filed against the merge of an investigation PR (#768) for the same expiry while another investigation PR (#770) was already open — is the strongest empirical signal yet that this gate is needed.

This is **not a Polecat-scope item** for this issue and should remain deferred. Recording it here for archive only.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-04-30T07:50:00Z
- **Artifact**: `artifacts/runs/6d344360044a88b0cc6e7662846b9610/investigation.md`
- **Companion artifacts**: PR #770's `artifacts/runs/f3fc885e2e8b2e56a36fbb90466c6e64/investigation.md` (issue #769, 9th expiration); PR #768's `artifacts/runs/0c44823de5470e5c9687e943e83f9414/{investigation.md, web-research.md}` (issue #762, 8th re-fire) — both still current; root cause and remediation are unchanged from the 8th and 9th occurrences.
