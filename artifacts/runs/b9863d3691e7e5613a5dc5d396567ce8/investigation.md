# Investigation: Main CI red: Deploy to staging

**Issue**: #804 (https://github.com/alexsiri7/reli/issues/804)
**Type**: BUG
**Investigated**: 2026-04-30T18:50:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging deploy job fails on every main push, blocking the staging→prod promotion pipeline; no production data is at risk and a clear human-only workaround (rotate token) exists. |
| Complexity | LOW | Resolution is a one-step secret rotation in GitHub Actions; no code change is required and the runbook is already written. |
| Confidence | HIGH | The job log explicitly says `RAILWAY_TOKEN is invalid or expired: Not Authorized`, the validation step that produced it is deliberately designed to surface exactly this case, and the same failure has now recurred 21 times. |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` fails at the `Validate Railway secrets` step because the `RAILWAY_TOKEN` GitHub Actions secret has expired again. Railway's GraphQL API rejects the token with `Not Authorized`. **Agents cannot fix this** — rotation requires a human with railway.com dashboard access.

---

## Analysis

### Root Cause / Change Rationale

This is the 21st recurrence of the same `RAILWAY_TOKEN` expiration (prior: #742, #747, #752, #762, #769, #774, #777, #783, #793, #794, #798, #801, and others). The validate step is working as designed; it is correctly surfacing an expired credential.

### Evidence Chain

WHY: `Deploy to staging` job exits 1.
↓ BECAUSE: The `Validate Railway secrets` step fails.
  Evidence: run log line `2026-04-30T18:35:01.0910395Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: A `{me{id}}` probe to `https://backboard.railway.app/graphql/v2` returns no `data.me.id`.
  Evidence: `.github/workflows/staging-pipeline.yml:49-58` — the validate step calls Railway's GraphQL `me` query and exits 1 when the response lacks `.data.me.id`.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret is expired. Rotation requires a human with railway.com dashboard access; no agent can perform it.
  Evidence: `CLAUDE.md` — "Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com."

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| GitHub Actions secret `RAILWAY_TOKEN` | n/a | ROTATE (human-only) | Create new Railway API token with **"No expiration"** and update the secret. |

No source files require modification. The validate step at `.github/workflows/staging-pipeline.yml:32-58` (and the prod equivalent at `:149-173`) is functioning correctly.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — staging validate step that emitted the failure.
- `.github/workflows/staging-pipeline.yml:60-88` — staging deploy step that uses the same token.
- `.github/workflows/staging-pipeline.yml:149-173` — prod validate step (will fail next prod deploy with the same error).
- `.github/workflows/railway-token-health.yml` — periodic health check that monitors the token.

### Git History

- The validate step was introduced by commit `3dfb995` ("fix: add Railway API token auth check to deploy pre-flight (#738)") and refined in `0040535` ("fix: use curl -sf consistently in Railway token validate steps (#744)"). Behavior is correct.
- **Implication**: This is not a regression. The CI is doing its job; the credential is what expired.

---

## Implementation Plan

> ⚠️ **No code change. This issue requires a human to rotate the Railway API token.**
> Per `CLAUDE.md > Railway Token Rotation`, agents must NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. Doing so is a Category 1 error.

### Step 1 (HUMAN): Create a new Railway token with no expiration

1. Sign in at https://railway.com/account/tokens.
2. Create a token named `github-actions-permanent`.
3. **Set expiration to "No expiration"** — do not accept the default TTL. Several past rotations used short-lived defaults, which is why this keeps recurring.

### Step 2 (HUMAN): Update the GitHub Actions secret

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# paste the new token when prompted
```

### Step 3 (HUMAN): Re-run the failed CI

```bash
gh run rerun 25182725669 --repo alexsiri7/reli --failed

# Fallback if the run is stale:
gh run list --repo alexsiri7/reli --status failure --limit 1 \
  --json databaseId --jq '.[0].databaseId' \
  | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
```

### Step 4 (HUMAN): Close issue #804 once CI is green

The full runbook lives at `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Patterns to Follow

Mirror prior recurrence handling — file an investigation that points the human at the runbook, do not fabricate a rotation receipt:

```
SOURCE: recent commits on main
0275146 docs: investigation for issue #800 (20th RAILWAY_TOKEN expiration) (#803)
83a2f93 docs: investigation for issue #801 (20th RAILWAY_TOKEN expiration) (#802)
7b8fcc9 docs: investigation for issue #798 (19th RAILWAY_TOKEN expiration) (#799)
```

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent fabricates a `.github/RAILWAY_TOKEN_ROTATION_804.md` claiming success. | Explicitly forbidden by `CLAUDE.md`; this artifact does not create such a file. |
| Human rotates the token but with a default short TTL. | Step 1 emphasizes **"No expiration"** — this is the recurrence root cause. |
| Prod deploy job will hit the same failure on next deploy. | The rotation fixes both staging and prod since both jobs read the same `RAILWAY_TOKEN` secret. |
| `gh run rerun 25182725669` returns "run too old" / not rerunnable. | The fallback command in Step 3 reruns the most recent failed run. |
| Recurrence pattern (21 times) suggests systemic process problem. | Out of scope here; consider a follow-up issue to track Railway-side automation or alternate auth (e.g., service tokens with longer TTLs). |

---

## Validation

### Automated Checks

After human rotates the token:

```bash
# Re-run the failed staging deploy
gh run rerun 25182725669 --repo alexsiri7/reli --failed

# Watch the rerun
gh run watch --repo alexsiri7/reli
```

### Manual Verification

1. New run of `staging-pipeline.yml` reaches `Deploy staging image to Railway` without the `RAILWAY_TOKEN is invalid or expired` error.
2. Staging health probe (`/healthz`) returns `{"status":"ok"}` within the 20-attempt loop at `.github/workflows/staging-pipeline.yml:90-104`.
3. `railway-token-health.yml` next scheduled run reports green.

---

## Scope Boundaries

**IN SCOPE:**
- Documenting the failure, pointing the human at `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Posting a GitHub comment on issue #804 with this analysis.

**OUT OF SCOPE (do not touch):**
- Editing `.github/workflows/staging-pipeline.yml` — the validate step is correct.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file (forbidden by CLAUDE.md).
- Attempting to rotate the token via API (agents lack the credentials and the policy forbids it).
- Architectural changes to the Railway deploy approach (the recurrence pattern may warrant a separate issue, but that is a future decision).

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-30T18:50:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/b9863d3691e7e5613a5dc5d396567ce8/investigation.md`
