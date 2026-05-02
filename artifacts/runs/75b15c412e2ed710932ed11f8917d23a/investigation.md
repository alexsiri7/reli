# Investigation: Prod deploy failed on main — RAILWAY_TOKEN rejected (60th occurrence)

**Issue**: #904 (https://github.com/alexsiri7/reli/issues/904)
**Type**: BUG (infrastructure / secret rotation — recurring)
**Investigated**: 2026-05-02T16:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging (and downstream production + smoke-test jobs) fully blocked at the `Validate Railway secrets` pre-flight; no CI workaround; no data loss or security exposure; identical recurring pattern to 59 prior incidents. |
| Complexity | LOW | Zero code changes for this bead — a single GitHub Actions secret value (`RAILWAY_TOKEN`) must be replaced by a human admin via railway.com → repo Settings. Per `CLAUDE.md` § "Railway Token Rotation", agents cannot perform this action. |
| Confidence | HIGH | Run [25255409159](https://github.com/alexsiri7/reli/actions/runs/25255409159) logs the exact error string `RAILWAY_TOKEN is invalid or expired: Not Authorized` at the `Validate Railway secrets` step (workflow created `2026-05-02T15:34:40Z`); identical signature to 59 prior incidents (#742 → … → #901); deeper systemic findings already on file in this run's `web-research.md`. |

---

## Problem Statement

The `Deploy to staging` job in run [25255409159](https://github.com/alexsiri7/reli/actions/runs/25255409159) failed at the **Validate Railway secrets** step. Railway's GraphQL API responded `Not Authorized` to the `{me{id}}` validation probe — the `RAILWAY_TOKEN` GitHub Actions secret is rejected. Downstream `Deploy to production` and `Staging E2E smoke tests` jobs were skipped.

This is the **60th** RAILWAY_TOKEN rejection tracked on this repo and the **20th today** (2026-05-02). Issue #901 was the immediate predecessor; the chain has now extended to **twelve** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #904), with each prior rotation followed by another rejection at the next deploy attempt. The `web-research.md` in this run dir documents the systemic hypotheses (token-scope-at-creation and TTL-at-creation) that may explain why like-for-like rotations are not breaking the chain.

---

## Analysis

### Root Cause / Change Rationale

**WHY**: Run 25255409159 (`Staging → Production Pipeline` on commit `86aca5cf`) failed.
↓ **BECAUSE**: The `Deploy to staging` job exited 1 at the `Validate Railway secrets` step.
&nbsp;&nbsp;Evidence (run logs): `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` followed by `##[error]Process completed with exit code 1.` at `2026-05-02T15:34:37.3162996Z`.
↓ **BECAUSE**: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned a response without `.data.me.id` — Railway's GraphQL layer set `errors[0].message = "Not Authorized"`, so the `jq -e` check at line 53 failed.
&nbsp;&nbsp;Evidence: `.github/workflows/staging-pipeline.yml:49-58` posts `{"query":"{me{id}}"}` with `Authorization: Bearer $RAILWAY_TOKEN` and exits 1 with the observed error string when `.data.me.id` is missing.
↓ **ROOT CAUSE (surface)**: The `RAILWAY_TOKEN` GitHub Actions secret holds a token Railway no longer accepts. Identical to #901, #898, #896, #894, …, #742 — all resolved (when resolved) by rotating the secret value via railway.com.

> **Deeper hypothesis (already documented in this run's `web-research.md`)**: 12 rejections in a tight chain is not consistent with simple TTL expiration — Railway docs do not document an expiration policy for account tokens. Two systemic factors identified by web research:
> 1. **Wrong scope at creation**: A Railway community thread (`station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1`) reports that tokens created with a workspace selected cannot answer the `{me{id}}` query and fail with `Not Authorized` immediately. The fix is to create the token with **No workspace selected**.
> 2. **TTL at creation**: `docs/RAILWAY_TOKEN_ROTATION_742.md` warns the Railway dashboard's default TTL may be short; previous rotations may have used a default rather than **No expiration**.
>
> **This is out of scope for #904** (Polecat Scope Discipline) — escalation paths are captured in `web-research.md` § Recommendations #2.

### Affected Files

No source code, workflow, or runbook changes. This bead produces investigation artifacts only — see `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
> Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/75b15c412e2ed710932ed11f8917d23a/investigation.md` | NEW | CREATE | This document — failing run, error, runbook pointer, prior-occurrence count |
| `artifacts/runs/75b15c412e2ed710932ed11f8917d23a/web-research.md` | EXISTING | KEEP | Already on disk — captures the wrong-scope and TTL-at-creation hypotheses, and the `.app` vs `.com` host observation. Do not edit. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — the failing `Validate Railway secrets` step that probes Railway with `{me{id}}` and exits 1 on rejection. **Do not modify.** It is the correct fail-fast guard.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the human-facing rotation runbook. **Do not modify in this bead.** Web research (finding #5) confirms the runbook is already explicit about "No expiration"; an admin-facing addendum about "No workspace selected" is recommended in `web-research.md` § Recommendations but is a separate bead.
- `DEPLOYMENT_SECRETS.md` — referenced by the validator's error message; describes the secrets the workflow expects.

### Git History

- **Workflow last touched**: The validator step in `.github/workflows/staging-pipeline.yml` is stable across the 12-incident chain — the recurring failures are an environment/secret problem, not a code regression.
- **Issue cadence today**: #898 (18th today), #901 (19th today), #904 (20th today). #901 was opened against run `25252013103` (created `2026-05-02T12:34:28Z`); #904 is against run `25255409159` (created `2026-05-02T15:34:40Z`) — three hours and one full pipeline cycle later, with the secret still rejected.
- **Most recent merged investigation**: PR #902 (commit `86aca5c`) for #901 — same docs-only pattern this bead follows. The merge of PR #902 is the SHA (`86aca5cf`) that #904's failed deploy run was built from, confirming the next deploy attempt after PR #902 still hit a rejected token.

---

## Implementation Plan

This is a **docs-only** investigation. No source files are modified. The implementing agent's job is to:

1. Confirm `artifacts/runs/75b15c412e2ed710932ed11f8917d23a/investigation.md` (this file) and `web-research.md` (already on disk) are committed.
2. Post a routing comment on issue #904 directing the human admin to `docs/RAILWAY_TOKEN_ROTATION_742.md` and to `web-research.md` for the wrong-scope and TTL-at-creation hypotheses.
3. **Not** create `.github/RAILWAY_TOKEN_ROTATION_904.md` (Category 1 error per `CLAUDE.md`).
4. **Not** modify the workflow, the runbook, `DEPLOYMENT_SECRETS.md`, or any backend/frontend source.

| Step | Actor | Action |
|------|-------|--------|
| 1 | **Human admin** | Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`. **Before re-rotating like-for-like, read `web-research.md` § Recommendations** — the wrong-workspace-scope and short-TTL hypotheses may be the actual causes of the recurrence chain. |
| 2 | Human admin | Verify the new token: `gh workflow run railway-token-health.yml --repo alexsiri7/reli` and watch it pass before re-running staging. |
| 3 | Human admin | Re-run the failed pipeline: `gh run rerun 25255409159 --repo alexsiri7/reli --failed`. |
| 4 | Human admin | Confirm `Validate Railway secrets` passes; close #904 with the green run URL. |

> ⚠️ **Per `CLAUDE.md` Railway Token Rotation policy, agents cannot rotate this token.** No `.github/RAILWAY_TOKEN_ROTATION_904.md` will be created — that is a Category 1 error.

### Step 1: Human admin rotates the secret

**Action**: Replace the value of GitHub Actions secret `RAILWAY_TOKEN` in repo Settings → Secrets and variables → Actions with a freshly minted Railway API token at railway.com → Account Settings → Tokens, with **(a) No workspace selected** and **(b) No expiration**.

**Why**: Railway has rejected the current token value. The validator step blocks the deploy until a token that authenticates against `backboard.railway.app/graphql/v2` is in place. Per web research finding #3, omitting "No workspace" produces a token that fails the validator's `{me{id}}` probe immediately — so a like-for-like rotation that misses this checkbox would land us right back in #905 within minutes.

### Step 2: Verify the new token before re-running the deploy

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run watch <new-run-id> --repo alexsiri7/reli
```

**Why**: Catches a bad rotation (typo, wrong token type, workspace-scoped token, short TTL) before the staging pipeline burns another deploy slot on a token that won't authenticate.

### Step 3: Re-run the failed pipeline

```bash
gh run rerun 25255409159 --repo alexsiri7/reli --failed
gh run watch 25255409159 --repo alexsiri7/reli
```

**Why**: The original failure is in the validation step; nothing downstream ran. Re-running `--failed` resumes from the failed job with the new secret value.

---

## Patterns to Follow

This investigation follows the pattern established by the immediately preceding RAILWAY_TOKEN beads — most recently #901 / PR #902:

- Investigation artifact at `artifacts/runs/<workflow_id>/investigation.md` only.
- Routing comment posted on the GitHub issue.
- No `.github/RAILWAY_TOKEN_ROTATION_*.md` created (Category 1 guard).
- No workflow / runbook / source modifications (Polecat Scope Discipline).
- The deeper hypotheses are already on record in `web-research.md` for this run — link to them from the routing comment, do not re-litigate them here.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Human rotates with the same (workspace-scoped or short-TTL) token; chain continues to issue #905+ | Routing comment links to `web-research.md` § Recommendations #1–#2 so the admin checks both "No workspace" and "No expiration" before re-rotating like-for-like. |
| Merging the implementation PR triggers another deploy on the still-dead token, producing a successor `Prod deploy failed on main` issue | Expected — documented here. The chain only stops once the secret is rotated correctly. The `archon:in-progress` label on #904 prevents pickup-cron double-firing while this bead is open. |
| Agent accidentally creates `.github/RAILWAY_TOKEN_ROTATION_904.md` | Explicit Category 1 guard above; implementer must verify no such file is staged before committing. |
| Agent modifies the workflow or runbook beyond scope | Polecat Scope Discipline — out-of-scope ideas (`.app`→`.com` host migration, runbook addendum on "No workspace") are mailed to mayor or recorded in `web-research.md`, not implemented in this PR. |
| `web-research.md` already exists in the run dir before this bead started | Treat it as authoritative for the deeper hypotheses — link to it; do not duplicate or rewrite it. |

---

## Validation

### Automated Checks

```bash
# After human rotation:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25255409159 --repo alexsiri7/reli --failed
gh run watch 25255409159 --repo alexsiri7/reli
```

Expected: `Validate Railway secrets` step prints success and the downstream `Deploy staging image to Railway` step proceeds with no `Not Authorized` from `serviceInstanceUpdate`.

### Manual Verification

1. Confirm no `.github/RAILWAY_TOKEN_ROTATION_904.md` file exists in the PR diff (Category 1 guard).
2. Confirm `.github/workflows/staging-pipeline.yml` and `docs/RAILWAY_TOKEN_ROTATION_742.md` are unmodified in the PR diff (Polecat scope).
3. Confirm `DEPLOYMENT_SECRETS.md` is unmodified.
4. Confirm the routing comment is posted on issue #904 with a link to the runbook and to `web-research.md`.

---

## Scope Boundaries

**IN SCOPE:**
- Create `artifacts/runs/75b15c412e2ed710932ed11f8917d23a/investigation.md` (this document).
- Post a routing comment on issue #904 directing the human admin to the rotation runbook.
- Acknowledge the existing `web-research.md` (do not modify).

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` (the validator is correct as written; the `.app`→`.com` host migration recommended in `web-research.md` § Recommendations #3 is a separate bead).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` (a "No workspace selected" addendum is a separate bead; mail to mayor if needed).
- `DEPLOYMENT_SECRETS.md`.
- Any backend / frontend source.
- Performing the rotation itself (`CLAUDE.md` Category 1 error).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` (`CLAUDE.md` Category 1 error).
- Re-publishing the wrong-scope and TTL-at-creation hypotheses already captured in `web-research.md`.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-05-02T16:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/75b15c412e2ed710932ed11f8917d23a/investigation.md`
- **Companion**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/75b15c412e2ed710932ed11f8917d23a/web-research.md`
- **Failing run**: https://github.com/alexsiri7/reli/actions/runs/25255409159
- **Predecessor bead**: #901 / PR #902 (commit `86aca5c`)
