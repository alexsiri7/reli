# Investigation: Prod deploy failed on main (RAILWAY_TOKEN expired — 56th occurrence)

**Issue**: #894 (https://github.com/alexsiri7/reli/issues/894)
**Type**: BUG (infrastructure / secret rotation)
**Investigated**: 2026-05-02T11:05:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy is fully blocked at the validator step (no workaround), but no data loss or security exposure; a known recurring infra issue with a documented fix path. |
| Complexity | LOW | Zero code changes — a single GitHub Actions secret value (`RAILWAY_TOKEN`) must be replaced by a human admin via railway.com → repo Settings. |
| Confidence | HIGH | Failed run [25249993085](https://github.com/alexsiri7/reli/actions/runs/25249993085) logs the exact failure (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at the `Validate Railway secrets` step; identical signature to 55 prior incidents (#742 → … → #891). |

---

## Problem Statement

The `Deploy to staging` job in run [25249993085](https://github.com/alexsiri7/reli/actions/runs/25249993085) failed at the **Validate Railway secrets** step at 2026-05-02T10:34:36Z. Railway's GraphQL API responded `Not Authorized` to the `{me{id}}` validation probe — the `RAILWAY_TOKEN` GitHub Actions secret is expired or revoked. This is the **56th** RAILWAY_TOKEN expiration tracked on this repo and the **16th today**, arriving ~29 minutes after #891. The ~30-minute inter-arrival now holds across **eight** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894). Rotation tracker issue **#889** is already OPEN.

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` GitHub Actions secret holds an expired/revoked Railway API token. The workflow's pre-deploy validator probes Railway's GraphQL API and exits 1 when the token is rejected. No code path or workflow change can fix this — only a human with railway.com access can mint a new token and update the GitHub secret.

### Evidence Chain

WHY: Prod deploy failed on commit `6bbe0bf` at 2026-05-02T10:34:40Z.
↓ BECAUSE: The `Deploy to staging` workflow exited 1 at the `Validate Railway secrets` step.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` (run 25249993085 logs)

↓ BECAUSE: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned `Not Authorized`.
  Evidence: `.github/workflows/staging-pipeline.yml:32-58` posts `{"query":"{me{id}}"}` and exits 1 if `.data.me.id` is missing.

↓ ROOT CAUSE: The `RAILWAY_TOKEN` GitHub Actions secret holds an expired/revoked Railway API token. Identical to #891, #888, #886, #884, …, #742 — all resolved by rotating the secret value via railway.com.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | — | No code changes. Fix is rotating the `RAILWAY_TOKEN` GitHub Actions secret via the runbook in `docs/RAILWAY_TOKEN_ROTATION_742.md`. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32` — `Validate Railway secrets` step (where the failure surfaces)
- GitHub repo Settings → Secrets and variables → Actions → `RAILWAY_TOKEN` (where the value lives)
- railway.com → Account Settings → Tokens (where the new token is minted)

### Git History

- **Recurring pattern**: #742 → … → #882 → #884 → #886 → #888 → #891 → #894
- **Today's cadence**: 16 expirations on 2026-05-02 (#894 is the 16th); ~30-minute inter-arrival now holds for 8 consecutive incidents
- **Implication**: Long-standing infrastructure issue (token TTL too short); behavior-of-code is correct, the secret value is the problem

---

## Implementation Plan

### Step 1: Human admin rotates the RAILWAY_TOKEN secret

**File**: (none — GitHub Actions secret, not in repo)
**Action**: ROTATE

**What to do** (per `docs/RAILWAY_TOKEN_ROTATION_742.md`):
1. Log into railway.com.
2. Generate a new API token under Account Settings → Tokens. **Select "No expiration"** — short-TTL defaults are the cause of the recurring failure.
3. In GitHub: repo Settings → Secrets and variables → Actions → update `RAILWAY_TOKEN` with the new value.

**Why**: The token validator in `.github/workflows/staging-pipeline.yml:32-58` probes Railway's GraphQL API and exits 1 when `Not Authorized` is returned. Only a fresh token resolves this.

> ⚠️ **Per `CLAUDE.md` Railway Token Rotation policy, agents cannot rotate this token.** Do not create a `.github/RAILWAY_TOKEN_ROTATION_894.md` file claiming rotation is done — that is a Category 1 error.

### Step 2: Re-run the failed workflow

**Action**: VERIFY

```bash
gh run rerun 25249993085
gh run watch 25249993085
```

**Why**: Confirm the `Validate Railway secrets` step now passes and downstream deploy steps complete.

### Step 3: Close the related issues

**Action**: CLEANUP

Close **#894** (this issue) and **#889** (the rotation tracker) once the next deploy goes green.

---

## Patterns to Follow

The runbook at `docs/RAILWAY_TOKEN_ROTATION_742.md` is the canonical procedure. The previous 55 investigations (most recently #891) are all variants of this same artifact — none required code changes.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| New token also short-TTL → another expiration in ~30 min | Select **No expiration** when minting (or longest available); see Follow-up. |
| Re-run picks up cached failure | Use `gh run rerun --failed` or push a fresh commit to `main`. |
| Agent attempts rotation and fabricates a `RAILWAY_TOKEN_ROTATION_894.md` | Explicit Category 1 prohibition in `CLAUDE.md`; this artifact reiterates it. |

---

## Validation

### Automated Checks

```bash
gh run rerun 25249993085
gh run watch 25249993085
```

The `Validate Railway secrets` step should report success and downstream `Deploy` steps should complete green.

### Manual Verification

1. Confirm the new token value is saved in GitHub Actions secrets.
2. Watch the rerun (or next `main` push) reach the `Deploy to staging` step successfully.
3. Confirm `https://reli-staging.up.railway.app` (or equivalent) responds.

---

## Scope Boundaries

**IN SCOPE:**
- Document the failure, point to the rotation runbook, hand off to the human admin.

**OUT OF SCOPE (do not touch):**
- Code changes to `.github/workflows/staging-pipeline.yml` (validator is working correctly).
- Creating a `RAILWAY_TOKEN_ROTATION_894.md` claiming rotation is done — agents cannot rotate the token.
- Bundling the structural fix (long-lived token, project-scoped token, alternate hosting) into this incident — that belongs in a separate issue / mail to mayor (Polecat Scope Discipline).

### Follow-up (separate issue / mayor mail)

Eight consecutive ~30-minute expirations (#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894) is structural. Evaluate independently: project-scoped Railway token (with `Project-Access-Token` header), workspace/account token with explicit no-expiration TTL, long-lived deploy credential, or alternate hosting.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T11:05:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/594db19c756acf05e346a8d70e5a6a19/investigation.md`
