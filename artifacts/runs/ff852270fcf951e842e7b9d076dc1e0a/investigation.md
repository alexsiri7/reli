# Investigation: Main CI red — Deploy to staging (RAILWAY_TOKEN rejected — 59th occurrence)

**Issue**: #901 (https://github.com/alexsiri7/reli/issues/901)
**Type**: BUG (infrastructure / secret rotation — recurring)
**Investigated**: 2026-05-02T16:10:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Staging (and downstream production + smoke-test jobs) fully blocked at the `Validate Railway secrets` pre-flight; no CI workaround; no data loss or security exposure; identical recurring pattern to 58 prior incidents. |
| Complexity | LOW | Zero code changes for this bead — a single GitHub Actions secret value (`RAILWAY_TOKEN`) must be replaced by a human admin via railway.com → repo Settings. Per `CLAUDE.md` § "Railway Token Rotation", agents cannot perform this action. |
| Confidence | HIGH | Run [25252013103](https://github.com/alexsiri7/reli/actions/runs/25252013103) summary logs the exact error string `RAILWAY_TOKEN is invalid or expired: Not Authorized` at the `Validate Railway secrets` step (workflow created `2026-05-02T12:34:28Z`); identical signature to 58 prior incidents (#742 → … → #898); web-research findings are already on file in this run's `web-research.md`. |

---

## Problem Statement

The `Deploy to staging` job in run [25252013103](https://github.com/alexsiri7/reli/actions/runs/25252013103) failed at the **Validate Railway secrets** step. Railway's GraphQL API responded `Not Authorized` to the `{me{id}}` validation probe — the `RAILWAY_TOKEN` GitHub Actions secret is rejected. The downstream `Deploy to production` and `Staging E2E smoke tests` jobs were skipped (showing `-` in the run summary).

This is the **59th** RAILWAY_TOKEN rejection tracked on this repo and the **19th today** (2026-05-02). Issue #898 was the immediate predecessor; the chain has now extended to **eleven** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901), with each prior rotation followed by another rejection at the next deploy attempt. The `web-research.md` in this run dir documents the project-token-vs-account-token hypothesis that may explain why like-for-like rotations are not breaking the chain.

---

## Analysis

### Root Cause / Change Rationale

**WHY**: Run 25252013103 (`Staging → Production Pipeline` on commit `13bf51e9`) failed.
↓ **BECAUSE**: The `Deploy to staging` job (`ID 74045436358`) exited 1 at the `Validate Railway secrets` step.
&nbsp;&nbsp;Evidence (run summary): `X RAILWAY_TOKEN is invalid or expired: Not Authorized` followed by `X Process completed with exit code 1.`
↓ **BECAUSE**: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned a response without `.data.me.id`, so the `jq -e` check at line 53 failed.
&nbsp;&nbsp;Evidence: `.github/workflows/staging-pipeline.yml:49-58` posts `{"query":"{me{id}}"}` with `Authorization: Bearer $RAILWAY_TOKEN` and exits 1 with the observed error string when `.data.me.id` is missing.
↓ **ROOT CAUSE (surface)**: The `RAILWAY_TOKEN` GitHub Actions secret holds a token Railway no longer accepts. Identical to #898, #896, #894, #891, #888, …, #742 — all resolved (when resolved) by rotating the secret value via railway.com.

> **Deeper hypothesis (already documented in this run's `web-research.md`)**: 11 rejections in a tight chain is not consistent with simple TTL expiration. Railway docs reserve the env-var name `RAILWAY_TOKEN` for **project tokens** (used with the `Project-Access-Token` header), while account/workspace tokens (which the validator's `Authorization: Bearer` + `{me{id}}` probe actually requires) belong in `RAILWAY_API_TOKEN`. If the runbook is directing humans to mint a project token at https://railway.com/account/tokens (it is not — but the secret name suggests one), the rotation would always fail-on-arrival. **This is out of scope for #901** (Polecat Scope Discipline) — escalation to mayor is captured in `web-research.md` § Recommendations #2.

### Affected Files

No source code, workflow, or runbook changes. This bead produces investigation artifacts only — see `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
> Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/investigation.md` | NEW | CREATE | This document — failing run, error, runbook pointer, prior-occurrence count |
| `artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/web-research.md` | EXISTING | KEEP | Already on disk — captures the project-token-vs-account-token hypothesis. Do not edit. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — the failing `Validate Railway secrets` step that probes Railway with `{me{id}}` and exits 1 on rejection. **Do not modify.** It is the correct fail-fast guard.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the human-facing rotation runbook (52 lines). **Do not modify in this bead.**
- `DEPLOYMENT_SECRETS.md` — referenced by the validator's error message (`"See DEPLOYMENT_SECRETS.md for setup instructions."`); describes the secrets the workflow expects.

### Git History

- **Workflow last touched**: `git log .github/workflows/staging-pipeline.yml` — the validator step is stable; the recurring failures are an environment/secret problem, not a code regression.
- **Issue cadence**: Issue #898 was created at `2026-05-02T12:00:20Z` and closed at `2026-05-02T12:30:10Z`; #901 was filed at `2026-05-02T13:00:27Z` against run 25252013103 (`createdAt 2026-05-02T12:34:28Z`). The next deploy attempt after #898's close failed within ~4 minutes — consistent with the secret remaining rejected even after the human-cycle on #898.
- **Most recent merged investigation**: PR #899 (commit `13bf51e`) for #898 — same docs-only pattern this bead follows.

---

## Implementation Plan

This is a **docs-only** investigation. No source files are modified. The implementing agent's job is to:

1. Confirm `artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/investigation.md` (this file) and `web-research.md` (already on disk) are committed.
2. Post a routing comment on issue #901 directing the human admin to `docs/RAILWAY_TOKEN_ROTATION_742.md` and to `web-research.md` for the runbook-revision hypothesis.
3. **Not** create `.github/RAILWAY_TOKEN_ROTATION_901.md` (Category 1 error per `CLAUDE.md`).
4. **Not** modify the workflow, the runbook, `DEPLOYMENT_SECRETS.md`, or any backend/frontend source.

| Step | Actor | Action |
|------|-------|--------|
| 1 | **Human admin** | Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`. **Before re-rotating like-for-like, read `web-research.md` § Recommendations** — the secret name vs auth-scheme mismatch may be the actual cause. |
| 2 | Human admin | Verify the new token: `gh workflow run railway-token-health.yml --repo alexsiri7/reli` and watch it pass before re-running staging. |
| 3 | Human admin | Re-run the failed pipeline: `gh run rerun 25252013103 --repo alexsiri7/reli --failed`. |
| 4 | Human admin | Confirm `Validate Railway secrets` passes; close #901 with the green run URL. |

> ⚠️ **Per `CLAUDE.md` Railway Token Rotation policy, agents cannot rotate this token.** No `.github/RAILWAY_TOKEN_ROTATION_901.md` will be created — that is a Category 1 error.

### Step 1: Human admin rotates the secret

**Action**: Replace the value of GitHub Actions secret `RAILWAY_TOKEN` in repo Settings → Secrets and variables → Actions with a freshly minted Railway API token (per `docs/RAILWAY_TOKEN_ROTATION_742.md`, "No expiration" selected).

**Why**: Railway has rejected the current token value. The validator step blocks the deploy until a token that authenticates against `backboard.railway.app/graphql/v2` is in place.

### Step 2: Verify the new token before re-running the deploy

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run watch <new-run-id> --repo alexsiri7/reli
```

**Why**: Catches a bad rotation (typo, wrong token type) before the staging pipeline burns another deploy slot on a token that won't authenticate.

### Step 3: Re-run the failed pipeline

```bash
gh run rerun 25252013103 --repo alexsiri7/reli --failed
gh run watch 25252013103 --repo alexsiri7/reli
```

**Why**: The original failure is in the validation step; nothing downstream ran (`Deploy to production` and `Staging E2E smoke tests` are listed with `-`). Re-running `--failed` resumes from the failed job with the new secret value.

---

## Patterns to Follow

This investigation follows the pattern established by the immediately preceding RAILWAY_TOKEN beads — most recently #898 / PR #899:

- Investigation artifact at `artifacts/runs/<workflow_id>/investigation.md` only.
- Routing comment posted on the GitHub issue.
- No `.github/RAILWAY_TOKEN_ROTATION_*.md` created (Category 1 guard).
- No workflow / runbook / source modifications (Polecat Scope Discipline).
- The runbook-revision hypothesis is already on record in `web-research.md` for this run — link to it from the routing comment, do not re-litigate it here.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Human rotates with the same (wrong-type or short-TTL) token; chain continues to issue #903+ | Routing comment links to `web-research.md` § Recommendations #2 so the admin can consider the runbook-revision options before re-rotating like-for-like. |
| Merging the implementation PR triggers another deploy on the still-dead token, producing a successor `Main CI red: Deploy to staging` issue | Expected — documented here. The chain only stops once the secret is rotated correctly. The `archon:in-progress` label on #901 prevents pickup-cron double-firing. |
| Agent accidentally creates `.github/RAILWAY_TOKEN_ROTATION_901.md` | Explicit Category 1 guard above; implementer must verify no such file is staged before committing. |
| Agent modifies the workflow or runbook beyond scope | Polecat Scope Discipline — out-of-scope ideas are mailed to mayor (`web-research.md` already records the recommended escalation), not implemented in this PR. |
| `web-research.md` already exists in the run dir before this bead started | Treat it as authoritative for the deeper hypothesis — link to it; do not duplicate or rewrite it. |

---

## Validation

### Automated Checks

```bash
# After human rotation:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25252013103 --repo alexsiri7/reli --failed
gh run watch 25252013103 --repo alexsiri7/reli
```

Expected: `Validate Railway secrets` step prints success and the downstream `Deploy staging image to Railway` step proceeds with no `Not Authorized` from `serviceInstanceUpdate`.

### Manual Verification

1. Confirm no `.github/RAILWAY_TOKEN_ROTATION_901.md` file exists in the PR diff (Category 1 guard).
2. Confirm `.github/workflows/staging-pipeline.yml` and `docs/RAILWAY_TOKEN_ROTATION_742.md` are unmodified in the PR diff (Polecat scope).
3. Confirm `DEPLOYMENT_SECRETS.md` is unmodified.
4. Confirm the routing comment is posted on issue #901 with a link to the runbook and to `web-research.md`.

---

## Scope Boundaries

**IN SCOPE:**
- Create `artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/investigation.md` (this document).
- Post a routing comment on issue #901 directing the human admin to the rotation runbook.
- Acknowledge the existing `web-research.md` (do not modify).

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` (the validator is correct as written).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` (runbook revision is a separate bead per `web-research.md` § Recommendations #2).
- `DEPLOYMENT_SECRETS.md`.
- Any backend / frontend source.
- Performing the rotation itself (`CLAUDE.md` Category 1 error).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` (`CLAUDE.md` Category 1 error).
- Re-publishing the project-token-vs-account-token hypothesis already captured in `web-research.md`.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-05-02T16:10:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/investigation.md`
- **Companion**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/ff852270fcf951e842e7b9d076dc1e0a/web-research.md`
- **Failing run**: https://github.com/alexsiri7/reli/actions/runs/25252013103
- **Predecessor bead**: #898 / PR #899 (commit `13bf51e`)
