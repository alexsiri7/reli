# Investigation: Daily Railway token health-check failed (RAILWAY_TOKEN expired — 55th occurrence, 1st flagged by railway-token-health.yml in this streak)

**Issue**: #889 (https://github.com/alexsiri7/reli/issues/889)
**Type**: BUG (infrastructure / secret rotation — daily monitor signal)
**Investigated**: 2026-05-02T10:30:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | MEDIUM | Daily health-check (monitor) failure, not a deploy block. The deploy-blocked angle is already captured by #888 (HIGH). The same human rotation closes both, but #889 in isolation is monitoring noise rather than a production outage. |
| Complexity | LOW | Zero code changes required — a single GitHub Actions secret value (`RAILWAY_TOKEN`) must be replaced by a human admin via railway.com → repo Settings. |
| Confidence | HIGH | Failed run 25249487264 logs the exact failure (`Not Authorized` from `backboard.railway.app/graphql/v2` `{me{id}}` probe) at 2026-05-02T10:04:02Z; identical signature to 54 prior incidents (#742 → … → #888). Issue body verbatim from `railway-token-health.yml:48-51`. |

---

## Problem Statement

The `Railway Token Health Check` workflow (`.github/workflows/railway-token-health.yml`, daily cron `0 9 * * *`) failed at run [25249487264](https://github.com/alexsiri7/reli/actions/runs/25249487264) on 2026-05-02T10:04:02Z. The probe to `https://backboard.railway.app/graphql/v2` with `{"query":"{me{id}}"}` returned `Not Authorized`, meaning the `RAILWAY_TOKEN` GitHub Actions secret is expired or revoked. The workflow's `create_issue_if_absent()` helper opened issue #889 with the title `Railway token expired — rotate RAILWAY_TOKEN before next deploy`. This is the **55th** RAILWAY_TOKEN expiration tracked on this repo. It is also the **1st** time the daily health-check workflow itself filed the issue in the current streak (prior 54 issues — #742 → #888 — were all filed by `staging-pipeline.yml`'s validator, even though the daily check has been failing every day since at least 2026-04-28).

The daily health-check workflow has now failed **5 consecutive days** (2026-04-28, 2026-04-29, 2026-04-30, 2026-05-01, 2026-05-02) — verified directly via `gh run list --workflow railway-token-health.yml --status failure --limit 5`. Earlier daily failures did not file separate issues because the `create_issue_if_absent` search-term match (`"Railway token expired"`) deduped against open `staging-pipeline.yml`-filed issues. #889 is the first daily-check-filed issue because all prior `staging-pipeline.yml`-filed issues have since been closed.

---

## Analysis

### Root Cause / Change Rationale

Railway API tokens have a finite lifetime. When the active `RAILWAY_TOKEN` GitHub Actions secret expires (or is revoked), every consumer of it fails: the `staging-pipeline.yml` validator (deploy-blocked, see #888) and the `railway-token-health.yml` daily probe (monitor failure, this issue). The fix is **secret rotation**, not a code change.

### Evidence Chain

WHY: Daily Railway token health-check failed on run 25249487264 at 2026-05-02T10:04:02Z.
↓ BECAUSE: The `Check RAILWAY_TOKEN validity` step in `railway-token-health.yml` POSTed `{"query":"{me{id}}"}` to `backboard.railway.app/graphql/v2` and the response did not contain `.data.me.id`.
  Evidence: workflow source `railway-token-health.yml:42-52` — the `if ! echo "$RESP" | jq -e '.data.me.id'` branch fires `create_issue_if_absent "Railway token expired" …` with the body `Daily token health check failed: \`Not Authorized\`. See docs/RAILWAY_TOKEN_ROTATION_742.md for rotation instructions.` — verbatim match with issue #889's body.

↓ BECAUSE: Railway's GraphQL endpoint rejected the bearer token.
  Evidence: identical failure signature to issues #888, #886, #884, #882, #880, #878, #876, …, #742 — all resolved by rotating the secret value via railway.com.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an expired/revoked Railway API token.
  Evidence: same secret feeds both `staging-pipeline.yml` (deploy validator) and `railway-token-health.yml` (daily monitor). #888 was filed at 2026-05-02T09:34:39Z by the deploy validator; #889 was filed at 2026-05-02T10:04:08Z by the daily monitor — same root cause, two different alerting paths, ~30 minutes apart.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | — | No code changes required. Fix is a GitHub Actions **secret value** rotation performed in repo Settings → Secrets and variables → Actions. |

### Integration Points

- **GitHub Actions secret**: `RAILWAY_TOKEN` (consumed by every deploy workflow's `Validate Railway secrets` step AND by the daily `railway-token-health.yml` monitor).
- **Railway API**: `https://backboard.railway.app/graphql/v2` — issues and validates the token.
- **Workflow (this issue's source)**: `.github/workflows/railway-token-health.yml` — the failing daily probe.
- **Workflow (deploy-blocked sibling)**: `.github/workflows/staging-pipeline.yml` — same secret, different alerting path; #888 captures that path.
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md` — step-by-step rotation procedure for the human.
- **Repo policy**: `CLAUDE.md` "Railway Token Rotation" — agents MUST NOT claim to rotate the token.

### Git History

- **First occurrence on file**: tracked back to issue #742 (the runbook is named for it).
- **Today's volume (across all alerting paths)**: 14 expirations from `staging-pipeline.yml` (per #888) plus this one from `railway-token-health.yml` — same root cause, two different alerting paths.
- **Daily-check cadence**: 5 consecutive days of failures (2026-04-28, 2026-04-29, 2026-04-30, 2026-05-01, 2026-05-02). Only today's filed an issue under its own name; the earlier four were deduped against `staging-pipeline.yml`-filed issues.
- **Implication**: The structural problem — that personal-token rotation alone is not keeping the pipeline green — was already escalated against #886 and reinforced on #888. **#889 is not the place to re-recommend** a project-scoped credential; it is the place to confirm the daily monitor is now correctly surfacing the same signal in its own audit-trail row. The 5-consecutive-day daily-check trend is surfaced once to mayor via mail, per Polecat Scope Discipline.

---

## Implementation Plan

This investigation produces **no code changes**. The required action is human secret rotation.

### Step 1: Human rotates `RAILWAY_TOKEN`

**Actor**: A repo admin with railway.com access (agents cannot perform this step).
**Action**: Follow `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Generate a new API token under Account Settings → Tokens.
3. In GitHub: repo Settings → Secrets and variables → Actions → update `RAILWAY_TOKEN` with the new value.
4. Re-run the failed workflow at https://github.com/alexsiri7/reli/actions/runs/25249487264 (or wait for the next 09:00 UTC cron tick).
5. Confirm the next daily check goes green.
6. Close issue #889 (and #888, which shares the same root cause).

A single rotation closes #888 and #889 simultaneously and stops the daily-check failures from accumulating further.

### Step 2 (DO NOT DO): Create a `.github/RAILWAY_TOKEN_ROTATION_889.md` file claiming rotation is complete

Per `CLAUDE.md` Railway Token Rotation policy:
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

The implementing agent for this issue MUST NOT create `.github/RAILWAY_TOKEN_ROTATION_889.md`. The only correct outcome from an agent is **filing this artifact, posting one routing comment, and waiting for a human**.

### Step 3 (Follow-up, OUT OF SCOPE for this bead): Acknowledge the daily-check 5-day cadence to mayor

5 consecutive days of daily-check failures (2026-04-28 → 2026-05-02) corroborate the structural recommendation already made on #886 and reinforced on #888. A separate follow-up should:

- Send mail to mayor noting the daily-check trend and runs 25049349913 (2026-04-28), 25105119767 (2026-04-29), 25161724763 (2026-04-30), 25211139148 (2026-05-01), 25249487264 (2026-05-02).
- Ask mayor to confirm whether the structural follow-up issue is already filed (per #886/#888 escalations) before opening a duplicate.
- **Do not** re-recommend the project-scoped credential design here — it has already been escalated twice.

Per "Polecat Scope Discipline" in `CLAUDE.md`, do **not** address the structural design in the current bead.

---

## Patterns to Follow

**From repo history — mirror the resolution path of prior identical incidents (e.g., #742, #876, #878, #880, #882, #884, #886, #888):**

- The fix commit/PR for those issues was a **docs-only investigation note**, not a code change.
- The token rotation itself was performed by a human admin out-of-band.
- The issue was closed only after the next monitor / deploy ran green.

The most recent precedent — `artifacts/runs/1de35348acc7c51029dcba9e2d07e4dc/investigation.md` (issue #888) — is the template this artifact mirrors.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Agent tries to "fix" by creating a `RAILWAY_TOKEN_ROTATION_889.md` claiming success | Explicitly forbidden by `CLAUDE.md`; reject any such PR. |
| Agent tries to "fix" by raising tolerance / changing cron / suppressing duplicate-issue creation in `railway-token-health.yml` | Forbidden — the workflow is correct; the failure is data, not code. The duplicate-issue suppression is what made earlier daily-check failures invisible; tightening or loosening it should be a separate, mayor-approved change. |
| Agent tries to read the secret value | Impossible — GitHub masks secrets. |
| New token leaks into logs | The probe only sends `***` in the `Authorization` header; no change needed. |
| Agent posts a routing comment on #888 too (instead of just #889) | Forbidden by Task 3 GOTCHA — #888 already has its routing comment from 2026-05-02T10:07:13Z; do not double-post. |
| Two agents run for #889 in parallel and both post routing comments | Pre-flight Task 1 reads existing comments and aborts if any agent comment is present. |
| The token is rotated by a human while the bead is in flight, and the next cron run goes green | Edge Cases checklist row 4 — switch the comment to a "resolved by rotation at <ts>" form, still commit the artifact (audit trail still valuable). |

---

## Validation

### Automated Checks

```bash
# After human rotates the secret, re-run the failed workflow (or wait for tomorrow's cron tick):
gh run rerun 25249487264 --repo alexsiri7/reli
gh run watch 25249487264 --repo alexsiri7/reli
```

### Manual Verification

1. Confirm the `Check RAILWAY_TOKEN validity` step prints `RAILWAY_TOKEN is valid.` (no `Not Authorized`).
2. Confirm tomorrow's 09:00 UTC cron tick succeeds.
3. Confirm the next deploy from `main` triggers a green pipeline (closes #888 in the same human action).
4. Close issue #889 with a comment linking the green run.

---

## Scope Boundaries

**IN SCOPE:**
- Diagnosing the failure as a `RAILWAY_TOKEN` expiration.
- Producing this investigation artifact under `artifacts/runs/c9f685899fed213b579b2eb37be19ca6/`.
- Posting a single routing comment on issue #889 directing a human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Sending one mail to mayor noting the 5-consecutive-day daily-check trend (Polecat Scope Discipline).

**OUT OF SCOPE (do not touch):**
- The token rotation itself (humans only — `CLAUDE.md` policy).
- Creating a `.github/RAILWAY_TOKEN_ROTATION_889.md` file (Category 1 error per `CLAUDE.md`).
- Modifying `railway-token-health.yml` (alarm logic is correct; the failure is data).
- Modifying `staging-pipeline.yml` (out of scope for #889 — that's #888's path).
- Re-recommending a project-scoped Railway token / service account (already escalated on #886/#888 — mayor mail acknowledges, does not re-recommend).
- Reopening or commenting on #886, #888, or other prior incidents.
- Any frontend, backend, or DB changes — this is purely a secret-rotation incident.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T10:30:00Z
- **Artifact**: `artifacts/runs/c9f685899fed213b579b2eb37be19ca6/investigation.md`
- **Failing run**: 25249487264 (https://github.com/alexsiri7/reli/actions/runs/25249487264)
- **Source workflow**: `.github/workflows/railway-token-health.yml`
- **Sibling issue (same root cause, deploy path)**: #888 (already routed at 2026-05-02T10:07:13Z)
