# Investigation: Deploy down: https://reli.interstellarai.net returning HTTP 000000

**Issue**: #758 (https://github.com/alexsiri7/reli/issues/758)
**Type**: BUG
**Investigated**: 2026-05-01T08:30:00Z

## Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | LOW | Original symptom (HTTP 000000) has cleared; production currently returns HTTP 200 on `/`, `/healthz`, `/api/health`. The active deploy-pipeline failure is already tracked under issue #836 (33rd RAILWAY_TOKEN expiration). |
| Complexity | LOW | No source-code change is appropriate. The actionable step is human-only token rotation; this investigation is docs-only and the issue is a duplicate that should be closed. |
| Confidence | HIGH | Live probes confirm the site is up; CI logs (run `25207459124`) confirm the underlying CI failure mode is `RAILWAY_TOKEN is invalid or expired: Not Authorized`, matching the established 33-cycle pattern documented in PRs #831–#838. |

---

## Problem Statement

Issue #758 reports a transient health-check failure (`HTTP 000000`) observed on **2026-04-28 03:00:32 UTC**. As of **2026-05-01 08:30 UTC** the production endpoint is healthy (HTTP 200, `{"status":"ok","service":"reli"}`). The issue has remained `archon:in-progress` and been re-queued repeatedly because no PR closes it; the prior investigation comment (2026-04-29) misdiagnosed the cause as an MCP `lifespan` hang. The actual recurring driver — expired `RAILWAY_TOKEN` — is already being tracked under separate issues (#833, #836) and is human-action-only per `CLAUDE.md`.

---

## Analysis

### Primitive Check

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Production app process (FastAPI / uvicorn) | `backend/main.py` | Yes | Live probe `GET /healthz` returns `{"status":"ok"}` — the running container is healthy. |
| CI deploy validator (Railway preflight) | `.github/workflows/staging-pipeline.yml:32-58` | Yes | The validator correctly fails fast on an expired token; the failure is the *signal*, not the *defect*. |
| `RAILWAY_TOKEN` GitHub Actions secret | external (Railway dashboard) | **No — operationally fragile** | Token has expired again (33rd occurrence). Structural improvement (Workspace=No workspace, Expiration=No expiration at creation) is tracked in #836's investigation; not in scope for #758. |
| Issue lifecycle (archon `in-progress` → re-queue) | issue label state | **Partial** | An open `archon:in-progress` issue with no PR is re-fired every few hours. Once the symptom resolves, the issue should be closed manually since no agent action will produce a PR. |

### Root Cause / Change Rationale

This issue is a **stale duplicate of an active tracking issue**, not a code defect.

### Evidence Chain

WHY: Issue #758 keeps being re-queued.
↓ BECAUSE: It is labeled `archon:in-progress` with no linked PR.
  Evidence: 12 auto-comments in `gh issue view 758` of the form *"archon was labeled in-progress Ns ago but no live run and no linked PR were found. Re-queued for another attempt."*

↓ BECAUSE: Prior investigation (2026-04-29 comment by Claude) proposed an MCP-lifespan code change but no implementation was produced; meanwhile the actual operational defect was a Railway-token expiration, which agents cannot rotate.
  Evidence: Prior comment text — *"ROOT CAUSE: The MCP session manager initialization added in commit `8d621893` may be deadlocking…"* — does not align with current production state (HTTP 200) nor with the recurring CI failure mode below.

↓ BECAUSE: The symptom that triggered #758 (`HTTP 000000` at 2026-04-28 03:00:32 UTC) was a transient outage during a Railway deploy window. The production process recovered, but CI deploy attempts continue to fail with an expired token.
  Evidence:
  - Live probe 2026-05-01 08:30 UTC: `curl https://reli.interstellarai.net/healthz` → `HTTP 200 {"status":"ok","service":"reli"}`.
  - Most recent `Staging → Production Pipeline` run `25207459124` (2026-05-01 08:04 UTC) failed at the *Validate Railway secrets* step: `##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized` (`.github/workflows/staging-pipeline.yml:55`).

