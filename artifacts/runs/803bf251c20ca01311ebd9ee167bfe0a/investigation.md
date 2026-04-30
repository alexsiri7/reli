# Investigation: Main CI red: Deploy to staging (11th `RAILWAY_TOKEN` expiration)

**Issue**: #773 (https://github.com/alexsiri7/reli/issues/773)
**Type**: BUG
**Investigated**: 2026-04-30T08:30:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Every staging+prod deploy is blocked at the pre-flight `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml:32-58`; no code change can ship until a human rotates the GitHub Actions secret, and #774 (prod deploy) was filed 4 seconds after #773 from the same root cause. |
| Complexity | LOW | No code change is permitted — the canonical runbook already exists at `docs/RAILWAY_TOKEN_ROTATION_742.md`; the fix is a single secret rotation in the Railway dashboard followed by `gh secret set`. |
| Confidence | HIGH | Run `25153294867` emits the exact string `RAILWAY_TOKEN is invalid or expired: Not Authorized` against SHA `0ca8284` (the merge of PR #770 closing the 9th-recurrence issue #769); this is the 11th identical recurrence of an invariant pattern the prior 10 investigations have already root-caused. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is expired — again. Pipeline run [`25153294867`](https://github.com/alexsiri7/reli/actions/runs/25153294867) (workflow `Staging → Production Pipeline`, SHA `0ca82844ba2f28c3858e1cdccc378f772b71740f` — the merge of investigation PR #770 that closed the 9th-recurrence issue #769) failed at the pre-flight `Validate Railway secrets` step at `2026-04-30T07:34:56Z` with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. The pickup cron filed this issue at `08:00:27Z` and filed sister issue #774 ("Prod deploy failed on main") 4 seconds later at `08:00:31Z`. Both will resolve on the same human rotation.

> **#773 is the post-merge sister of #769/#771.** PR #770 (closing #769) and PR #772 (closing #771) merged in the last hour with no token rotation between them; the workflow_run on PR #770's merge commit (`0ca8284`) is the failure being investigated here, and #774 is the same failure rebranded as a prod-deploy report.

---

## Analysis

### First-Principles: Is the primitive sound?

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Pre-flight Railway token validation | `.github/workflows/staging-pipeline.yml:32-58` | Yes | Calls `me{id}` GraphQL probe before deploy; correctly fails closed with a precise error string. The recurrence is **not** a defect in this primitive — it is doing its job. |
| Token issuance policy (human-side) | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Partial | The runbook documents the "select **No expiration**" requirement, but enforcement is operator discipline. Eleven recurrences indicate the runbook step is being skipped or the option is being mis-clicked at issuance. |
| Auto-pickup cron de-duplication | (out-of-repo: `pipeline-health-cron.sh`) | No | The cron filed #773 at `08:00:27Z` despite #769 (9th) and #771 (10th) already having open `archon:in-progress` investigation cycles in the same hour, and despite the canonical runbook being already linked. **Deferred follow-up #1 from PR #770/#772 is reaffirmed, not duplicated, by this investigation.** |

The pipeline primitive is sound. The recurrence is rooted in human-side token TTL policy plus a cron that does not gate on existing open investigations.

### Root Cause / Change Rationale

```
WHY: Pipeline run 25153294867 failed.
↓ BECAUSE: Job "Deploy to staging" failed at step "Validate Railway secrets".
  Evidence: 2026-04-30T07:34:56.5710012Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized

↓ BECAUSE: Railway's me{id} GraphQL probe returned "Not Authorized" for the
  bearer token in secrets.RAILWAY_TOKEN.
  Evidence: .github/workflows/staging-pipeline.yml:49-58 (the probe and
  failure-mode handler).

↓ BECAUSE: The token in secrets.RAILWAY_TOKEN reached its expiry and was not
  rotated when investigations #770 (9th) and #772 (10th) merged.
  Evidence: Run 25153294867's head SHA is 0ca82844 — exactly the merge commit
  of PR #770. The post-merge workflow_run failed at the same Validate step.

↓ ROOT CAUSE: Prior rotations issued Railway tokens with finite TTL instead of
  selecting "No expiration", producing recurrence every few weeks. No human
  has yet performed the rotation that resolves the current expiry window;
  closing #769 and #771 via docs-only PRs (which is the correct agent action)
  does not rotate the secret.
```

### Evidence Chain

WHY: Staging deploy red on every push to `main`.
↓ BECAUSE: `Validate Railway secrets` step exits 1 before any deploy command runs.
  Evidence: `.github/workflows/staging-pipeline.yml:53-57` — `if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then ... exit 1`

↓ BECAUSE: The `me{id}` probe response body contains `errors[0].message == "Not Authorized"`.
  Evidence: Run log line `2026-04-30T07:34:56.5710012Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ ROOT CAUSE: The Workspace token bound to `secrets.RAILWAY_TOKEN` is past its expiry.
  Evidence: 11 identical recurrences over the chain `#733 → #739 → #742 → #755 → #762 → #751 → #766 → #762(re-fire) → #769 → #771 → #773`, each on a different deploy SHA, each emitting the same string. No code edit between recurrences could have caused this.

### Lineage

Canonical chain (taken from each merged investigation commit's `(Nth RAILWAY_TOKEN expiration)` suffix) — **10 unique issues with #762 firing twice = 11 occurrences**:

| # | Issue | Investigation PR | State |
|---|-------|------------------|-------|
| 1 | #733 | (fix-only) | CLOSED |
| 2 | #739 | (fix-only) | CLOSED |
| 3 | #742 | #743 | CLOSED |
| 4 | #755 | #761 | CLOSED |
| 5 | #762 | #764 | CLOSED |
| 6 | #751 | #765 | CLOSED |
| 7 | #766 | #767 | CLOSED |
| 8 | #762 (re-fire) | #768 | CLOSED |
| 9 | #769 | #770 | CLOSED |
| 10 | #771 | #772 | CLOSED |
| 11 | #773 | this investigation | OPEN |

Sister-of-the-same-failure (filed by the cron 4s after #773): **#774** ("Prod deploy failed on main"). Same root cause, same human-rotation fix; investigation lives separately so the chain count is not double-counted here.

Related-but-separate (do **not** belong in the RAILWAY_TOKEN chain): #758 / #759 are an `HTTP 000000` lifespan/production-config defect (fixed by `93c8ce4`), not a token expiration.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/803bf251c20ca01311ebd9ee167bfe0a/investigation.md` | NEW | CREATE | This investigation artifact (committed in the docs-only PR that closes #773). |
| `.github/workflows/staging-pipeline.yml` | 32-58 | NO CHANGE | The `Validate Railway secrets` step is correctly failing closed; editing it would mask the real defect. |
| `docs/RAILWAY_TOKEN_ROTATION_742.md` | — | NO CHANGE | Runbook is current; the human action to rotate is documented there. |
| `.github/RAILWAY_TOKEN_ROTATION_*.md` | — | DO NOT CREATE | Per `CLAUDE.md` § "Railway Token Rotation", agents MUST NOT create such a file claiming rotation is done — that is a Category 1 error. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — pre-flight `Validate Railway secrets` step (where the failure surfaces). Reads `secrets.RAILWAY_TOKEN`, `RAILWAY_STAGING_SERVICE_ID`, `RAILWAY_STAGING_ENVIRONMENT_ID`, `RAILWAY_STAGING_URL`.
- `.github/workflows/staging-pipeline.yml:60-80` — `Deploy staging image to Railway` step (the consumer that would also fail without the token, but is gated by the validate step).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the canonical human runbook. Steps: mint Workspace token at https://railway.com/account/tokens with **No expiration**, then `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`, then re-run.
- (out-of-repo) `pipeline-health-cron.sh` — the auto-filer. Lacks an open-investigation gate, so it filed #773 and #774 within seconds of each other and on top of already-open sister investigations earlier in the hour. Strengthens deferred follow-up #1 from PR #770/#772.

### Git History

- **Run SHA**: `0ca82844ba2f28c3858e1cdccc378f772b71740f` — `docs: investigation for issue #769 (9th RAILWAY_TOKEN expiration) (#770)` (the merge of PR #770).
- **Implication**: This is the post-merge re-trigger of the staging-pipeline workflow on the just-merged docs-only investigation PR for the previous expiration. The merge added no code, only the artifact at `artifacts/runs/<hash>/investigation.md`. Therefore no commit on `main` could have caused this regression; the failure is the persistent unrotated-secret state, surfaced by the workflow_run that fires on every CI completion on `main`.

---

## Implementation Plan

This is an **investigation-only, no-PR-with-code incident by design**. Per `CLAUDE.md` § "Railway Token Rotation", agents cannot rotate the token. The plan is the human-action checklist plus the docs-only PR that records this recurrence.

### Step 1: Human rotates the Railway token

**Actor**: Human operator (railway.com login required)
**Action**:
1. Navigate to https://railway.com/account/tokens.
2. Mint a **Workspace** token with **No expiration**.
3. `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` (paste the new value).

**Why**: The `Validate Railway secrets` step is a deliberate fail-closed guard; only secret rotation can unblock it.

---

### Step 2: Human re-runs the failed staging-pipeline run

**Actor**: Human operator
**Action**: `gh run rerun 25153294867 --repo alexsiri7/reli --failed`

**Why**: Confirms the new token is accepted by Railway's `me{id}` probe and the deploy proceeds. Same rotation will also clear sister issue #774's failed run.

---

### Step 3: Agent opens docs-only PR closing #773

**Actor**: Agent (downstream `/implement-issue 773` cycle)
**Action**: Open a PR that:
- Adds `artifacts/runs/803bf251c20ca01311ebd9ee167bfe0a/investigation.md` (this file).
- Includes `Fixes #773` in the PR body.
- Touches **only** the artifact file — no `.py`/`.ts`/`.tsx`/`.yml`/`.yaml`/`.json` changes.
- Does **not** create any `.github/RAILWAY_TOKEN_ROTATION_*.md` file.

**Why**: Records the recurrence in the lineage chain and lets Archon transition #773 out of `archon:in-progress` while the human performs the rotation. Mirrors the proven pattern of PRs #770 and #772.

---

### Step N: Tests

**No automated tests apply.** The recurrence is in operator-side state (an external SaaS bearer token), not in code paths covered by `pytest` or `vitest`. Adding a test for "is the token alive?" would (a) duplicate the live `Validate Railway secrets` step we already have and (b) require the very secret that is broken.

---

## Patterns to Follow

**From the immediately prior investigations — mirror these exactly:**

```markdown
# SOURCE: artifacts/runs/6d344360044a88b0cc6e7662846b9610/investigation.md (PR #772, 10th expiration)
# Pattern: docs-only artifact, no workflow edits, no rotation-claim file,
# explicit lineage table, explicit "Not changed (deliberate)" callouts.
```

```markdown
# SOURCE: PR #772 body (the canonical PR template for this recurrence class)
# Pattern: "Required human action" section listing the 3-step rotation,
# "Validation" table marking automated checks N/A,
# Fixes #N footer.
```

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron files a 12th sister issue before #773 closes | Deferred follow-up #1 (gate the auto-filer on open investigations) is reaffirmed; this investigation does not implement the gate (out of scope per Polecat Scope Discipline). |
| Human rotates again with a finite TTL | Runbook explicitly says "No expiration"; if the operator misses the toggle, recurrence #12 is inevitable. Suggested follow-up: add a screenshot to `docs/RAILWAY_TOKEN_ROTATION_742.md` showing the toggle (deferred — not in this scope). |
| #774 (prod sister) and #773 close out of order | They resolve on the same rotation; whichever PR merges second can reference the other in its body without re-running the rotation. |
| Tempted to "fix" by editing `.github/workflows/staging-pipeline.yml:53-57` to soft-fail or warn | Do **not**. The fail-closed behavior is the feature, not the bug. Soft-failing would let a broken token deploy silently. |
| Tempted to create `.github/RAILWAY_TOKEN_ROTATION_773.md` claiming rotation is done | Forbidden — `CLAUDE.md` § "Railway Token Rotation" classifies this as a Category 1 error. |

---

## Validation

### Automated Checks

This is a docs-only artifact. Code-level checks are N/A:

```bash
# Confirm only the artifact is touched in the eventual PR:
git diff origin/main...HEAD -- '*.py' '*.ts' '*.tsx' '*.js' '*.jsx' '*.yml' '*.yaml' '*.json'
# Expected: empty
```

### Manual Verification (post-rotation)

```bash
# After human rotation, re-run the failed staging-pipeline run:
gh run rerun 25153294867 --repo alexsiri7/reli --failed

# Verify the Validate step now passes:
gh run view 25153294867 --repo alexsiri7/reli --log | grep -F "Validate Railway secrets" | head -5

# Verify the deploy completed (any subsequent run):
gh run list --repo alexsiri7/reli --workflow "Staging → Production Pipeline" --limit 3
```

Both #773 and sister #774 should close on the same rotation.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact at `artifacts/runs/803bf251c20ca01311ebd9ee167bfe0a/investigation.md`.
- The GitHub comment on issue #773 summarizing the investigation.
- The eventual docs-only PR (opened by `/implement-issue 773`) that adds this artifact and closes #773 with `Fixes #773`.

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — the validate step is correct as-is.
- Any new `.github/RAILWAY_TOKEN_ROTATION_*.md` rotation-claim file (Category 1 error).
- The auto-filer cron de-duplication fix (deferred follow-up #1, owned separately by mayor's queue — Polecat Scope Discipline says: do not fix out-of-scope issues from this bead).
- Sister issue #774 — same root cause, same fix, but owned by a separate `archon:in-progress` cycle.
- A new `web-research.md` companion — PR #768's `artifacts/runs/0c44823de5470e5c9687e943e83f9414/web-research.md` is still current; root cause and remediation are unchanged across the chain.

---

## Suggested Follow-Up (deferred — do **not** implement in this PR)

1. **Auto-filer open-investigation gate.** `pipeline-health-cron.sh` should not file a new issue while an `archon:in-progress` issue with the same matched-failure-class is open. This was first deferred in PR #770 and re-deferred in PR #772; #773+#774 firing within 4 seconds of each other on top of already-closed-but-just-merged #769/#771 strengthens the case again. Owner: mayor's queue.
2. **Runbook screenshot.** Add an annotated screenshot of the Railway "Create Token" dialog to `docs/RAILWAY_TOKEN_ROTATION_742.md` so the "No expiration" toggle cannot be missed. Owner: human (only a human can capture the railway.com UI).
3. **Multi-token + automatic rotation.** Long-term: switch to a service that supports programmatic rotation (Railway projects with team-level OIDC, or a sidecar that mints short-lived tokens). Owner: future RFC.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-30T08:30:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/803bf251c20ca01311ebd9ee167bfe0a/investigation.md`
- **Issue**: https://github.com/alexsiri7/reli/issues/773
- **Failed run**: https://github.com/alexsiri7/reli/actions/runs/25153294867
- **Sister (out-of-scope) issue**: https://github.com/alexsiri7/reli/issues/774
- **Canonical runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md`
