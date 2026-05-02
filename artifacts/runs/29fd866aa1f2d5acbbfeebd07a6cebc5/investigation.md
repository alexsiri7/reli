# Investigation: Prod deploy failed on main (#874)

**Issue**: #874 (https://github.com/alexsiri7/reli/issues/874)
**Type**: BUG (infrastructure / secrets)
**Investigated**: 2026-05-02T06:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | Prod deploy pipeline is fully blocked — no code can ship to staging until the token is rotated, and there is no in-repo workaround. |
| Complexity | LOW | Resolution is a single GitHub secret update by a human with Railway dashboard access; zero code changes are required in this repo. |
| Confidence | HIGH | The CI log explicitly returns `RAILWAY_TOKEN is invalid or expired: Not Authorized` from Railway's `{me{id}}` validation query — identical signature to issues #864/#866/#868/#870/#871, all resolved by token rotation. |

---

## Problem Statement

The `Deploy to staging` job on workflow run [25245399740](https://github.com/alexsiri7/reli/actions/runs/25245399740) failed at the `Validate Railway secrets` step because the `RAILWAY_TOKEN` GitHub Actions secret is expired/invalid. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, so no deploy can proceed. This is the **47th** occurrence of this exact failure mode (6th today) and the established remediation is a human-only Railway token rotation.

---

## Analysis

### Root Cause

The `RAILWAY_TOKEN` secret stored in GitHub Actions is rejected by Railway's API. The validation step in `.github/workflows/staging-pipeline.yml` performs an authenticated GraphQL request and exits non-zero when the response does not contain `data.me.id`.

### Evidence Chain

WHY: Prod deploy run 25245399740 failed.
↓ BECAUSE: The `Validate Railway secrets` step exited with code 1.
  Evidence: deploy log line `2026-05-02T06:04:26.9693198Z ##[error]Process completed with exit code 1.`

↓ BECAUSE: Railway's GraphQL `{me{id}}` query returned `Not Authorized` instead of a user id.
  Evidence: deploy log line `2026-05-02T06:04:26.9676771Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret has expired (or was revoked) and must be rotated by a human with Railway dashboard access.
  Evidence: `docs/RAILWAY_TOKEN_ROTATION_742.md:5-12` documents this exact failure signature and notes that prior rotations (#733, #739, plus 40+ subsequent recurrences) all resolved via token rotation; recent commits (`bb5dfa7`, `0de37f2`, `79cd02a`, `7a22aaa`, `b5ad0e6`) record the 43rd–46th occurrences.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| _(none — repo code is correct)_ | — | NONE | The validator in `.github/workflows/staging-pipeline.yml` is working as designed; it correctly detects the bad token. The fix lives outside the repository, in GitHub Actions secrets and the Railway dashboard. |

### Integration Points

- `.github/workflows/staging-pipeline.yml` — `Validate Railway secrets` step performs the `{me{id}}` probe that detects this failure.
- GitHub Actions secret `RAILWAY_TOKEN` (org/repo level) — the value that needs rotation.
- Railway dashboard at https://railway.com/account/tokens — where the new token must be minted.

### Git History

- **Pattern recognized in repo**: `docs/RAILWAY_TOKEN_ROTATION_742.md` (canonical runbook, originally for issue #742).
- **Recent recurrences** (`git log --oneline -5`):
  - `bb5dfa7` docs: investigation for issue #870 (46th expiration, 6th today)
  - `0de37f2` docs: investigation for issue #871 (also #46, 6th today)
  - `79cd02a` docs: investigation for issue #868 (45th, 5th today)
  - `7a22aaa` docs: investigation for issue #866 (44th, 4th today)
  - `b5ad0e6` docs: investigation for issue #864 (43rd)
- **Implication**: This is a recurring operational problem — likely the rotated token still has a finite TTL. The runbook explicitly instructs the human to select **"No expiration"** when creating the replacement token. If we are still seeing daily recurrences, the rotator should double-check that step.

---

## Implementation Plan

**No code changes are required in this repository.** Per `CLAUDE.md` "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
>
> When CI fails with `RAILWAY_TOKEN is invalid or expired`:
> 1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> 2. File a GitHub issue or send mail to mayor with the error details.
> 3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.

### Step 1: Human rotates the token (out-of-band)

Owner: a human with Railway dashboard access.

1. Open https://railway.com/account/tokens.
2. Create a new token named `github-actions-permanent` with **Expiration: No expiration**.
3. Update the GitHub secret:
   ```bash
   gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
   # paste the new token
   ```
4. Re-run the failed deploy:
   ```bash
   gh run rerun 25245399740 --repo alexsiri7/reli --failed
   ```
   Fallback (if the run is stale):
   ```bash
   gh run list --repo alexsiri7/reli --status failure --limit 1 \
     --json databaseId --jq '.[0].databaseId' \
     | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
   ```

### Step 2: Confirm green deploy and close the issue

Once the next staging deploy passes, close issue #874.

---

## Patterns to Follow

**From `CLAUDE.md` (Railway Token Rotation):**

> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

This investigation explicitly avoids creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` artifact and avoids modifying any workflow or secret-related code. The only deliverable is this investigation note plus a GitHub comment routing the human to the runbook.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a "rotation complete" doc | Forbidden by CLAUDE.md; this investigation explicitly does not. |
| Human picks a short-TTL token again (root cause of recurrence) | Runbook requires **"No expiration"** — call this out in the comment. |
| Multiple duplicate issues (this is the 47th) | Comment notes the recurrence count so the human can consider a longer-term fix (e.g., service account, monitoring, alerting on token age). |
| Re-run hits same expired token | Step 1 must complete (secret update) before the re-run in Step 2. |

---

## Validation

### Automated Checks

None for this repo — the failure is in CI infrastructure, not code.

### Manual Verification

1. After the human completes Step 1, re-run workflow 25245399740 (or trigger a fresh deploy).
2. Confirm the `Validate Railway secrets` step now succeeds (response contains `data.me.id`).
3. Confirm the full `Deploy to staging` pipeline completes green.
4. Close issue #874.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the deploy failure on run 25245399740.
- Producing this investigation artifact.
- Posting a GitHub comment that routes the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**OUT OF SCOPE (do not touch):**
- Rotating the Railway token (human-only — agent has no Railway dashboard credentials).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` document (explicitly forbidden by CLAUDE.md).
- Modifying `.github/workflows/staging-pipeline.yml` — the validator is working correctly.
- Any longer-term remediation (token monitoring, service account migration, alerting on token age) — would belong in a separate issue.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T06:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/29fd866aa1f2d5acbbfeebd07a6cebc5/investigation.md`