↓ ROOT CAUSE: The active operational issue is the **33rd `RAILWAY_TOKEN` expiration**, already tracked under issue **#836** (and adjacent #833). Issue #758 itself describes a now-resolved transient symptom and is duplicate work. Per `CLAUDE.md > Railway Token Rotation`, agents cannot rotate the token; the only fix is a human action against railway.com.
  Evidence:
  - `gh run view 25207459124 --log-failed` → `RAILWAY_TOKEN is invalid or expired: Not Authorized` at `staging-pipeline.yml:55`.
  - `git log --oneline -20` shows 14+ recent commits that are investigation receipts for the same expiration pattern (`8a3f93a` → `ee9d0fb`, issues #800–#836).
  - `CLAUDE.md` (project root): *"Agents cannot rotate the Railway API token. … Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done. … Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the rotation runbook."*

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none) | — | NONE | No source code, workflow, config, runbook, or test should be modified by this investigation. The only change is producing this artifact and posting a status comment that recommends closing #758 as duplicate of #836. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — *Validate Railway secrets* step is the **detector**, not the defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — runbook for the human rotation step.
- Issue #836 — currently-open active tracking bead for the 33rd expiration; carries the latest PR receipt (#838) and the surfaced "No workspace" structural recommendation.
- Issue #833 — adjacent open tracking bead ("Prod deploy failed on main") for the same root cause.

### Git History

- **First filed**: #758 on 2026-04-28 (transient `HTTP 000000`).
- **Last comment activity on this issue**: 2026-05-01 07:31:25Z — auto-requeue from archon poller.
- **Adjacent activity**:
  - `ee9d0fb` (2026-05-01) — *docs: investigation for issue #836 (33rd RAILWAY_TOKEN expiration, 2nd pickup) (#838)*
  - `392291c` (2026-05-01) — *docs: investigation for issue #836 (33rd RAILWAY_TOKEN expiration) (#837)*
  - `3db8f1b` / `feb6609` (2026-05-01) — investigations for #832/#833.
- **Implication**: This is an established recurring pattern, not a regression in #758 itself. The cluster of investigations around the same root cause indicates that #758 should be **closed as duplicate of #836** to stop the requeue loop.

---

## Implementation Plan

There is **no code change** in scope. The plan has two human-only steps and one optional bookkeeping step.

### Step 1 (Human-only): Rotate `RAILWAY_TOKEN`

**Where**: https://railway.com/account/tokens
**Action**: Create a new account-level token.

