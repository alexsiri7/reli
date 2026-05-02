# Investigation: Prod deploy failed on main (#912)

**Issue**: #912 (https://github.com/alexsiri7/reli/issues/912)
**Type**: BUG (operational — external credential rejection)
**Investigated**: 2026-05-02T19:05:00Z
**Workflow run**: dff05fb47bc6d33f0d9282dfe5d882c0
**CI run**: 25258939832 (https://github.com/alexsiri7/reli/actions/runs/25258939832)
**Companion issue**: #911 (Main CI red: Deploy to staging — same run, same SHA, same root cause)

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy is gated by the staging deploy job, which fails at the Railway-secret validator on every main push; no in-repo workaround exists, but only the deploy chain is blocked — non-deploy CI continues to run. |
| Complexity | LOW | Zero code changes warranted on this bead; the remediation is a human-only Railway dashboard rotation followed by `gh secret set RAILWAY_TOKEN`. The validator at `.github/workflows/staging-pipeline.yml:32-58` and `:149+` is functioning as designed. |
| Confidence | HIGH | The failure message, endpoint, and step are byte-for-byte identical to the prior 62 incidents (most recently #909, ~30 minutes ago, PR #910). Same SHA `fdf6393` filed both #911 and #912 from the same run 25258939832. |

---

## Problem Statement

The "Validate Railway secrets" step in `.github/workflows/staging-pipeline.yml` (job
"Deploy to staging") failed on run 25258939832 because Railway's auth backend rejected
the token currently held in `secrets.RAILWAY_TOKEN`. This is the **63rd** recurrence of
the same failure mode and the **23rd today**. Issue #912 (prod deploy gate) and #911
(main CI red) were both auto-filed from the same run by `pipeline-health-cron.sh`.

Chain: `#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #903/#904 → #907 → #909 → #911/#912`.

---

## Analysis

### Root Cause / Change Rationale

The validator posts a `query { me { id } }` GraphQL request to
`https://backboard.railway.app/graphql/v2` with `Authorization: Bearer $RAILWAY_TOKEN`.
Railway returned `{"errors":[{"message":"Not Authorized"}]}`, which the validator
correctly surfaces as `RAILWAY_TOKEN is invalid or expired: Not Authorized`. The
validator is correct; the token itself is what is failing.

Per `CLAUDE.md` § Railway Token Rotation, the token lives in GitHub Actions secrets and
requires human access to railway.com; agents cannot rotate it. The fix is therefore
out of code-change scope for this bead. Creating a `.github/RAILWAY_TOKEN_ROTATION_*.md`
file claiming rotation has been done is an explicitly-prohibited Category 1 error.

### Evidence Chain

WHY: Why did "Prod deploy" (the production stage) fail on run 25258939832?
↓ BECAUSE: The upstream "Deploy to staging" job exited non-zero, gating prod.
  Evidence: GH issue body — `Failed jobs: Deploy to staging`.

↓ BECAUSE: Within "Deploy to staging", the "Validate Railway secrets" step exited 1.
  Evidence: `##[error]Process completed with exit code 1.` at 2026-05-02T18:34:31Z.

↓ BECAUSE: The validator's `me{id}` probe to Railway returned `Not Authorized`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at
  2026-05-02T18:34:31Z (raw log).

↓ ROOT CAUSE: The token currently stored in `secrets.RAILWAY_TOKEN` is rejected by
  Railway's auth backend. Either it has expired, been revoked, or is the wrong token
  type for the validator's query (Account/Personal token required for `me{id}` — see
  prior chain artifact `artifacts/runs/71a21444dc75f75167bd149ae06d3f82/web-research.md` §2).
  Evidence: `.github/workflows/staging-pipeline.yml:32-58` — validator code is
  unchanged across all 63 incidents.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | This bead requires no source-tree changes. The remediation is a GitHub Actions secret update performed by a human via the Railway dashboard + `gh secret set`. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging validator that surfaced the
  failure; behaves correctly. (Prod validator at `:149+` is structurally identical.)
- `secrets.RAILWAY_TOKEN` (GitHub Actions secret) — the credential being rejected.
  Rotation requires human access to https://railway.com.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the existing human runbook.
- `.github/workflows/railway-token-health.yml` — out-of-band health check the human
  can trigger after rotation to verify the new token before re-running #912.
- `pipeline-health-cron.sh` — auto-filer that produced both #911 and #912 from the
  same run; not in this repo, but is the source of duplicate-issue pairing.

### Git History

- **Last validator change**: not modified in any of the 63 incidents — this is
  consistently a credential-rejection issue, not a regression in the validator.
- **Prior incident chain on the same root cause**: #878, #880, #882, #884, #886,
  #888, #891, #894, #896, #898, #901, #903, #904, #907, #909 (immediate predecessor) —
  see PRs #879/#881/#883/#885/#887/#889/#892/#895/#897/#899/#902/#905/#906/#908/#910
  for the same investigation pattern.
- **SHA pairing**: `fdf6393` is the head commit at the time of run 25258939832 —
  it is the previous investigation merge (#910 for #909). The current failure is not
  caused by `fdf6393`; it is the *next* deploy gate after that merge that hit the
  same expired token.
- **Implication**: 63 occurrences and 23-in-one-day cadence at this point indicate
  the *recurrence rate itself* is the underlying problem (long-term). See the prior
  chain's `web-research.md` §1–§3 for the token-type-vs-query-type hypothesis that
  may explain why like-for-like rotations keep producing the same error.

---

## Implementation Plan

This bead does not modify the source tree. Per `CLAUDE.md` § Railway Token Rotation,
the only valid agent output here is (a) this investigation artifact and (b) a GitHub
comment directing the human operator to the runbook. Creating any
`.github/RAILWAY_TOKEN_ROTATION_912.md` file claiming rotation is done would be a
Category 1 error and is explicitly forbidden.

### Step 1: Document the failure (this artifact)

**File**: `artifacts/runs/dff05fb47bc6d33f0d9282dfe5d882c0/investigation.md`
**Action**: CREATE (this file)

### Step 2: Post investigation comment on issue #912

**Action**: `gh issue comment 912 --body @<formatted_comment>` summarizing this
artifact and pointing the human at the runbook. Cross-reference #911 (the
companion main-CI-red issue auto-filed from the same run).

### Step 3: Human follow-up (out of agent scope)

1. Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`.
   - Before another like-for-like rotation, consider verifying whether the secret is
     an Account/Personal token or a Project Token. The validator's `me{id}` probe
     requires an Account token; a Project Token returns the same `Not Authorized`
     message even when valid. (See chain artifact #909/web-research.md §2.)
2. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` — verify the
   replacement authenticates before re-running the failed pipeline.
3. `gh run rerun 25258939832 --repo alexsiri7/reli --failed` — re-trigger the
   "Deploy to staging" job (which gates prod).
4. Confirm green run; close #911 and #912 together.

---

## Patterns to Follow

This investigation follows the exact pattern established by #909's investigation
(the immediate predecessor, PR #910). Diff vs that prior pattern:

- Issue number: #909 → #912 (with companion #911)
- CI run ID: 25257755620 → 25258939832
- Failure timestamp: 2026-05-02T17:34:50Z → 2026-05-02T18:34:31Z
- Incident count: "62nd / 22nd today" → "63rd / 23rd today"
- Predecessor chain extended by `#909`
- All other content and structure unchanged

```bash
# Identical validator code that fired the failure (unchanged across 63 incidents)
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
| Agent creates `.github/RAILWAY_TOKEN_ROTATION_912.md` falsely claiming the token was rotated. | Explicitly prohibited by CLAUDE.md § Railway Token Rotation; this investigation produces no such file. |
| Human rotates with same token type & defaults, recurrence continues. | Token-type hypothesis already documented in prior chain (`#909`/web-research.md §1–§3). Out-of-scope for this bead — flag via mail-to-mayor if confirmed after the next rotation. |
| Validator endpoint or query is the actual bug (not the token). | Out of scope here per Polecat Scope Discipline; would require its own bead. Hypothesis documented in prior chain artifact. |
| Re-running the pipeline before the human rotates would fail again. | Step 3.2 (`railway-token-health.yml`) added as a pre-check before `gh run rerun`. |
| #911 (main CI red) and #912 (prod deploy) are duplicates from the same run. | Both should be closed together once the rotation lands; cross-reference in the GitHub comment. |

---

## Validation

### Automated Checks

```bash
# After the human rotates RAILWAY_TOKEN and we re-run the pipeline:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25258939832 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli  # confirm "Validate Railway secrets" passes
```

### Manual Verification

1. Confirm `Validate Railway secrets` step is green on the re-run.
2. Confirm the deploy job (`Deploy staging image to Railway`) completes without
   credential errors.
3. Confirm the prod stage that #912 reports against also completes.
4. Close #911 and #912 with the green run URL.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnose the failure on run 25258939832.
- Produce an investigation artifact and a GitHub comment that direct the human to
  the existing runbook.
- Cross-reference the companion issue #911 from the same auto-filer run.

**OUT OF SCOPE (do not touch):**
- Rotating `RAILWAY_TOKEN` (human-only per CLAUDE.md).
- Modifying `.github/workflows/staging-pipeline.yml` validator logic.
- Modifying `docs/RAILWAY_TOKEN_ROTATION_742.md` or `DEPLOYMENT_SECRETS.md`
  (runbook revisions belong in a separate bead — token-type hypotheses captured in
  the prior chain's `web-research.md` for that future bead).
- Replacing the static-secret model with OIDC / dynamic secrets (long-term
  mitigation; mail-to-mayor candidate, not this bead).
- Fixing `pipeline-health-cron.sh` to dedupe staging-vs-prod failures from the same
  run into a single issue (out-of-repo; mail-to-mayor candidate).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T19:05:00Z
- **Artifact**: `artifacts/runs/dff05fb47bc6d33f0d9282dfe5d882c0/investigation.md`
- **Companion research**: `artifacts/runs/71a21444dc75f75167bd149ae06d3f82/web-research.md` (prior chain)
