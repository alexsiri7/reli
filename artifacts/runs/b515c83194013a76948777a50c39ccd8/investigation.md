# Investigation: Prod deploy failed on main (#876)

**Issue**: #876 (https://github.com/alexsiri7/reli/issues/876)
**Type**: BUG (infrastructure / secrets)
**Investigated**: 2026-05-02T06:40:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | Prod deploy pipeline is fully blocked at the very first step; nothing can ship to staging or production until the GitHub `RAILWAY_TOKEN` secret is rotated, and there is no in-repo workaround. |
| Complexity | LOW | Resolution is a single GitHub secret update by a human with Railway dashboard access; zero code changes are required in this repo (the validator is already correctly detecting and reporting the bad token). |
| Confidence | HIGH | The CI log explicitly returns `RAILWAY_TOKEN is invalid or expired: Not Authorized` from Railway's `{me{id}}` GraphQL probe — byte-identical signature to issues #860/#862/#864/#866/#868/#870/#871/#874, all resolved by token rotation. |

---

## Problem Statement

The `Deploy to staging` job on workflow run [25245920463](https://github.com/alexsiri7/reli/actions/runs/25245920463) failed at the `Validate Railway secrets` step because the `RAILWAY_TOKEN` GitHub Actions secret is expired/invalid. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, so no deploy job (`Deploy staging image to Railway`, `Wait for staging health`, `Staging E2E smoke tests`, `Deploy to production`) can proceed — the rest of the pipeline is `skipped`. This is the **48th** occurrence of this exact failure mode (**8th today**, 2026-05-02), and the established remediation is a human-only Railway token rotation.

---

## Analysis

### Root Cause

The `RAILWAY_TOKEN` secret stored in GitHub Actions is rejected by Railway's API. The validation step in `.github/workflows/staging-pipeline.yml` performs an authenticated GraphQL request (`POST https://backboard.railway.app/graphql/v2` with body `{me{id}}`) and exits non-zero when the response does not contain `data.me.id`.

### Evidence Chain

WHY: Prod deploy run 25245920463 failed (`conclusion: failure`).
↓ BECAUSE: The `Validate Railway secrets` step exited with code 1 and downstream jobs (`Staging E2E smoke tests`, `Deploy to production`) were skipped.
  Evidence: deploy log line `2026-05-02T06:34:55.3868816Z ##[error]Process completed with exit code 1.`

↓ BECAUSE: Railway's GraphQL `{me{id}}` query returned `Not Authorized` instead of a user id.
  Evidence: deploy log line `2026-05-02T06:34:55.3858733Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret has expired (or was revoked) and must be rotated by a human with Railway dashboard access.
  Evidence: `docs/RAILWAY_TOKEN_ROTATION_742.md:5-12` documents this exact failure signature and notes that prior rotations (#733, #739, plus 40+ subsequent recurrences) all resolved via token rotation; recent commits (`715992e`, `bb5dfa7`, `0de37f2`, `79cd02a`, `7a22aaa`, `b5ad0e6`) record the 43rd–47th occurrences.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| _(none — repo code is correct)_ | — | NONE | The validator in `.github/workflows/staging-pipeline.yml` is working as designed; it correctly detects the bad token and fails fast before any deploy mutations are sent to Railway. The fix lives outside the repository, in GitHub Actions secrets and the Railway dashboard. |

### Integration Points

- `.github/workflows/staging-pipeline.yml` — `Validate Railway secrets` step performs the `{me{id}}` probe that detects this failure.
- GitHub Actions secret `RAILWAY_TOKEN` (repo-level) — the value that needs rotation.
- Railway dashboard at https://railway.com/account/tokens — where the new token must be minted.

### Git History

- **Pattern recognized in repo**: `docs/RAILWAY_TOKEN_ROTATION_742.md` (canonical runbook, originally for issue #742).
- **Recent recurrences** (`git log --oneline -5`):
  - `715992e` docs: investigation for issue #874 (47th expiration, 7th today)
  - `bb5dfa7` docs: investigation for issue #870 (46th expiration, 6th today)
  - `0de37f2` docs: investigation for issue #871 (46th expiration, 6th today)
  - `79cd02a` docs: investigation for issue #868 (45th, 5th today)
  - `7a22aaa` docs: investigation for issue #866 (44th, 4th today)
- **Implication**: This is a recurring operational problem — eight failures in a single calendar day strongly suggests the rotated token still has a finite TTL (likely the 7-day default). The runbook explicitly instructs the human to select **"No expiration"** when creating the replacement token. With this many same-day recurrences, the rotator should hard-confirm that step on this rotation, and a longer-term remediation (service-account migration, monitoring on token age, alerting before expiry) should be filed as a separate issue.

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
   gh run rerun 25245920463 --repo alexsiri7/reli --failed
   ```
   Fallback (if the run is stale):
   ```bash
   gh run list --repo alexsiri7/reli --status failure --limit 1 \
     --json databaseId --jq '.[0].databaseId' \
     | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
   ```

### Step 2: Confirm green deploy and close the issue

Once the next staging deploy passes, close issue #876.

---

## Patterns to Follow

**From `CLAUDE.md` (Railway Token Rotation):**

> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

This investigation explicitly avoids creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` artifact and avoids modifying any workflow or secret-related code. The only deliverables are this investigation note plus a GitHub comment routing the human to the runbook.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a "rotation complete" doc | Forbidden by CLAUDE.md; this investigation explicitly does not. |
| Human picks a short-TTL token again (likely root cause of repeated daily recurrences) | Runbook requires **"No expiration"** — call this out emphatically in the comment, since 8 same-day failures imply the last rotation used a default TTL. |
| Multiple duplicate issues (this is the 48th, 8th today) | Comment notes the recurrence count so the human can consider a longer-term fix (service account, monitoring, alerting on token age) as a separate tracking issue. |
| Re-run hits same expired token | Step 1 (secret update) must complete before the re-run in Step 2. |

---

## Validation

### Automated Checks

None for this repo — the failure is in CI infrastructure, not code.

### Manual Verification

1. After the human completes Step 1, re-run workflow 25245920463 (or trigger a fresh deploy).
2. Confirm the `Validate Railway secrets` step now succeeds (response contains `data.me.id`).
3. Confirm the full `Deploy to staging` pipeline completes green and downstream `Staging E2E smoke tests` and `Deploy to production` run.
4. Close issue #876.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the deploy failure on run 25245920463.
- Producing this investigation artifact.
- Posting a GitHub comment that routes the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**OUT OF SCOPE (do not touch):**
- Rotating the Railway token (human-only — agent has no Railway dashboard credentials).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` document (explicitly forbidden by CLAUDE.md).
- Modifying `.github/workflows/staging-pipeline.yml` — the validator is working correctly.
- Any longer-term remediation (token monitoring, service-account migration, alerting on token age) — would belong in a separate issue.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T06:40:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/b515c83194013a76948777a50c39ccd8/investigation.md`
