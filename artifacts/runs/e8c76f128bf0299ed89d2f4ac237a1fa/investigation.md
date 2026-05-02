# Investigation: Prod deploy failed on main (RAILWAY_TOKEN rejected — 57th occurrence)

**Issue**: #896 (https://github.com/alexsiri7/reli/issues/896)
**Type**: BUG (infrastructure / secret rotation — recurring)
**Investigated**: 2026-05-02T11:35:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod deploy is fully blocked at the `Validate Railway secrets` pre-flight (no workaround in CI; manual deploys still possible). No data loss or security exposure — recurring infra issue with a documented routing path; identical to 56 prior incidents. |
| Complexity | LOW | Zero code changes for this bead. Recovery is a human-only `RAILWAY_TOKEN` secret update via railway.com → repo Settings; per `CLAUDE.md` agents must not attempt it. |
| Confidence | HIGH | Run [25250485076](https://github.com/alexsiri7/reli/actions/runs/25250485076) logs the exact failure (`RAILWAY_TOKEN is invalid or expired: Not Authorized` from `backboard.railway.app/graphql/v2 {me{id}}`) at 2026-05-02T11:04:50Z; identical signature to 56 prior incidents (#742 → … → #894). Inter-arrival from #894 is exactly 30 min — perfect cadence match. |

---

## Problem Statement

The `Deploy to staging` job in run [25250485076](https://github.com/alexsiri7/reli/actions/runs/25250485076) failed at the **Validate Railway secrets** step at 2026-05-02T11:04:50Z. Railway's GraphQL API responded `Not Authorized` to the `{me{id}}` validation probe — the `RAILWAY_TOKEN` GitHub Actions secret is rejected. This is the **57th** RAILWAY_TOKEN rejection tracked on this repo and the **17th today**, arriving exactly **30 minutes** after #894 was filed (#894 at 11:00:18Z → #896 at 11:30:24Z). The ~30-minute inter-arrival now holds across **nine** consecutive incidents (#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896). The deploy SHA (`b4b2daa5d5547922d96895a42582832d6bcfabd5`) is itself the merge of the prior #891 investigation PR — every docs-merge-triggered deploy hits the same dead token. Rotation tracker #889 was filed by `railway-token-health.yml` earlier today and has since been **closed**, so there is no currently-open Railway-token tracker issue at the time of investigation.

---

## Analysis

### Root Cause / Change Rationale

**Surface root cause**: the token in the `RAILWAY_TOKEN` GitHub Actions secret is rejected by Railway's GraphQL API. The validator at `.github/workflows/staging-pipeline.yml:32-58` correctly fails fast (intended fail-safe — no code regression). The fix lives entirely outside the repo: a human with railway.com access must mint a new token and update the GitHub secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`.

**Deeper root cause hypothesis (NEW — see web-research.md in this run)**: 9 consecutive rejections at a clockwork ~30-minute cadence is **not** consistent with token expiration. Per Railway's own docs (Public API page, Login & Tokens page), account/workspace/project API tokens are presented as long-lived persistent credentials with **no documented default TTL**. The Railway Help Station thread "RAILWAY_TOKEN invalid or expired" (cited in `web-research.md` § 3) flags the "expired" wording as a misleading catch-all for **any** auth failure — most commonly **token-type mismatch** between what `RAILWAY_TOKEN` actually requires (per the official Railway GitHub-Actions blog: a **project token**, minted from project settings) and what `docs/RAILWAY_TOKEN_ROTATION_742.md` directs the human to mint (an **account token** at https://railway.com/account/tokens). If past rotations have minted an account token but the workflow needs a project token (or vice versa), the same "expired" message will recur on every rotation. This is also consistent with #889's same-day rotation tracker being closed without ending the chain — the human likely rotated the token, but a like-for-like swap from the runbook does not address the mis-typing.

This hypothesis is **not a fix for #896** — it is a hand-off to mayor for runbook revision (see "Follow-up" below).

### Evidence Chain

WHY: Prod deploy run 25250485076 failed at 2026-05-02T11:04:54Z.
↓ BECAUSE: The `Deploy to staging` workflow exited 1 at the `Validate Railway secrets` step.
  Evidence: `##[error]Process completed with exit code 1.` at `2026-05-02T11:04:50.5932168Z` (run 25250485076 logs, captured in this conversation's Phase 1 fetch).

↓ BECAUSE: The validator's GraphQL probe to `backboard.railway.app/graphql/v2` returned `Not Authorized`.
  Evidence: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` at `2026-05-02T11:04:50.5920618Z`. `.github/workflows/staging-pipeline.yml:49-58` posts `{"query":"{me{id}}"}` and exits 1 if `.data.me.id` is missing.

↓ BECAUSE: Railway's GraphQL endpoint rejected the bearer token.
  Evidence: identical failure signature to 56 prior issues (#742, …, #894), all resolved by rotating the secret value via railway.com.

↓ ROOT CAUSE (surface): The `RAILWAY_TOKEN` GitHub Actions secret holds a rejected Railway API token.
  Evidence: same secret feeds `staging-pipeline.yml` (deploy validator), `railway-token-health.yml` (daily monitor), and downstream deploy step `Deploy staging image to Railway`. The secret value, not the validator code, is at fault.

↓ ROOT CAUSE (deeper, hypothesis only): The token *type* required by `RAILWAY_TOKEN` and the type the runbook directs humans to mint are mismatched. The 30-min clockwork cadence cannot be explained by ordinary expiration. See `web-research.md` § 3, § 4 in this same run dir.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | — | No code changes for this bead. Fix is a GitHub Actions **secret value** rotation performed by a human admin via railway.com → repo Settings → Secrets and variables → Actions. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (where the failure surfaces; the `me{id}` GraphQL probe).
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` step (gated by validator; would fail the same way if reached, since it uses the same `Authorization: Bearer $RAILWAY_TOKEN`).
- `.github/workflows/railway-token-health.yml` — independent token-health probe (daily 09:00 UTC cron); will also fail on the same secret until rotated.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook; **may itself be incorrect re: token type** (see Follow-up).
- GitHub repo Settings → Secrets and variables → Actions → `RAILWAY_TOKEN` (where the value lives).
- railway.com (account vs project token UIs) — where the new token is minted.
- `pipeline-health-cron.sh` — the external cron that filed this issue (third alerting path; complements the in-repo `staging-pipeline.yml` validator and `railway-token-health.yml` daily monitor).

### Git History

- **Failing SHA**: `b4b2daa5d5547922d96895a42582832d6bcfabd5` — itself the merge of PR #892 (the prior #891 investigation). Docs-only; cannot have caused this. Confirms it is the secret value, not any new code.
- **Validator step provenance**: `.github/workflows/staging-pipeline.yml:32-58` has been stable since `0040535` (#744). Auth-check pattern was added in `3dfb995` (#738). Neither is recent.
- **Today's chain (`Prod deploy failed on main`, all filed by `pipeline-health-cron.sh`)**: #858, #860, #862, #864, #866, #868, #871, #874, #876, #878, #880, #882, #884, #886, #888, #891, #894, #896 — eighteen filings, of which `#896` is the 17th to be picked up by an investigation bead (#874 was a duplicate-pickup that did not get its own counter slot).
- **Inter-arrival**: nine consecutive incidents at ~30-minute clockwork (#878 11:30Z prior day → #880, #882, #884, #886, #888, #891, #894, #896 today on a strict half-hour grid). Earlier today the cadence was wider; the half-hour rhythm aligns with the `pipeline-health-cron.sh` schedule, which means the deploys themselves are continuously failing and the cron is spotting each fresh failure on its next sweep — not that token churn is increasing.
- **Implication**: Long-lived structural issue. The cron-aligned cadence is the strongest evidence yet that the repeated rotations are not landing the right token type (or that no human rotation has occurred since #889 was closed). Either way, the bead-level action remains the same: route to the runbook and let a human act.

---

## Implementation Plan

> **Agent-side: NO CODE CHANGES.** Per `CLAUDE.md` § "Railway Token Rotation":
> > Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. File a GitHub issue or send mail to mayor with the error details. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
>
> Producing such a marker file would be a Category 1 error.

### Step 1: Document the failure (agent action — this artifact)

**File**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/e8c76f128bf0299ed89d2f4ac237a1fa/investigation.md`
**Action**: CREATE (this file)

Captures the failing run URL, exact error string, runbook pointer, prior-occurrence count, and the new web-research-derived hypothesis that the recurring failures may be token-type mismatch rather than expiration. The companion `web-research.md` in the same directory is the citation source for the hypothesis.

### Step 2: Post a single routing comment on #896 (agent action)

Use `gh issue comment 896` with a formatted summary directing the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`. **Include a one-line hand-off** noting that `web-research.md` in this run dir suggests the runbook itself may need a token-type review; the comment must not claim agent rotation, must not link to a `RAILWAY_TOKEN_ROTATION_896.md` file (it MUST NOT exist), and must not duplicate routing comments on sibling issues.

### Step 3: Human admin rotates the RAILWAY_TOKEN secret (NOT an agent action)

Per `docs/RAILWAY_TOKEN_ROTATION_742.md`:

1. Log into railway.com.
2. Mint a new API token. **Before re-using the runbook verbatim**, see the open question in `web-research.md` § 3-4: the runbook currently directs to https://railway.com/account/tokens (account-scoped), but the official Railway GitHub-Actions blog uses a **project token** in `RAILWAY_TOKEN`. The 9-incident clockwork chain suggests this mismatch may be the actual root cause. If a human can verify which type the workflow needs, do that **before** re-running the rotation; otherwise rotate per the existing runbook to unblock prod and capture a follow-up.
3. In GitHub: repo Settings → Secrets and variables → Actions → update `RAILWAY_TOKEN` with the new value.
4. Verify with the daily check before rerunning the deploy:
   ```bash
   gh workflow run railway-token-health.yml --repo alexsiri7/reli
   gh run watch <new-run-id> --repo alexsiri7/reli
   ```
5. Re-run the failed pipeline:
   ```bash
   gh run rerun 25250485076 --repo alexsiri7/reli --failed
   gh run watch 25250485076 --repo alexsiri7/reli
   ```
6. Confirm the `Validate Railway secrets` step passes; close #896 with the green run URL.
7. (Optional) Revoke the previous token in Railway after the new one verifies green.

### Step 4: Mail mayor about the runbook hypothesis (agent action — Polecat hand-off)

Send a `gt mail send mayor/` note flagging that 9 consecutive 30-min-cadence rejections + Railway's own docs (no documented TTL) + Railway-staff guidance that `RAILWAY_TOKEN` needs a *project* token together suggest `docs/RAILWAY_TOKEN_ROTATION_742.md` may direct humans to mint the wrong token type. The mail asks mayor to either (a) confirm the runbook is correct and the chain is unrelated, or (b) commission a runbook-revision bead. **The mail does not propose the fix in #896's PR** — Polecat Scope Discipline keeps the runbook change separate.

---

## Patterns to Follow

The most recent precedent — `artifacts/runs/594db19c756acf05e346a8d70e5a6a19/investigation.md` (issue #894) — is the template this artifact mirrors. The runbook at `docs/RAILWAY_TOKEN_ROTATION_742.md` is the canonical procedure; do not duplicate or fork it.

The new element here (vs #894) is the explicit incorporation of `web-research.md` findings already present in this run dir. That research was prepared before this investigation and identifies the type-mismatch hypothesis; the investigation surfaces it and routes it to mayor without acting on it.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Cron re-fires #896 before rotation completes | Issue carries `archon:in-progress`; the pickup cron skips while that label is present. Do not strip the label until the deploy goes green. |
| Two agents pick up #896 in parallel | Pre-flight reads the issue's existing comments; skip if any agent comment is present. |
| Agent creates `.github/RAILWAY_TOKEN_ROTATION_896.md` | Forbidden — Category 1 error per `CLAUDE.md`. This artifact reiterates it. |
| Agent edits `staging-pipeline.yml` / `railway-token-health.yml` to bypass the validator | Forbidden — the validator is correct; the failure is data, not code. Suppression would mask a real outage. |
| Agent edits `docs/RAILWAY_TOKEN_ROTATION_742.md` to incorporate the type-mismatch hypothesis | Out of scope for #896. Surface as mail to mayor; runbook revision is a separate bead. |
| New token verifies green but next deploy still fails | Likely a separate issue (revoked service ID, image registry permissions). Re-investigate from logs; do not assume same root cause. |
| Token rotation lands while this bead is in flight (next cron tick goes green) | Switch the routing comment to a "resolved by rotation at <ts>" form, still commit the artifact for audit trail. |
| Mail to mayor duplicates an earlier same-day mail (the runbook-revision angle was already raised on #886/#888 per their commit messages) | Pre-flight `gt mail` for the address `mayor/` and verify no equivalent in-flight mail exists; only send if the new evidence (9-incident chain, runbook conflict citations) is materially additive. |
| Deploy SHA mismatch: the merge of #891's PR (b4b2daa) is the failing SHA, but the merge of #892 (this run's bead's parent), if any, will deploy after this PR | Each merge to main triggers a fresh deploy; the chain will only stop when a human rotates the secret correctly. The PR for this investigation will trigger another failed deploy and a likely #897. Note this in the PR body so the next investigator does not double-count. |

---

## Validation

### Automated Checks

```bash
# Agent-side: docs-only diff. Standard suite is vacuously passing.
# The actual signal lives in the deploy pipeline, which only goes green
# AFTER the human rotates the token (and possibly the type):
gh workflow run railway-token-health.yml --repo alexsiri7/reli   # post-rotation sanity check
gh run rerun 25250485076 --repo alexsiri7/reli --failed
gh run watch 25250485076 --repo alexsiri7/reli
```

### Manual Verification (post-rotation)

1. The re-run of [25250485076](https://github.com/alexsiri7/reli/actions/runs/25250485076) reaches the `Deploy staging image to Railway` step and exits 0 (or, if the runbook hypothesis is right, the validator query is replaced first and the new probe succeeds).
2. `railway-token-health.yml` next scheduled run reports green.
3. Next merge to `main` triggers a green pipeline (closes #896).
4. The `pipeline-health-cron.sh` external cron's next sweep does not file a successor `Prod deploy failed on main` issue.

---

## Scope Boundaries

**IN SCOPE (agent, this bead):**
- Investigate the failed run, identify the recurring root cause, surface the new web-research hypothesis.
- Produce this investigation artifact under `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/e8c76f128bf0299ed89d2f4ac237a1fa/investigation.md`.
- Post one routing comment on #896 directing a human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.
- Send one mail to `mayor/` flagging the runbook-revision hypothesis (Polecat hand-off).

**OUT OF SCOPE (do not touch):**
- Rotating the Railway API token (humans only — `CLAUDE.md` policy).
- Creating any `.github/RAILWAY_TOKEN_ROTATION_896.md` file (Category 1 error per `CLAUDE.md`).
- Editing `.github/workflows/staging-pipeline.yml` or `railway-token-health.yml` (alarm logic is correct; failure is data).
- Editing `docs/RAILWAY_TOKEN_ROTATION_742.md` (runbook-revision is a separate bead — surface as mail to mayor).
- Re-recommending project-scoped credential / OIDC / autodeploy migration in #896's PR — those have been escalated on prior incidents; mayor mail acknowledges, does not re-recommend in code.
- Reopening or commenting on #886, #888, #889, #891, #894, or any closed sibling.
- Any frontend, backend, or DB changes — this is purely a secret-rotation incident.

### Follow-up (separate issue / mayor mail)

Nine consecutive ~30-minute-cadence rejections + Railway's published token-lifetime docs + the `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` and account-vs-project-token conflict in Railway's own documentation (see `web-research.md` § 3-5) constitute strong evidence that **the runbook itself is directing humans to the wrong token type**, not that tokens are expiring. A separate bead should:

- Mint a project token from Railway project settings, store it in a scratch GitHub secret, and run the validator's `{me{id}}` probe against it in isolation. Confirm whether the probe is even compatible with project tokens (it likely is not, since project tokens have no user identity).
- Either (a) update the runbook to direct humans to the project-token UI **and** replace the validator's `{me{id}}` probe with a project-scoped query, or (b) document why the account-token approach is correct despite the official-blog conflict.
- Evaluate Railway's GitHub-App autodeploy as an alternative (no GitHub Secret needed; trade-off is loss of custom validation gates).

This is mayor's call — not addressed in #896's PR.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T11:35:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/e8c76f128bf0299ed89d2f4ac237a1fa/investigation.md`
- **Companion artifact (web research, prepared before this investigation)**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/e8c76f128bf0299ed89d2f4ac237a1fa/web-research.md`
- **Failing run**: https://github.com/alexsiri7/reli/actions/runs/25250485076
- **Failing SHA**: `b4b2daa5d5547922d96895a42582832d6bcfabd5` (merge of PR #892, the prior #891 investigation — docs-only)
- **Source workflow**: `.github/workflows/staging-pipeline.yml` (job: `Deploy to staging`; failing step: `Validate Railway secrets`)
- **Filer**: `pipeline-health-cron.sh` (external cron; sibling alerting paths are `staging-pipeline.yml` and `railway-token-health.yml`)
- **Prior occurrences**: 56 (this is #57; 17th in the same-day chain; 9th in the 30-min-cadence sub-chain)
- **Sibling open issues at investigation time**: none open (#889 was closed before this investigation; #896 is the only open archon-tagged Railway-token issue)
- **Runbook**: `docs/RAILWAY_TOKEN_ROTATION_742.md`