**Settings to use** (per `docs/RAILWAY_TOKEN_ROTATION_742.md` and the structural finding from #836's investigation):
- **Workspace**: `No workspace` ← critical; suspected primary driver of the 33-cycle pattern.
- **Expiration**: `No expiration`.
- Name: `gh-actions-deploy-<YYYYMMDD>`.

Then update the GitHub Actions secret:

```bash
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token at the prompt.
```

Re-run the most recent failed deploy:

```bash
gh run rerun 25207459124 --repo alexsiri7/reli --failed
```

**Why**: This is the only action that unblocks CI deploy. It cannot be done by an agent — it requires interactive access to railway.com.

---

### Step 2 (Human-only): Close issue #758 as duplicate of #836

```bash
gh issue close 758 --repo alexsiri7/reli \
  --reason "not planned" \
  --comment "Symptom (HTTP 000000) has cleared; production is HTTP 200 as of 2026-05-01 08:30 UTC. The underlying recurring driver is the RAILWAY_TOKEN expiration cycle, currently tracked under #836 (33rd occurrence). Closing as duplicate to stop the archon requeue loop. See artifacts/runs/a5e81891df69badbc37d19cacc1c057a/investigation.md."
```

**Why**: Without closing, the `archon:in-progress` label on an issue with no possible PR will keep firing the poller every ~2.5 hours, generating noise comments without progress.

---

### Step 3 (Optional, agent-safe): Land this investigation artifact

This artifact (`artifacts/runs/a5e81891df69badbc37d19cacc1c057a/investigation.md`) is the only file produced. A docs-only PR following the same convention as #838 / #837 (`docs: investigation for issue #758 (deploy-down stale duplicate)`) is acceptable but optional — its function is purely documentary.

---

## Patterns to Follow

**From codebase — the established docs-only investigation pattern**:

```
# git log --oneline -10 (excerpt)
ee9d0fb docs: investigation for issue #836 (33rd RAILWAY_TOKEN expiration, 2nd pickup) (#838)
392291c docs: investigation for issue #836 (33rd RAILWAY_TOKEN expiration) (#837)
3db8f1b docs: investigation for issue #833 (32nd RAILWAY_TOKEN expiration) (#834)
```

Each PR in this pattern lands **only** files under `artifacts/runs/<run-id>/` and touches no source, workflow, config, runbook, or test. This investigation conforms to that pattern.

```python
# CLAUDE.md > Railway Token Rotation (verbatim policy)
# Agents cannot rotate the Railway API token. The token lives in GitHub
# Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
# When CI fails with `RAILWAY_TOKEN is invalid or expired`:
# 1. Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming
#    rotation is done.
# 2. File a GitHub issue or send mail to mayor with the error details.
# 3. Direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md` for the
#    rotation runbook.
```

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Production goes down again before the human rotates the token. | Already covered: the running container persists across CI failures (the validator gates *new* deploys, not the live process). If the live process crashes for an unrelated reason, no auto-redeploy will recover it until the token is rotated — file a separate `human-needed` issue if this happens. |
| Closing #758 obscures the original transient outage. | This artifact captures the original symptom (`HTTP 000000` at 2026-04-28 03:00:32 UTC) and the current healthy state, so the historical record is preserved in `artifacts/runs/`. |
| The prior (incorrect) MCP-lifespan investigation comment confuses future readers. | Step-2 close comment explicitly supersedes the 2026-04-29 comment by stating the symptom has cleared and pointing to the active tracking issue #836. |
| Agent attempts to apply the prior investigation's `backend/main.py` patch. | **Out of scope**. This artifact's "Scope Boundaries" section explicitly forbids touching `backend/main.py`. The prior comment's diagnosis is unsubstantiated — `/healthz` returns 200 right now without that change. |

---

## Validation

### Automated Checks

```bash
# 1. Confirm production is currently healthy.
curl -sf https://reli.interstellarai.net/healthz
# Expected: HTTP 200 with {"status":"ok","service":"reli"}

# 2. Confirm the CI failure mode is RAILWAY_TOKEN expiration (not something new).
gh run view 25207459124 --repo alexsiri7/reli --log-failed | grep -i "railway_token"
# Expected: ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized

# 3. Confirm there is no agent-rotatable secret in the repo.
git grep -n "RAILWAY_TOKEN" -- .github docs
# Expected: only references in workflow/runbook — no plaintext token.
```

### Manual Verification

1. After human rotates the token (Step 1), re-run the latest failed pipeline (`gh run rerun 25207459124 --failed`) and confirm the *Validate Railway secrets* step turns green.
2. After closing #758 (Step 2), confirm the archon poller stops emitting requeue comments on it (no new comment within ~3 hours).
3. Confirm production endpoints remain HTTP 200 across the rotation window.

---

## Scope Boundaries

**IN SCOPE:**
- Producing this investigation artifact under `artifacts/runs/a5e81891df69badbc37d19cacc1c057a/investigation.md`.
- Posting a single GitHub comment on #758 with the assessment and the close-as-duplicate recommendation.

**OUT OF SCOPE (do not touch):**
- `backend/main.py` (no MCP-lifespan change — the prior investigation's hypothesis is not supported by the current healthy state).
- `docker-compose.yml` (no `RELI_BASE_URL` change — same reason).
- `.github/workflows/staging-pipeline.yml` (the validator is working correctly; it is the detector, not the defect).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` (runbook updates are tracked under #836's follow-up beads; CLAUDE.md says do not create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file).
- Rotating `RAILWAY_TOKEN` (human-only — agents cannot perform this action).
- Closing the issue itself via API (close action belongs to the human as part of Step 2 to confirm the duplicate determination).

---

## Metadata

- **Investigated by**: Claude (model `claude-opus-4-7[1m]`)
- **Timestamp**: 2026-05-01T08:30:00Z
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/a5e81891df69badbc37d19cacc1c057a/investigation.md`
- **Workflow run-id**: `a5e81891df69badbc37d19cacc1c057a`
- **Production probe** (at investigation time): `GET https://reli.interstellarai.net/healthz` → `HTTP 200 {"status":"ok","service":"reli"}`
- **Active CI failure** (at investigation time): pipeline run `25207459124` red at `staging-pipeline.yml:55` — `RAILWAY_TOKEN is invalid or expired: Not Authorized`
- **Tracking issues**: #836 (33rd `RAILWAY_TOKEN` expiration — primary), #833 (adjacent — same cause)
- **Supersedes**: 2026-04-29 investigation comment on #758 (incorrectly attributed cause to MCP `lifespan` hang)
