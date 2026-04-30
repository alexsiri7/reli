# Investigation: Prod deploy failed on main

**Issue**: #762 (https://github.com/alexsiri7/reli/issues/762)
**Type**: BUG
**Investigated**: 2026-04-30T00:00:00Z

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Every push to `main` since 2026-04-27 has failed at the `Validate Railway secrets` pre-flight gate (5 consecutive runs); both daily Railway token health probes (Apr 28, Apr 29) also failed; nothing can ship until the token is rotated, but the workflow file itself is correct so no code-level workaround exists. |
| Complexity | LOW | The repository is healthy: no code change is needed. Resolution is a single GitHub Actions secret rotation performed via the existing runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`); the only "complexity" is that the action is gated on a human with Railway dashboard access. |
| Confidence | HIGH | The pre-flight code at `.github/workflows/staging-pipeline.yml:49-58` only emits the exact `RAILWAY_TOKEN is invalid or expired` string when Railway's `me{id}` probe rejects the token; the same string is reported by the cron health probe; this is the 5th identical failure (#733 → #739 → #742 → #755 → #762) — pattern, mechanism, and fix are all known. |

---

## Problem Statement

Production deploy run [25126991550](https://github.com/alexsiri7/reli/actions/runs/25126991550) on commit `eb6a432` failed at the `Validate Railway secrets` pre-flight step with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. The `RAILWAY_TOKEN` GitHub Actions secret has expired again. This is the **5th identical recurrence** of the same root cause; every staging-pipeline run on `main` since 2026-04-27 (5 runs) has failed at the same step, and the daily Railway token health probe has been red since 2026-04-28. **No code change is possible** — agents cannot rotate the token (CLAUDE.md § "Railway Token Rotation"). The deliverable is this investigation; resolution requires a human to rotate the token via the existing runbook.

---

## Analysis

### Root Cause / Change Rationale

The `RAILWAY_TOKEN` PAT stored in GitHub Actions secrets has reached its expiry date. Previous rotations (issues #733, #739, #742, #755) created tokens with finite TTL instead of selecting "No expiration" in the Railway dashboard, so each token expires within a few weeks and the same pre-flight gate blocks the next deploy. The pre-flight gate itself is working correctly — it is meant to fail fast with a human-readable message exactly when this happens.

### Evidence Chain

WHY: Production deploy run 25126991550 failed.
↓ BECAUSE: The job `Deploy to staging` failed at step `Validate Railway secrets`.
  Evidence: `gh run list --workflow staging-pipeline.yml` shows `conclusion: failure` for runs `25126991550, 25028112865, 25027090951, 25022304652, 25021921290` — every run since 2026-04-27.

↓ BECAUSE: A `curl` POST to `https://backboard.railway.app/graphql/v2` querying `me{id}` returned an unauthorized response.
  Evidence: `.github/workflows/staging-pipeline.yml:53-57`:
  ```bash
  if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
    MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
    echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  ```
  This is the only code path that emits the observed `RAILWAY_TOKEN is invalid or expired: Not Authorized` string.

↓ BECAUSE: Railway rejected the bearer token in `secrets.RAILWAY_TOKEN`.
  Corroborating evidence: `gh run list --workflow railway-token-health.yml` shows the daily probe is also failing — runs `25105119767` (Apr 29) and `25049349913` (Apr 28). The probe is independent of staging-pipeline triggering, so the failure is the secret value itself, not workflow plumbing.

