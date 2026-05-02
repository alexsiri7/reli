# Investigation: Prod deploy failed on main (RAILWAY_TOKEN rejected — 58th occurrence)

**Issue**: #898 (https://github.com/alexsiri7/reli/issues/898)
**Type**: BUG (infrastructure / secret rotation — recurring)
**Investigated**: 2026-05-02T12:05:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy fully blocked at the `Validate Railway secrets` pre-flight (no CI workaround); no data loss or security exposure; identical recurring pattern to 57 prior incidents. |
| Complexity | LOW | Zero code changes for this bead — a single GitHub Actions secret value (`RAILWAY_TOKEN`) must be replaced by a human admin via railway.com → repo Settings. |
| Confidence | HIGH | Run [25250991058](https://github.com/alexsiri7/reli/actions/runs/25250991058) logs the exact failure (`RAILWAY_TOKEN is invalid or expired: Not Authorized`) at `2026-05-02T11:35:24Z`; identical signature to 57 prior incidents (#742 → … → #896). Inter-arrival from #896 is exactly **30 minutes** — perfect cadence match. |

---

## Problem Statement

The `Deploy to staging` job in run [25250991058](https://github.com/alexsiri7/reli/actions/runs/25250991058) failed at the **Validate Railway secrets** step at `2026-05-02T11:35:24Z`. Railway's GraphQL API responded `Not Authorized` to the `{me{id}}` validation probe — the `RAILWAY_TOKEN` GitHub Actions secret is rejected.

This is the **58th** RAILWAY_TOKEN rejection tracked on this repo and the **18th today**, arriving exactly 30 minutes after #896. The ~30-minute inter-arrival now holds across **ten** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898). Each prior rotation has been followed by another rejection at the next deploy — strongly suggesting like-for-like rotations are not stopping the failures (see #896's companion `web-research.md` for the project-token vs account-token hypothesis).

---

## Analysis

### Root Cause / Change Rationale

**WHY**: Prod deploy run 25250991058 failed at `2026-05-02T11:35:27Z`.
↓ **BECAUSE**: The `Deploy to staging` workflow exited 1 at the `Validate Railway secrets` step.
&nbsp;&nbsp;Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-02T11:35:24.0287765Z`.
↓ **BECAUSE**: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned `Not Authorized`.
&nbsp;&nbsp;Evidence: `.github/workflows/staging-pipeline.yml:49-58` posts `{"query":"{me{id}}"}` and exits 1 if `.data.me.id` is missing.
↓ **ROOT CAUSE (surface)**: The `RAILWAY_TOKEN` GitHub Actions secret holds a rejected Railway API token. Identical to #896, #894, #891, #888, …, #742 — all resolved (when resolved) by rotating the secret value via railway.com.

> **Deeper hypothesis (already documented in #896's `web-research.md`)**: 10 rejections at clockwork 30-min cadence is not consistent with token expiration. The Railway GitHub Actions blog directs users to mint a **project token** (from project settings) for `RAILWAY_TOKEN`, while `docs/RAILWAY_TOKEN_ROTATION_742.md` directs humans to `railway.com/account/tokens` (account-scoped). The chain continuing across multiple rotations is consistent with a token-type mismatch. This is **out of scope for #898** (Polecat Scope Discipline) — the runbook revision is captured as a follow-up in #896's resolution comment.

### Affected Files

No source code changes. This bead produces investigation artifacts only — see `CLAUDE.md` § "Railway Token Rotation":

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
> Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/e0d0f9f1499c026f53b53cc5fcde48a5/investigation.md` | NEW | CREATE | This document — failing run, error, runbook pointer, prior-occurrence count |

### Integration Points

- `.github/workflows/staging-pipeline.yml:34-58` — the failing `Validate Railway secrets` step that probes Railway with `{me{id}}` and exits 1 on rejection. **Do not modify.** It is the correct fail-fast guard.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the human-facing rotation runbook (52 lines).
- `DEPLOYMENT_SECRETS.md` — referenced by the validator's error message; describes the secrets the workflow expects.

### Git History

- **Workflow last touched**: see `git log .github/workflows/staging-pipeline.yml` — the validator step itself is stable; the recurring failures are an environment/secret problem, not a code regression.
- **Issue cadence**: 30-minute inter-arrival aligns with the staging deploy cron / `pipeline-health-cron.sh` cadence — every deploy attempt fails with the same auth error until the secret is rotated.

---

## Implementation Plan

This is a **docs-only** investigation. No source files are modified. The implementing agent's job is to:

1. Create this artifact + companion files in the run dir.
2. Post a routing comment on issue #898 directing the human admin to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
3. **Not** create `.github/RAILWAY_TOKEN_ROTATION_898.md` (Category 1 error per `CLAUDE.md`).
4. **Not** modify the workflow, the runbook, or any backend/frontend source.

| Step | Actor | Action |
|------|-------|--------|
| 1 | **Human admin** | Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md`. **Before re-rotating like-for-like, check #896's resolution comment** — the runbook may be directing to mint the wrong token type. |
| 2 | Human admin | Verify with `gh workflow run railway-token-health.yml --repo alexsiri7/reli` before re-running the deploy. |
| 3 | Human admin | Re-run the failed pipeline: `gh run rerun 25250991058 --repo alexsiri7/reli --failed`. |
| 4 | Human admin | Confirm `Validate Railway secrets` passes; close #898 with the green run URL. |

> ⚠️ **Per `CLAUDE.md` Railway Token Rotation policy, agents cannot rotate this token.** No `.github/RAILWAY_TOKEN_ROTATION_898.md` will be created — that is a Category 1 error.

### Step 1: Human admin rotates the secret

**Action**: Replace the value of GitHub Actions secret `RAILWAY_TOKEN` in repo Settings → Secrets and variables → Actions with a freshly minted Railway API token.

**Why**: Railway has rejected the current token value. The validator step blocks the deploy until a token that authenticates against `backboard.railway.app/graphql/v2` is in place.

### Step 2: Verify the new token before re-running the deploy

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run watch <new-run-id> --repo alexsiri7/reli
```

**Why**: Catches a bad rotation (typo, wrong token type) before the staging pipeline burns another deploy slot on a token that won't authenticate.

### Step 3: Re-run the failed pipeline

```bash
gh run rerun 25250991058 --repo alexsiri7/reli --failed
gh run watch 25250991058 --repo alexsiri7/reli
```

**Why**: The original failure is in the validation step; nothing downstream ran. Re-running `--failed` resumes from the failed job with the new secret value.

---

## Patterns to Follow

This investigation follows the pattern established by the immediately preceding RAILWAY_TOKEN bead (issue #896, PR #897):

- Investigation artifact at `artifacts/runs/<run-id>/investigation.md` only.
- Routing comment posted on the GitHub issue.
- No `.github/RAILWAY_TOKEN_ROTATION_*.md` created (Category 1 guard).
- No workflow / runbook / source modifications (Polecat Scope Discipline).
- The runbook-revision hypothesis is already on record in #896 — do not re-litigate it here, just point to it.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Human rotates with the same (wrong-type) token; chain continues | Routing comment links to #896's runbook-revision hypothesis so the admin can consider switching to a project token. |
| Merging the implementation PR triggers another deploy on the still-dead token, producing a successor `Prod deploy failed on main` issue | Expected — documented here. The chain only stops once the secret is rotated correctly. The pickup cron is gated by the `archon:in-progress` label so duplicate work is prevented. |
| Agent accidentally creates `.github/RAILWAY_TOKEN_ROTATION_898.md` | Explicit Category 1 guard above; implementer must verify no such file is staged before committing. |
| Agent modifies the workflow or runbook beyond scope | Polecat Scope Discipline — out-of-scope ideas are mailed to mayor or noted as follow-ups, not implemented in this PR. |

---

## Validation

### Automated Checks

```bash
# After human rotation:
gh workflow run railway-token-health.yml --repo alexsiri7/reli
gh run rerun 25250991058 --repo alexsiri7/reli --failed
gh run watch 25250991058 --repo alexsiri7/reli
```

Expected: `Validate Railway secrets` step prints success and the downstream `Deploy staging image to Railway` step proceeds to `serviceInstanceUpdate` with no `errors`.

### Manual Verification

1. Confirm no new `.github/RAILWAY_TOKEN_ROTATION_898.md` file exists in the PR diff (Category 1 guard).
2. Confirm `.github/workflows/staging-pipeline.yml` and `docs/RAILWAY_TOKEN_ROTATION_742.md` are unmodified in the PR diff (Polecat scope).
3. Confirm the routing comment is posted on issue #898 with a link to the runbook.

---

## Scope Boundaries

**IN SCOPE:**
- Create `artifacts/runs/e0d0f9f1499c026f53b53cc5fcde48a5/investigation.md` (this document).
- Post a routing comment on issue #898.
- Update `MEMORY.md` only if a new durable lesson emerged (none did — this is the 58th identical incident).

**OUT OF SCOPE (do not touch):**
- `.github/workflows/staging-pipeline.yml` — the validator is correct; the failure is environmental.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — runbook revision is tracked as follow-up #1 from #896, not #898's bead.
- `RAILWAY_SECRETS.md` / `DEPLOYMENT_SECRETS.md` — same reason.
- Any `.github/RAILWAY_TOKEN_ROTATION_898.md` file — Category 1 error.
- Backend / frontend / Docker config — unrelated to the auth failure.
- Mailing mayor about the runbook-type-mismatch hypothesis — already mailed (or attempted) in #896's run.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-05-02T12:05:00Z
- **Run ID**: e0d0f9f1499c026f53b53cc5fcde48a5
- **Failing CI run**: https://github.com/alexsiri7/reli/actions/runs/25250991058
- **Failing SHA**: ed436e2911ff17b10dd916b27fd73c2e771a6fb4
- **Prior bead**: #896 / PR #897 (57th occurrence, 17th today)
- **Counter**: 58th RAILWAY_TOKEN rejection / 18th today / 10th in the 30-min-cadence chain
- **Artifact**: `/home/asiri/.archon/workspaces/ext-fast/reli/worktrees/archon/task-archon-fix-github-issue-1777723220968/artifacts/runs/e0d0f9f1499c026f53b53cc5fcde48a5/investigation.md`
