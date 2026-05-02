# Investigation: Prod deploy failed on main (RAILWAY_TOKEN expired — 55th occurrence)

**Issue**: #891 (https://github.com/alexsiri7/reli/issues/891)
**Type**: BUG (infrastructure / secret rotation)
**Investigated**: 2026-05-02T10:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy is fully blocked at the validator step (no workaround), but no data loss / security exposure; a known recurring infrastructure issue with a documented fix path. |
| Complexity | LOW | Zero code changes required — a single GitHub Actions secret value (`RAILWAY_TOKEN`) must be replaced by a human admin via railway.com → repo Settings. |
| Confidence | HIGH | Failed run 25249509349 logs the exact failure (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at the `Validate Railway secrets` step; identical signature to 54 prior incidents (#742 → … → #888). |

---

## Problem Statement

The `Deploy to staging` job in run [25249509349](https://github.com/alexsiri7/reli/actions/runs/25249509349) failed at the **Validate Railway secrets** step at 2026-05-02T10:05:27Z. Railway's GraphQL API responded `Not Authorized` to the `{me{id}}` validation probe, meaning the `RAILWAY_TOKEN` GitHub Actions secret is expired or revoked. No subsequent build/deploy steps ran. This is the **55th** RAILWAY_TOKEN expiration tracked on this repo and the **15th today** (2026-05-02), arriving ~31 minutes after #888 — the steady ~30-minute inter-arrival now holds across **seven** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891). A separate rotation tracker issue, **#889**, is already OPEN.

---

## Analysis

### Root Cause / Change Rationale

Railway API tokens have a finite lifetime. When the active `RAILWAY_TOKEN` GitHub Actions secret expires (or is revoked), the CI validator step (which probes `https://backboard.railway.app/graphql/v2` with `{me{id}}`) receives `Not Authorized` and halts the deploy. The fix is **secret rotation**, not a code change.

### Evidence Chain

WHY: Prod deploy failed on commit `07a8f3fde237c1cff5d4df38dfe6f80159d61efb` at 2026-05-02T10:05:30Z.
↓ BECAUSE: The `Deploy to staging` workflow exited 1 at the `Validate Railway secrets` step.
  Evidence: run log `2026-05-02T10:05:27.0580615Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned `Not Authorized` — the token is rejected by Railway.
  Evidence: validator step in `.github/workflows/staging-pipeline.yml:32-58` posts `{"query":"{me{id}}"}` and exits 1 if `.data.me.id` is missing.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an expired/revoked Railway API token.
  Evidence: identical failure signature to issues #888, #886, #884, #882, #880, #878, #876, …, #742 — all resolved by rotating the secret value via railway.com. Tracker issue #889 is already OPEN for this rotation.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | — | No code changes required. Fix is a GitHub Actions **secret value** rotation performed in repo Settings → Secrets and variables → Actions. |

### Integration Points

- **GitHub Actions secret**: `RAILWAY_TOKEN` (consumed by every deploy workflow at the `Validate Railway secrets` step).
- **Railway API**: `https://backboard.railway.app/graphql/v2` — issues and validates the token.
- **Workflow**: `.github/workflows/staging-pipeline.yml` — the failing validator lives here.
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md` — step-by-step rotation procedure.
- **Active rotation tracker**: issue #889 ("Railway token expired — rotate RAILWAY_TOKEN before next deploy") — already OPEN; rotating per its instructions resolves this issue too.
- **Repo policy**: `CLAUDE.md` "Railway Token Rotation" — agents MUST NOT claim to rotate the token.

### Git History

- **First occurrence on file**: tracked back to issue #742 (the runbook is named for it).
- **Today's volume**: 15 expirations as of 2026-05-02 (#891 is the 15th today, the 55th overall).
- **Inter-arrival**: ~31 minutes from #888 (run 25249000514 → 25249509349). The accelerated cadence has now held for **seven** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891).
- **Implication**: Personal-token rotation alone is no longer keeping the pipeline green. **Out of scope for this fix** — but escalation to mayor for a structural fix (project-scoped Railway token, service account, or longer-TTL credential) is now urgent. Investigations #886 and #888 already recommended this; #891 is further direct evidence the recommendation should be acted on rather than re-recommended. Note also that `web-research.md` (in this run's artifact dir) confirms via Railway docs that the validator workflow uses an account/workspace-token style call — switching to a properly long-TTL account token, or moving to a project-scoped token with the matching header, is the structural fix.

---

## Implementation Plan

This investigation produces **no code changes**. The required action is human secret rotation.

### Step 1: Human rotates `RAILWAY_TOKEN`

**Actor**: A repo admin with railway.com access (agents cannot perform this step).
**Action**: Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new API token under Account Settings → Tokens (**select "No expiration"**, per the runbook — short-TTL defaults are the cause of the recurring failure).
3. In GitHub: repo Settings → Secrets and variables → Actions → update `RAILWAY_TOKEN` with the new value.
4. Re-run the failed workflow at https://github.com/alexsiri7/reli/actions/runs/25249509349 (or wait for next push to `main`).
5. Confirm the next deploy goes green.
6. Close issues #891 **and** #889 (the active rotation tracker).

### Step 2 (DO NOT DO): Create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is complete

Per `CLAUDE.md` Railway Token Rotation policy:
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

The implementing agent for this issue MUST NOT create such a file. The only correct outcome from an agent is **filing/updating this issue and waiting for a human**.

### Step 3 (Follow-up, OUT OF SCOPE for this bead): Escalate the rotation cadence to mayor

15 expirations in one day with a steady ~30-minute inter-arrival (seven consecutive incidents) is a structural problem. A separate follow-up should:
- Send mail to mayor summarising the trend (#878 → #880 → #882 → #884 → #886 → #888 → #891, all today, all RAILWAY_TOKEN, all ~30 min apart).
- Recommend evaluating: project-scoped Railway token (with `Project-Access-Token` header), Railway workspace/account token with **explicit no-expiration TTL**, long-lived deploy credential, or alternate hosting. (See `web-research.md` in this run for Railway-side reference material.)
- Track the work as its own issue, not bundled with this incident.

Per "Polecat Scope Discipline" in `CLAUDE.md`, do **not** address this in the current bead.

---

## Patterns to Follow

**From repo history — mirror the resolution path of prior identical incidents (e.g., #742, #876, #878, #880, #882, #884, #886, #888):**

- The fix commit/PR for those issues was a **docs-only investigation note**, not a code change.
- The token rotation itself was performed by a human admin out-of-band.
- The issue was closed only after the next deploy ran green.

The most recent precedent — `artifacts/runs/1de35348acc7c51029dcba9e2d07e4dc/investigation.md` (issue #888, merged in PR #890) — is the template this artifact mirrors.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent tries to "fix" by creating a `RAILWAY_TOKEN_ROTATION_891.md` claiming success | Explicitly forbidden by `CLAUDE.md`; reject any such PR. |
| Agent tries to read the secret value | Impossible — GitHub masks secrets. |
| New token leaks into logs | Validator only echoes `***`; no change needed. |
| Multiple in-flight deploy jobs after rotation | Re-run only the most recent failed run; older runs will have stale workflow definitions but will succeed if token is now valid. |
| The 15-per-day cadence indicates a deeper issue | File a separate follow-up issue / mail mayor (see Step 3). Do not bundle with this fix. |
| #888 already routed to the operator ~31 min ago — operator may rotate once and clear both | Acceptable: a single rotation will green-light any subsequent failed run. The issue tracker still benefits from #891 having its own routed comment. |
| Operator may rotate via #889 without ever seeing #891 | Acceptable: the validator is shared, so any successful rotation greens this issue's deploy too. The comment we post on #891 will still serve as an audit trail. |

---

## Validation

### Automated Checks

```bash
# After human rotates the secret, re-run the failed workflow:
gh run rerun 25249509349
gh run watch 25249509349
```

### Manual Verification

1. Confirm the `Validate Railway secrets` step reports success (no `Not Authorized`).
2. Confirm subsequent deploy steps complete and the staging URL responds.
3. Confirm the next push to `main` triggers a green deploy.
4. Close issue #891 (and #889) with a comment linking the green run.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the failure as a `RAILWAY_TOKEN` expiration.
- Producing this investigation artifact.
- Posting a comment on issue #891 directing a human to the rotation runbook.

**OUT OF SCOPE (do not touch):**
- The token rotation itself (humans only — `CLAUDE.md` policy).
- Creating a `.github/RAILWAY_TOKEN_ROTATION_891.md` file (Category 1 error per `CLAUDE.md`).
- Modifying the validator workflow.
- Escalating the 15/day cadence to mayor (file separate issue / mail).
- Any frontend, backend, or DB changes — this is purely a secret-rotation incident.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T10:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/606f720ddc2c93cdc49cc98e87e5c9c8/investigation.md`