↓ ROOT CAUSE: The token has reached its expiry date.
  Evidence: This is the 5th identical recurrence (#733, #739, #742, #755, #762). `docs/RAILWAY_TOKEN_ROTATION_742.md:18-21` documents the cause: "When creating tokens on Railway, the default TTL may be short … The new token must be created with **No expiration**." The recurrence cadence (~once every few weeks) is consistent with rotators having repeatedly accepted Railway's default finite TTL instead of selecting "No expiration." See web research finding #3 (`web-research.md:49-59`) for endpoint-level confirmation that "No expiration" is an available option in the Railway token UI.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| *(none in this repo)* | — | — | The repository is healthy. The fix is rotating the `RAILWAY_TOKEN` GitHub Actions secret; this happens outside the code. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step; first place to fail when token is invalid (working as designed).
- `.github/workflows/staging-pipeline.yml:60-78` — `Deploy staging image to Railway`; gated by the validate step, so it never runs while token is expired.
- `.github/workflows/railway-token-health.yml` — daily cron probe that calls the same `me{id}` query; gives early warning of expiration (already failing on Apr 28 and Apr 29 — warning fired but the rotation has not been performed).
- GitHub Actions secret `RAILWAY_TOKEN` (org/repo-level secret) — the actual artefact that needs rotation; not in the repo.
- Railway dashboard at https://railway.com/account/tokens — where the new token must be minted.
- Sister issue #751 — same root cause, still open; should be closed with #762 once deploy is green.

### Git History

- `docs/RAILWAY_TOKEN_ROTATION_742.md` — added during incident #742; covers exactly this rotation procedure.
- `bdc2651` (Apr 27) — `add weekly Railway token health check to prevent recurring deploy failures (#753)` (originally weekly).
- `6a0d232` (Apr 28) — `ci: run Railway token health check daily instead of weekly (#757)` — increased probe cadence in response to recurrences.
- `459f790` / `9b9ef96` (Apr 27) — removals of false rotation-completion docs (per CLAUDE.md prohibition).
- `eb6a432` (Apr 29) — `docs: add investigation for issue #755 (#761)`; this commit triggered run `25126991550` and is the SHA the issue cites — but it is *not* the cause; any commit landing during the token's expired window would have produced the same failure.
- **Implication**: The repository's instrumentation is doing exactly what it was designed to do — the daily probe is alerting, the pre-flight gate is failing fast, and the runbook exists. The recurring failure mode is a process gap (rotators accepting the default TTL), not a regression.

---

## Implementation Plan

> ⚠️ **No code change is required.** Per `CLAUDE.md` § "Railway Token Rotation": "Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com." Creating a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done is a **Category 1 error**. The implementation plan below is a **human action checklist**, not an agent-executable plan.

### Step 1: Mint a new Railway token (HUMAN)

**Where**: https://railway.com/account/tokens
**Action**: Create a new token with these settings:
- **Name**: `github-actions-permanent`
- **Expiration**: **No expiration** ← critical, do not accept the default TTL
- **Workspace**: select the workspace that owns the `reli` project (workspace token — narrowest viable scope for `me{id}` probes; see `web-research.md:23-30`)

**Why**: Web research finding #1 confirms Workspace tokens are Railway's official recommendation for shared CI; finding #3 confirms "No expiration" is what prevents the next recurrence.

---

### Step 2: Update the GitHub Actions secret (HUMAN)

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted
```

**Why**: This is the secret read by both `staging-pipeline.yml` and `railway-token-health.yml`. Same procedure as documented in `docs/RAILWAY_TOKEN_ROTATION_742.md:28-32`.

---

### Step 3: Verify rotation worked (EITHER agent or human)

```bash
gh workflow run railway-token-health.yml --repo alexsiri7/reli
# Wait ~30s, then:
gh run list --workflow railway-token-health.yml --repo alexsiri7/reli --limit 1
```

**Pass criterion**: The most-recent run shows `conclusion: success`. If still `failure`, the new token did not propagate or was minted with the wrong type — return to Step 1.

---

### Step 4: Unblock the failed deploy (EITHER)

```bash
gh run rerun 25126991550 --repo alexsiri7/reli --failed
```

**Pass criterion**: Run completes with `conclusion: success`. Production deploy then proceeds.

---

### Step 5: Close the duplicate issues (EITHER)

Close both #762 and #751 with a comment linking to the green run. Both have the same root cause and the same fix.

---

### Step N: No tests to add

No code is changing in this repo, so no test updates apply. The `railway-token-health.yml` daily cron probe **is** the regression test for this class of failure; it is already in place and is what surfaced the current expiration before users noticed.

---

## Patterns to Follow

**From the existing runbook — mirror these exactly:**

```markdown
# SOURCE: docs/RAILWAY_TOKEN_ROTATION_742.md:18-21
When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days).
Previous rotations may have used these defaults. **The new token must be created with
"No expiration".**
```

```bash
# SOURCE: docs/RAILWAY_TOKEN_ROTATION_742.md:28-32
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted
```

**From CLAUDE.md — what NOT to do:**

> Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done.
> File a GitHub issue or send mail to mayor with the error details.
> Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook.

---

## Edge Cases & Risks

| Risk/Edge Case | Mitigation |
|----------------|------------|
| Rotator picks the wrong token type (e.g., Project token instead of Workspace) | Step 3 (`railway-token-health.yml` rerun) fails fast — `me{id}` only succeeds with Account/Workspace tokens. |
| Rotator accepts default TTL again (6th recurrence) | Daily health probe (`railway-token-health.yml`) catches it ahead of the next deploy attempt; flag in PR-review checklist that "No expiration" must be confirmed. |
| Token leaks via accidental log of `$RAILWAY_TOKEN` | `staging-pipeline.yml:34, 54` only sends the token in headers; GitHub Actions auto-redacts known secret values from logs. No mitigation needed beyond not changing this. |
| Agent attempts to "fix" the workflow file thinking the YAML is the problem | The workflow is correct — failure is in the secret value. No edits to `.github/workflows/*.yml` are warranted by this incident. |
| Sister issue #751 is missed | Step 5 explicitly closes both #762 and #751. |
| Runbook drift (`docs/RAILWAY_TOKEN_ROTATION_742.md` says "third occurrence") | Cosmetic — the runbook is still correct on the actions to take. Out of scope for this fix; could be refreshed in a follow-up. |
| Endpoint cutover (Railway retires `backboard.railway.app` in favour of `.com`) | Future risk identified in `web-research.md:63-73`; would produce identical failure shape from a different root cause. **Out of scope** for this incident; file as separate follow-up issue once deploy is green. |

---

## Validation

### Automated Checks

```bash
# Verify the rotated token works against Railway:
gh workflow run railway-token-health.yml --repo alexsiri7/reli

# Verify the failed prod deploy now passes:
gh run rerun 25126991550 --repo alexsiri7/reli --failed

# Confirm both:
gh run list --repo alexsiri7/reli --workflow railway-token-health.yml --limit 1 --json conclusion
gh run list --repo alexsiri7/reli --workflow staging-pipeline.yml --limit 1 --json conclusion
```

Both must show `"conclusion":"success"`.

### Manual Verification

1. Visit https://railway.com/account/tokens and confirm the active token shows **No expiration**.
2. Confirm production deploy completed by checking the Railway dashboard for the new `eb6a432` (or later) image rollout.
3. Confirm both #762 and #751 are closed with a link to the green run.

---

## Scope Boundaries

**IN SCOPE:**
- This investigation artifact.
- The investigation comment already posted on issue #762 (Apr 29).
- Direction to the human rotator: use `docs/RAILWAY_TOKEN_ROTATION_742.md`, mint with "No expiration", select the workspace.

**OUT OF SCOPE (do not touch):**
- Editing `.github/workflows/staging-pipeline.yml` — workflow is correct; failure is in the secret value, not the YAML.
- Creating any `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming completion (CLAUDE.md Category 1 error).
- Switching `backboard.railway.app` → `backboard.railway.com` in workflow files (real future risk, but separate concern; file as follow-up).
- Migrating `RAILWAY_TOKEN` → `RAILWAY_API_TOKEN` (cosmetic; works as-is via raw `Authorization` header).
- Implementing OIDC federation (Railway has not published OIDC support; not currently feasible — see `web-research.md:77-89`).
- Two-secret rolling rotation pattern (overkill; daily probe already gives early warning).
- Refreshing `docs/RAILWAY_TOKEN_ROTATION_742.md` to say "fifth occurrence" — cosmetic; runbook actions remain correct.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-04-30T00:00:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/investigation.md`
- **Companion**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/7aff677993bdaf14206873cdd7ba86aa/web-research.md`
- **Prior investigation comment**: https://github.com/alexsiri7/reli/issues/762#issuecomment-4347686287 (Apr 29) — same conclusions; this artifact supersedes it with confirmation that the failure is still active 1 day later (5 consecutive failed pipeline runs, 2 consecutive failed health probes).
