# Investigation: Main CI red: Deploy to staging (#909)

**Issue**: #909 (https://github.com/alexsiri7/reli/issues/909)
**Type**: BUG (operational — external credential rejection)
**Investigated**: 2026-05-02T17:40:00Z
**Workflow run**: 71a21444dc75f75167bd149ae06d3f82

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging deploy chain is fully blocked at the validator step on every main CI completion; no in-repo workaround, but only the staging deploy job fails — non-deploy CI is unaffected. |
| Complexity | LOW | Zero code changes are warranted on this bead; the remediation is a human-only Railway dashboard rotation followed by `gh secret set RAILWAY_TOKEN`. Validator code at `.github/workflows/staging-pipeline.yml:49-58` is functioning as designed. |
| Confidence | HIGH | The failure message, endpoint, and step are byte-for-byte identical to the prior 61 incidents (most recently #907 about an hour ago, PR #908). The validator's `me{id}` probe returned the same `Not Authorized` GraphQL error. |

---

## Problem Statement

The "Validate Railway secrets" step in `.github/workflows/staging-pipeline.yml` failed
on run 25257755620 because Railway's auth backend rejected the token currently held in
`secrets.RAILWAY_TOKEN`. This is the 62nd recurrence of the same failure mode and the
22nd today (chain `#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #903/#904 → #907 → #909`).

---

## Analysis

### Root Cause / Change Rationale

The validator posts a `query { me { id } }` GraphQL request to
`https://backboard.railway.app/graphql/v2` with `Authorization: Bearer $RAILWAY_TOKEN`.
Railway returned `{"errors":[{"message":"Not Authorized"}]}`, which the validator
correctly surfaces as "RAILWAY_TOKEN is invalid or expired". The validator is correct;
the token is what is failing.

Per `CLAUDE.md` § Railway Token Rotation, the token lives in GitHub Actions secrets and
requires human access to railway.com; agents cannot rotate it. The fix is therefore
out of code-change scope for this bead.

### Evidence Chain

WHY: Why did "Deploy to staging" fail on run 25257755620?
↓ BECAUSE: The "Validate Railway secrets" step exited non-zero.
  Evidence: `Process completed with exit code 1.` at 2026-05-02T17:34:50Z.

↓ BECAUSE: The validator's `me{id}` probe to Railway returned `Not Authorized`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at
  2026-05-02T17:34:50Z.

↓ ROOT CAUSE: The token currently stored in `secrets.RAILWAY_TOKEN` is rejected by
  Railway's auth backend. Either it has expired, been revoked, or is the wrong token
  type for the validator's query (see `web-research.md` §2 — `me{id}` requires an
  Account/Personal token, not a Project Token).
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — validator code is
  unchanged from prior green runs and is identical across all 62 incidents.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | This bead requires no source-tree changes. The remediation is a GitHub Actions secret update performed by a human via the Railway dashboard + `gh secret set`. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:49-58` — the validator that surfaces the
  failure. Continues to behave correctly.
- `secrets.RAILWAY_TOKEN` (GitHub Actions secret) — the credential being rejected.
  Rotation requires human access to https://railway.com.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the existing human runbook.
- `.github/workflows/railway-token-health.yml` — out-of-band health check the human
  can trigger after rotation to verify the new token before re-running #909.

### Git History

- **Last validator change**: not modified in any of the 62 incidents — this is
  consistently a credential-rejection issue, not a regression in the validator.
- **Prior incident chain on the same root cause**: #878, #880, #882, #884, #886,
  #888, #891, #894, #896, #898, #901, #903, #904, #907 (immediate predecessor) — see
  PRs #879/#881/#883/#885/#887/#889/#892/#895/#897/#899/#902/#905/#906/#908 for the
  same investigation pattern.
- **Implication**: 62 occurrences and 22-in-one-day cadence suggest the recurrence is
  itself the bug to address (long-term). See `web-research.md` §1–§3 for the
  token-type-vs-query-type hypothesis that may explain why like-for-like rotations
  keep producing the same error.

---

## Implementation Plan

This bead does not modify the source tree. Per `CLAUDE.md` § Railway Token Rotation,
the only valid agent output here is (a) this investigation artifact and (b) a GitHub
comment directing the human operator to the runbook. Creating any
`.github/RAILWAY_TOKEN_ROTATION_909.md` file claiming rotation is done would be a
Category 1 error and is explicitly forbidden.

### Step 1: Document the failure (this artifact)

**File**: `artifacts/runs/71a21444dc75f75167bd149ae06d3f82/investigation.md`
**Action**: CREATE (this file)

### Step 2: Post investigation comment on issue #909

**Action**: `gh issue comment 909 --body @<formatted_comment>` summarizing this
artifact and pointing the human at the runbook.

### Step 3: Human follow-up (out of agent scope)

1. Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`.
   - Before another like-for-like rotation, consider `web-research.md`
     Recommendations §1 — verify whether the secret is an Account token or a Project
     token, since the chain has now repeated 14 times in <8 hours and a token-type
     mismatch surfaces as "Not Authorized" identically to expiration.
2. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` — verify the
   replacement authenticates before re-running the failed pipeline.
3. `gh run rerun 25257755620 --repo alexsiri7/reli --failed` — re-trigger the
   "Deploy to staging" job.
4. Confirm green run, close #909.

---

## Patterns to Follow

This investigation follows the exact pattern established by #907's investigation
comment (the immediate predecessor in the chain). Diff vs that prior pattern:

- Issue number: #907 → #909
- CI run ID: 25256579563 → 25257755620
- Incident count: "61st / 21st today" → "62nd / 22nd today"
- Predecessor chain extended by `#907`
- All other content and structure unchanged

```bash
# Identical validator code that fired the failure (unchanged across 62 incidents)
# .github/workflows/staging-pipeline.yml:49-58
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  echo "Rotate the token — see DEPLOYMENT_SECRETS.md Token Rotation section."
  exit 1
fi
```

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent creates `.github/RAILWAY_TOKEN_ROTATION_909.md` falsely claiming the token was rotated. | Explicitly prohibited by CLAUDE.md § Railway Token Rotation; this investigation produces no such file. |
| Human rotates with same token type & defaults, recurrence continues. | `web-research.md` Recommendations §1–§3 capture token-type hypothesis to investigate before another like-for-like rotation. Out-of-scope for this bead — flag via mail-to-mayor if confirmed. |
| Validator endpoint or query is the actual bug (not the token). | Out of scope here per Polecat Scope Discipline; would require its own bead. Hypothesis documented in `web-research.md` §2–§3. |
| Re-running the pipeline before the human rotates would fail again. | Step 3.2 (`railway-token-health.yml`) added as a pre-check before `gh run rerun`. |

---

## Validation

### Automated Checks

```bash
# After the human rotates RAILWAY_TOKEN and we re-run the pipeline:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25257755620 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli  # confirm "Validate Railway secrets" passes
```

### Manual Verification

1. Confirm `Validate Railway secrets` step is green on the re-run.
2. Confirm the deploy job (`Deploy staging image to Railway`) completes without
   credential errors.
3. Close #909 with the green run URL.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnose the failure on run 25257755620.
- Produce an investigation artifact and a GitHub comment that direct the human to
  the existing runbook.

**OUT OF SCOPE (do not touch):**
- Rotating `RAILWAY_TOKEN` (human-only per CLAUDE.md).
- Modifying `.github/workflows/staging-pipeline.yml` validator logic.
- Modifying `docs/RAILWAY_TOKEN_ROTATION_742.md` or `DEPLOYMENT_SECRETS.md`
  (runbook revisions belong in a separate bead — token-type hypotheses captured in
  `web-research.md` for that future bead).
- Replacing the static-secret model with OIDC / dynamic secrets (long-term
  mitigation; mail-to-mayor candidate).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T17:40:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/71a21444dc75f75167bd149ae06d3f82/investigation.md`
- **Companion research**: `artifacts/runs/71a21444dc75f75167bd149ae06d3f82/web-research.md`
