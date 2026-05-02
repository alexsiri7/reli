# Investigation: Prod deploy failed on main (RAILWAY_TOKEN expired — 52nd occurrence)

**Issue**: #884 (https://github.com/alexsiri7/reli/issues/884)
**Type**: BUG (infrastructure / secret rotation)
**Investigated**: 2026-05-02T08:40:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy is fully blocked (no workaround) but no data loss/security exposure; a known recurring infrastructure issue with a documented fix path. |
| Complexity | LOW | Zero code changes required — a single GitHub Actions secret value must be replaced by a human. |
| Confidence | HIGH | Deploy log shows the exact failure (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at the `Validate Railway secrets` step; identical signature to 51 prior incidents. |

---

## Problem Statement

The `Deploy to staging` job in run [25248009761](https://github.com/alexsiri7/reli/actions/runs/25248009761) failed at the **Validate Railway secrets** step. Railway's GraphQL API responded `Not Authorized` to the validation probe, meaning the `RAILWAY_TOKEN` GitHub Actions secret is expired or revoked. No subsequent build/deploy steps ran. This is the 52nd RAILWAY_TOKEN expiration tracked on this repo and the 12th today.

---

## Analysis

### Root Cause / Change Rationale

Railway API tokens have a finite lifetime. When the active `RAILWAY_TOKEN` GitHub Actions secret expires (or is revoked), the CI validator step (which probes `https://backboard.railway.app/graphql/v2` with `{me{id}}`) receives `Not Authorized` and halts the deploy. The fix is **secret rotation**, not a code change.

### Evidence Chain

WHY: Prod deploy failed on commit `6b231e3`.
↓ BECAUSE: The `Deploy to staging` workflow exited 1 at the `Validate Railway secrets` step.
  Evidence: run log `2026-05-02T08:35:09.0969383Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned `Not Authorized` — the token is rejected by Railway.
  Evidence: validator step in `.github/workflows/*deploy*.yml` posts `{"query":"{me{id}}"}` and exits 1 if `.data.me.id` is missing.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an expired/revoked Railway API token.
  Evidence: identical failure signature to issues #882, #880, #878, #876, #874, …, #752 — all resolved by rotating the secret value via railway.com.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | — | No code changes required. Fix is a GitHub Actions **secret value** rotation performed in repo Settings → Secrets and variables → Actions. |

### Integration Points

- **GitHub Actions secret**: `RAILWAY_TOKEN` (consumed by every deploy workflow at the `Validate Railway secrets` step).
- **Railway API**: `https://backboard.railway.app/graphql/v2` — issues and validates the token.
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md` — step-by-step rotation procedure.
- **Repo policy**: `CLAUDE.md` "Railway Token Rotation" — agents MUST NOT claim to rotate the token.

### Git History

- **First occurrence on file**: tracked back to issue #752 (the runbook is named for it).
- **Today's volume**: 12 expirations as of 2026-05-02 (#884 is the 12th today, the 52nd overall).
- **Implication**: The token is being rotated to a short-lived credential, or a different upstream policy is shortening lifetimes. **Out of scope for this fix** — but worth a follow-up issue to investigate why the rotation cadence has accelerated.

---

## Implementation Plan

This investigation produces **no code changes**. The required action is human secret rotation.

### Step 1: Human rotates `RAILWAY_TOKEN`

**Actor**: A repo admin with railway.com access (agents cannot perform this step).
**Action**: Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new API token under Account Settings → Tokens.
3. In GitHub: repo Settings → Secrets and variables → Actions → update `RAILWAY_TOKEN` with the new value.
4. Re-run the failed workflow at https://github.com/alexsiri7/reli/actions/runs/25248009761 (or wait for next push to `main`).
5. Confirm the next deploy goes green.
6. Close issue #884.

### Step 2 (DO NOT DO): Create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is complete

Per `CLAUDE.md` Railway Token Rotation policy:
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

The implementing agent for this issue MUST NOT create such a file. The only correct outcome from an agent is **filing/updating this issue and waiting for a human**.

### Step 3 (Optional follow-up, OUT OF SCOPE): Investigate rotation cadence

12 expirations in one day is an extreme cadence. A separate investigation should determine whether:
- Token TTL has shortened upstream.
- The token is being invalidated by something else (concurrent logins? team policy?).
- Long-lived deploy keys / project tokens / a Railway service account would be a better fit than a personal API token.

Do **not** address this in the current bead — file a separate issue.

---

## Patterns to Follow

**From repo history — mirror the resolution path of prior identical incidents (e.g., #752, #876, #878, #880, #882):**

- The fix commit/PR for those issues was a **docs-only investigation note**, not a code change.
- The token rotation itself was performed by a human admin out-of-band.
- The issue was closed only after the next deploy ran green.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent tries to "fix" by creating a `RAILWAY_TOKEN_ROTATION_884.md` claiming success | Explicitly forbidden by `CLAUDE.md`; reject any such PR. |
| Agent tries to read the secret value | Impossible — GitHub masks secrets. |
| New token leaks into logs | Validator only echoes `***`; no change needed. |
| Multiple in-flight deploy jobs after rotation | Re-run only the most recent failed run; older runs will have stale workflow definitions but will succeed if token is now valid. |
| The 12-per-day cadence indicates a deeper issue | File a separate follow-up issue (see Step 3). Do not bundle with this fix. |

---

## Validation

### Automated Checks

```bash
# After human rotates the secret, re-run the failed workflow:
gh run rerun 25248009761
gh run watch 25248009761
```

### Manual Verification

1. Confirm the `Validate Railway secrets` step reports success (no `Not Authorized`).
2. Confirm subsequent deploy steps complete and the staging URL responds.
3. Confirm the next push to `main` triggers a green deploy.
4. Close issue #884 with a comment linking the green run.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the failure as a `RAILWAY_TOKEN` expiration.
- Producing this investigation artifact.
- Posting a comment on issue #884 directing a human to the rotation runbook.

**OUT OF SCOPE (do not touch):**
- The token rotation itself (humans only — `CLAUDE.md` policy).
- Creating a `.github/RAILWAY_TOKEN_ROTATION_884.md` file (Category 1 error per `CLAUDE.md`).
- Modifying the validator workflow.
- Investigating why expirations have accelerated to 12/day (file separate issue).
- Any frontend, backend, or DB changes — this is purely a secret-rotation incident.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T08:40:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/6ba51c38cb6ac086b70b628d6b0621e0/investigation.md`
