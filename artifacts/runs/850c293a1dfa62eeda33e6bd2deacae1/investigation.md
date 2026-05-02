# Investigation: Prod deploy failed on main (#880)

**Issue**: #880 (https://github.com/alexsiri7/reli/issues/880)
**Type**: BUG (infrastructure / secrets)
**Investigated**: 2026-05-02T07:40:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | CRITICAL | Prod deploy pipeline is fully blocked at the `Validate Railway secrets` gate — no code can ship to staging or production until the token is rotated, and there is no in-repo workaround. |
| Complexity | LOW | Resolution is a single GitHub secret update by a human with Railway dashboard access; zero code changes are required in this repository. |
| Confidence | HIGH | The deploy log explicitly returns `RAILWAY_TOKEN is invalid or expired: Not Authorized` from Railway's `{me{id}}` validation query — identical signature to issues #864/#866/#868/#870/#871/#874/#876/#878, all of which were resolved by token rotation. |

---

## Problem Statement

The `Deploy to staging` job on workflow run [25246979867](https://github.com/alexsiri7/reli/actions/runs/25246979867) failed at the `Validate Railway secrets` step because the `RAILWAY_TOKEN` GitHub Actions secret is expired/invalid. Railway's GraphQL `{me{id}}` probe returns `Not Authorized`, so no deploy can proceed. This is the **50th** occurrence of this exact failure mode (10th today, ~30 minutes after #878) and the established remediation is a human-only Railway token rotation.

---

## Analysis

### Root Cause

The `RAILWAY_TOKEN` secret stored in GitHub Actions is rejected by Railway's API. The validation step in `.github/workflows/staging-pipeline.yml` performs an authenticated GraphQL request and exits non-zero when the response does not contain `data.me.id`.

### Evidence Chain

WHY: Prod deploy run 25246979867 failed.
↓ BECAUSE: The `Validate Railway secrets` step exited with code 1.
  Evidence: deploy log line `2026-05-02T07:34:52.2871639Z ##[error]Process completed with exit code 1.`

↓ BECAUSE: Railway's GraphQL `{me{id}}` query returned `Not Authorized` instead of a user id.
  Evidence: deploy log line `2026-05-02T07:34:52.2857078Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret has expired (or was revoked) and must be rotated by a human with Railway dashboard access.
  Evidence: `docs/RAILWAY_TOKEN_ROTATION_742.md:5-12` documents this exact failure signature and notes that prior rotations (#733, #739, plus 40+ subsequent recurrences) all resolved via token rotation; recent commits (`554eb03`, `5fcc23b`, `715992e`, `bb5dfa7`, `0de37f2`) record the 46th–49th occurrences.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| _(none — repo code is correct)_ | — | NONE | The validator at `.github/workflows/staging-pipeline.yml:32-58` is working as designed; it correctly detects the bad token. The fix lives outside the repository, in GitHub Actions secrets and the Railway dashboard. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step performs the `{me{id}}` probe that detects this failure.
- GitHub Actions secret `RAILWAY_TOKEN` (org/repo level) — the value that needs rotation.
- Railway dashboard at https://railway.com/account/tokens — where the new token must be minted.

### Git History

- **Pattern recognized in repo**: `docs/RAILWAY_TOKEN_ROTATION_742.md` (canonical runbook, originally for issue #742).
- **Recent recurrences** (`git log --oneline -5`):
  - `554eb03` docs: investigation for issue #878 (49th expiration, 9th today)
  - `5fcc23b` docs: investigation for issue #876 (48th, 8th today)
  - `715992e` docs: investigation for issue #874 (47th, 7th today)
  - `bb5dfa7` docs: investigation for issue #870 (46th, 6th today)
  - `0de37f2` docs: investigation for issue #871 (also 46th, 6th today)
- **Implication**: This is a high-frequency recurring operational problem. Issue #878's deploy ran at 07:04:31Z; this one (#880) ran at 07:34:53Z — only ~30 minutes later. At 10 occurrences in a single calendar day (2026-05-02), the rotated token's effective TTL is clearly far below the runbook's "No expiration" target. Either (a) the human is silently being given a short-TTL token by Railway's UI, (b) Railway has removed the "No expiration" option, or (c) an external process is revoking the token. The next rotator should screenshot the token-creation dialog and confirm the "No expiration" option still exists.

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
2. Create a new token named `github-actions-permanent` with **Expiration: No expiration**. If the option is missing or has been silently downgraded by Railway's UI, screenshot the dialog and report on the issue thread before creating any short-TTL token (this is the suspected root cause of the 10-per-day recurrence rate).
3. Update the GitHub secret:
   ```bash
   gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
   # paste the new token
   ```
4. Re-run the failed deploy:
   ```bash
   gh run rerun 25246979867 --repo alexsiri7/reli --failed
   ```
   Fallback (if the run is stale):
   ```bash
   gh run list --repo alexsiri7/reli --status failure --limit 1 \
     --json databaseId --jq '.[0].databaseId' \
     | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
   ```

### Step 2: Confirm green deploy and close the issue

Once the next staging deploy passes, close issue #880.

---

## Patterns to Follow

**From `CLAUDE.md` (Railway Token Rotation):**

> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

This investigation explicitly avoids creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` artifact and avoids modifying any workflow or secret-related code. The only deliverables are this investigation note plus a GitHub comment routing the human operator to the runbook.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a "rotation complete" doc | Forbidden by CLAUDE.md; this investigation explicitly does not. |
| Human picks a short-TTL token again (suspected root cause of recurrence) | Runbook requires **"No expiration"** — comment calls this out and recommends screenshotting the token-creation dialog. |
| Multiple duplicate issues (this is the 50th, 10th today) | Comment notes the recurrence count and frequency so the human can prioritize a longer-term fix (e.g., service account, monitoring, alerting on token age). |
| Re-run hits same expired token | Step 1 must complete (secret update) before the re-run in Step 2. |
| Sub-hourly recurrence (~30 min between #878 and #880) suggests TTL is being silently capped or token is revoked externally | Out of scope for this bead; flag to mayor as a separate investigation if the pattern continues past the next rotation. |

---

## Validation

### Automated Checks

None for this repo — the failure is in CI infrastructure, not code.

### Manual Verification

1. After the human completes Step 1, re-run workflow 25246979867 (or trigger a fresh deploy).
2. Confirm the `Validate Railway secrets` step now succeeds (response contains `data.me.id`).
3. Confirm the full `Deploy to staging` pipeline completes green.
4. Close issue #880.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the deploy failure on run 25246979867.
- Producing this investigation artifact.
- Posting a GitHub comment that routes the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**OUT OF SCOPE (do not touch):**
- Rotating the Railway token (human-only — agent has no Railway dashboard credentials).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` document (explicitly forbidden by CLAUDE.md).
- Modifying `.github/workflows/staging-pipeline.yml` — the validator is working correctly.
- Any longer-term remediation (token monitoring, service account migration, alerting on token age, switching to Railway CLI + project token) — would belong in a separate issue.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T07:40:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/850c293a1dfa62eeda33e6bd2deacae1/investigation.md`
