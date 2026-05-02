# Investigation: Prod deploy failed on main (RAILWAY_TOKEN expired — 53rd occurrence)

**Issue**: #886 (https://github.com/alexsiri7/reli/issues/886)
**Type**: BUG (infrastructure / secret rotation)
**Investigated**: 2026-05-02T09:15:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy is fully blocked (no workaround) but no data loss/security exposure; a known recurring infrastructure issue with a documented fix path. |
| Complexity | LOW | Zero code changes required — a single GitHub Actions secret value must be replaced by a human. |
| Confidence | HIGH | Deploy log shows the exact failure (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at the `Validate Railway secrets` step on run 25248500899; identical signature to 52 prior incidents. |

---

## Problem Statement

The `Deploy to staging` job in run [25248500899](https://github.com/alexsiri7/reli/actions/runs/25248500899) failed at the **Validate Railway secrets** step. Railway's GraphQL API responded `Not Authorized` to the validation probe, meaning the `RAILWAY_TOKEN` GitHub Actions secret is expired or revoked. No subsequent build/deploy steps ran. This is the 53rd RAILWAY_TOKEN expiration tracked on this repo and the 13th today (2026-05-02), arriving ~30 minutes after #884.

---

## Analysis

### Root Cause / Change Rationale

Railway API tokens have a finite lifetime. When the active `RAILWAY_TOKEN` GitHub Actions secret expires (or is revoked), the CI validator step (which probes `https://backboard.railway.app/graphql/v2` with `{me{id}}`) receives `Not Authorized` and halts the deploy. The fix is **secret rotation**, not a code change.

### Evidence Chain

WHY: Prod deploy failed on commit `6d1e9ce` at 2026-05-02T09:05:06Z.
↓ BECAUSE: The `Deploy to staging` workflow exited 1 at the `Validate Railway secrets` step.
  Evidence: run log `2026-05-02T09:05:03.5810644Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned `Not Authorized` — the token is rejected by Railway.
  Evidence: validator step in `.github/workflows/staging-pipeline.yml` posts `{"query":"{me{id}}"}` and exits 1 if `.data.me.id` is missing.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an expired/revoked Railway API token.
  Evidence: identical failure signature to issues #884, #882, #880, #878, #876, …, #742 — all resolved by rotating the secret value via railway.com.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | — | No code changes required. Fix is a GitHub Actions **secret value** rotation performed in repo Settings → Secrets and variables → Actions. |

### Integration Points

- **GitHub Actions secret**: `RAILWAY_TOKEN` (consumed by every deploy workflow at the `Validate Railway secrets` step).
- **Railway API**: `https://backboard.railway.app/graphql/v2` — issues and validates the token.
- **Workflow**: `.github/workflows/staging-pipeline.yml` — the failing validator lives here.
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md` — step-by-step rotation procedure.
- **Repo policy**: `CLAUDE.md` "Railway Token Rotation" — agents MUST NOT claim to rotate the token.

### Git History

- **First occurrence on file**: tracked back to issue #742 (the runbook is named for it).
- **Today's volume**: 13 expirations as of 2026-05-02 (#886 is the 13th today, the 53rd overall).
- **Inter-arrival**: ~30 minutes from #884 (run 25248009761 → 25248500899). The accelerated cadence has now held for at least 5 consecutive incidents (#878 → #880 → #882 → #884 → #886).
- **Implication**: Personal-token rotation alone is no longer keeping the pipeline green. **Out of scope for this fix** — but escalation to mayor for a structural fix (project-scoped Railway token, service account, or longer-TTL credential) is increasingly urgent.

---

## Implementation Plan

This investigation produces **no code changes**. The required action is human secret rotation.

### Step 1: Human rotates `RAILWAY_TOKEN`

**Actor**: A repo admin with railway.com access (agents cannot perform this step).
**Action**: Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new API token under Account Settings → Tokens.
3. In GitHub: repo Settings → Secrets and variables → Actions → update `RAILWAY_TOKEN` with the new value.
4. Re-run the failed workflow at https://github.com/alexsiri7/reli/actions/runs/25248500899 (or wait for next push to `main`).
5. Confirm the next deploy goes green.
6. Close issue #886.

### Step 2 (DO NOT DO): Create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is complete

Per `CLAUDE.md` Railway Token Rotation policy:
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

The implementing agent for this issue MUST NOT create such a file. The only correct outcome from an agent is **filing/updating this issue and waiting for a human**.

### Step 3 (Optional follow-up, OUT OF SCOPE): Escalate the rotation cadence to mayor

13 expirations in one day with a steady ~30-minute inter-arrival is no longer a transient symptom — it is a structural problem. A separate follow-up should:
- Send mail to mayor summarising the trend (#878 → #880 → #882 → #884 → #886, all today, all RAILWAY_TOKEN).
- Recommend evaluating: project-scoped Railway token, Railway service account, long-lived deploy credential, or alternate hosting.
- Track the work as its own issue, not bundled with this incident.

Do **not** address this in the current bead.

---

## Patterns to Follow

**From repo history — mirror the resolution path of prior identical incidents (e.g., #742, #876, #878, #880, #882, #884):**

- The fix commit/PR for those issues was a **docs-only investigation note**, not a code change.
- The token rotation itself was performed by a human admin out-of-band.
- The issue was closed only after the next deploy ran green.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent tries to "fix" by creating a `RAILWAY_TOKEN_ROTATION_886.md` claiming success | Explicitly forbidden by `CLAUDE.md`; reject any such PR. |
| Agent tries to read the secret value | Impossible — GitHub masks secrets. |
| New token leaks into logs | Validator only echoes `***`; no change needed. |
| Multiple in-flight deploy jobs after rotation | Re-run only the most recent failed run; older runs will have stale workflow definitions but will succeed if token is now valid. |
| The 13-per-day cadence indicates a deeper issue | File a separate follow-up issue / mail mayor (see Step 3). Do not bundle with this fix. |

---

## Validation

### Automated Checks

```bash
# After human rotates the secret, re-run the failed workflow:
gh run rerun 25248500899
gh run watch 25248500899
```

### Manual Verification

1. Confirm the `Validate Railway secrets` step reports success (no `Not Authorized`).
2. Confirm subsequent deploy steps complete and the staging URL responds.
3. Confirm the next push to `main` triggers a green deploy.
4. Close issue #886 with a comment linking the green run.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the failure as a `RAILWAY_TOKEN` expiration.
- Producing this investigation artifact.
- Posting a comment on issue #886 directing a human to the rotation runbook.

**OUT OF SCOPE (do not touch):**
- The token rotation itself (humans only — `CLAUDE.md` policy).
- Creating a `.github/RAILWAY_TOKEN_ROTATION_886.md` file (Category 1 error per `CLAUDE.md`).
- Modifying the validator workflow.
- Escalating the 13/day cadence to mayor (file separate issue / mail).
- Any frontend, backend, or DB changes — this is purely a secret-rotation incident.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T09:15:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/e91bc4fa93b72a9e8e01cfa3db770a5d/investigation.md`
