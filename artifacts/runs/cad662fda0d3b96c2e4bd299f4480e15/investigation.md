# Investigation: Prod deploy failed on main (#841 — 2nd pickup; 35th `RAILWAY_TOKEN` validator-rejection cycle)

**Issue**: #841 (https://github.com/alexsiri7/reli/issues/841)
**Type**: BUG
**Investigated**: 2026-05-01T15:10:00Z
**Workflow**: `cad662fda0d3b96c2e4bd299f4480e15`
**Predecessor**: 1st pickup of #841 — workflow `8531a0fb983e22588f40e6f43484ee47`, PR #842 (merged 12:30:32Z)

---

## Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod auto-deploy on every push to `main` is *still* broken at `Validate Railway secrets`. The latest failing run `25215295472` (13:04:42Z, on SHA `c42a83b` — the merge commit of PR #842, the 1st pickup of this very issue) makes 9 consecutive identical-shape reds on `main` since 03:35Z and confirms the secret has not been rotated since the 1st pickup merged. `Deploy to production` is `skipped` on every merge. HIGH (not CRITICAL) because the documented human-only rotation workaround is unchanged. |
| Complexity | LOW | A single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`, with the pre-save verification curl from the 1st pickup. No code, workflow, or runbook edit is in scope. Agents are forbidden from rotating per `CLAUDE.md > Railway Token Rotation`. |
| Confidence | HIGH | The evidence chain is unchanged from the 1st pickup, with one strengthening signal: the new red run `25215295472` lands on PR #842's merge SHA itself, which means the validator is still emitting the same `RAILWAY_TOKEN is invalid or expired: Not Authorized` diagnostic at `.github/workflows/staging-pipeline.yml:55`. The independent `Railway Token Health Check` workflow `25211139148` at 10:27:15Z also failed in the same shape. Web-research re-validation (this run's `web-research.md`, 18 sources total) finds **no upstream change** that would alter the recommendation. |

---

## Problem Statement

`RAILWAY_TOKEN` remains expired or wrong-class. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` issues `Authorization: Bearer $RAILWAY_TOKEN` against Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, exits 1, and `Deploy to production` is skipped. Issue #841 is the only remaining open issue in the cluster (siblings #833, #836, #832 all closed); a single human rotation closes it.

This is the **2nd pickup of #841** (pickup cron re-queue at 14:00:59Z with the same `archon was labeled in-progress 7206s ago but no live run and no linked PR were found` message). PR #842 from the 1st pickup landed two artifacts (investigation + web-research) but did not unblock CI — by design, since rotation is human-only.

---

## Analysis

### What's Different Since the 1st Pickup (Δ in ~3 hours)

| Signal | 1st pickup (12:15Z) | 2nd pickup (15:10Z) | Significance |
|--------|---------------------|---------------------|--------------|
| Sibling #832 | closed 04:30Z | closed 04:30Z | unchanged |
| Sibling #833 | closed 09:30Z (auto-closed by PR #840 merge) | closed 09:30Z | unchanged |
| Sibling #836 | open (2 prior pickups) | **closed 13:00:16Z** (auto-closed by PR #842 merge — the 1st pickup of #841) | new — only #841 remains open |
| Failed `Staging → Production Pipeline` runs on `main` since 03:35Z | 8 (last on `da29247`) | **9** (added `25215295472` on `c42a83b` at 13:04:42Z) | +1 — new merge SHA, same shape |
| Failed `Railway Token Health Check` since 1st pickup | (not separately enumerated) | **1** (`25211139148` at 10:27:15Z, same shape) | independent confirmation |
| `RAILWAY_TOKEN` rotated | no | no | unchanged |
| Open siblings | 3 | **1** (#841) | concentrating on #841 |
| Web-research sources | 15 | 18 | re-validated; +3 new sources, none change recommendation |

### First-Principles: Primitive Soundness (carried forward)

The three primitives identified in the 1st pickup remain unsound in the same ways. No structural change has shipped in the last 3 hours.

| Primitive | File:Lines | Sound? | Δ since 1st pickup |
|-----------|-----------|--------|--------------------|
| Secret-validator probe | `.github/workflows/staging-pipeline.yml:49-58` | Partial (single-string diagnostic conflates ≥3 failure modes) | unchanged |
| Token rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Partial (`/account/tokens` URL + unverified TTL claim) | unchanged |
| Issue/pickup taxonomy (3 crons opening overlapping issues) | n/a | Partial | one fewer open sibling, but same loop is still live |

The structural fix has been mailed-to-mayor in prior cycles (per PR #840) and is **deliberately not re-mailed** per `CLAUDE.md > Polecat Scope Discipline`.

### Root Cause / Change Rationale (carried forward, restated against latest run)

**Process / human-action defect, not a code defect.** The full rationale is in the 1st-pickup investigation at `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/investigation.md` §"Root Cause / Change Rationale" — restated here against the latest failing run for clarity:

### Evidence Chain

```
WHY: Run 25215295472 (latest, 13:04:42Z on SHA c42a83b — the merge of PR #842,
     the 1st pickup of THIS issue) failed.
↓ BECAUSE: "Deploy to staging" → "Validate Railway secrets" exited 1.
  Evidence: gh run view 25215295472 jobs[0].steps →
    {name:"Validate Railway secrets", conclusion:"failure"}
    {name:"Deploy staging image to Railway", conclusion:"skipped"}
    {name:"Deploy to production", conclusion:"skipped"}

↓ BECAUSE: Railway GraphQL {me{id}} returned no data.me.id.
  Evidence: .github/workflows/staging-pipeline.yml:55 emits
            "RAILWAY_TOKEN is invalid or expired: <message>" only on this
            branch. Same job shape as the 1st pickup's run 25209787350.

↓ ROOT CAUSE (immediate): RAILWAY_TOKEN GitHub Actions secret remains
  expired or wrong-class. Not rotated since the original 03:35Z incident.
  Evidence: 9 consecutive failed main runs since 03:35Z on 6 distinct
            merge SHAs (d01d31c, 3db8f1b, 392291c, ee9d0fb, 76b58f5,
            da29247, c42a83b). The 1st-pickup PR #842 — which merged at
            12:30:32Z and is itself the SHA of the new failure — landed
            no rotation (rotation is human-only by design and out of
            scope for any agent run). The Railway Token Health Check
            cron (25211139148, 10:27:15Z) also failed in the same shape.

↓ ROOT CAUSE (structural, recurring 35×): per the 1st pickup's web-research
  Findings 1–2 (still cited verbatim in this run's web-research.md) and
  this run's new Finding N4 (Railway's GitHub Actions PR Environment guide
  re-confirming RAILWAY_API_TOKEN + workspace-blank as the official
  pattern), the env-var name RAILWAY_TOKEN only authenticates a Project
  Token (Project-Access-Token header) in modern Railway. The validator's
  Authorization: Bearer + {me{id}} shape only accepts account/workspace
  tokens. The mismatch means rotations at /account/tokens with a
  workspace selected produce tokens that fail the validator with the
  same "invalid or expired" string — explaining the 35× recurrence.
  Structural fix already mailed-to-mayor; not re-mailed here.
```

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/cad662fda0d3b96c2e4bd299f4480e15/investigation.md` | NEW | CREATE | This 2nd-pickup investigation. |
| `artifacts/runs/cad662fda0d3b96c2e4bd299f4480e15/web-research.md` | (already authored at canonical path, 15:05Z) | CARRY-FORWARD | Web-research delta (3 new sources; 18 total). Already in canonical workspace. |

**Deliberately not changed** (carried forward from 1st pickup, plus this run's reasoning):

- `.github/workflows/staging-pipeline.yml` — fails closed correctly; editing during an active incident would mask the unrotated-secret signal.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — runbook corrections are tracked in mayor's queue from prior cycles. Per scope discipline, do not edit here.
- **No `.github/RAILWAY_TOKEN_ROTATION_841.md`** — Category 1 error per `CLAUDE.md > Railway Token Rotation`.
- **No re-mail to mayor** — PR #840's test plan and the 1st pickup of #841 (PR #842) both explicitly say *"do not re-mail"*; the structural fix is already in mayor's queue.
- **No new GitHub issue filed** — #841 is open and accurate; one rotation closes it.

### Integration Points

(Unchanged from 1st pickup — restated for completeness.)

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step (the gate currently rejecting the token).
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` (also depends on `RAILWAY_TOKEN`; would also fail without rotation).
- `.github/workflows/railway-token-health.yml` — independent health-check workflow whose latest run (`25211139148`, 10:27Z) confirms the token is rejected. Useful for the human to verify a freshly rotated secret before touching the deploy pipeline.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook referenced from `CLAUDE.md`.
- `pipeline-health-cron.sh` — the cron that filed #841. Will refile a 36th-cycle issue on each subsequent failed deploy until `Deploy to production` reaches Railway green.

### Git History

- **Original failing run cited by sibling #833**: `25201008471` at 03:35:29Z on SHA `d01d31c`.
- **Issue #841's filing run**: `25209787350` at 09:34:51Z on SHA `da29247` (PR #840's merge).
- **This pickup's latest failing run**: `25215295472` at 13:04:42Z on SHA `c42a83b` (PR #842's merge — the 1st pickup of #841).
- **Token-health cron failure (independent)**: `25211139148` at 10:27:15Z, same shape.
- **9 consecutive identical-shape main reds** since 03:35Z on 6 distinct merge SHAs.
- **Sibling-issue lineage (current state, all verified via `gh issue view`):**
  - **#832** — 32nd recurrence, staging-side framing. Closed 04:30:12Z.
  - **#833** — 32nd recurrence, deploy-down framing. Closed 09:30:10Z (auto-closed by PR #840 merge).
  - **#836** — 33rd recurrence, CI-red framing on next-day SHA. Closed 13:00:16Z (auto-closed by PR #842 merge — the 1st pickup of #841).
  - **#841** (this) — 34th recurrence, prod-deploy framing on PR #840's merge SHA. **Open, in-progress.** This is the 2nd pickup.
  - **#629** — Railway migration (long-term, separate).

---

## Implementation Plan (HUMAN-ONLY)

The plan is identical to the 1st pickup, with the run number updated to the latest red.

| Step | Where | Action |
|------|-------|--------|
| 1 | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Read end-to-end. Note: per the 1st pickup's web-research Findings 1–2 and this run's Finding N4, the env-var name `RAILWAY_TOKEN` is upstream-documented to accept only Project Tokens; the validator's existing `Authorization: Bearer` + `{me{id}}` shape requires an *account-scoped* token (workspace blank). Do NOT pick a workspace at `/account/tokens`. |
| 2 | Local terminal — pre-save verification | `curl -sf -X POST https://backboard.railway.app/graphql/v2 -H "Authorization: Bearer <NEW_TOKEN>" -H "Content-Type: application/json" -d '{"query":"{me{id}}"}' \| jq '.data.me.id'` — must return a non-null string. If null/error, the token is wrong-class for the validator — discard and retry. |
| 3 | Local terminal | `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the verified token. |
| 4 | Local terminal | `gh run rerun 25215295472 --repo alexsiri7/reli --failed`. If rejected (e.g., run too old to rerun by then), push a no-op commit to `main` to trigger a fresh `Staging → Production Pipeline` run on the new HEAD. |
| 5 | GitHub | Once `Validate Railway secrets` passes, `Deploy staging image to Railway` reaches Railway, `Wait for staging health` returns ok, `Deploy to production` proceeds, and `/healthz` on `RAILWAY_PRODUCTION_URL` returns `{"status":"ok"}` — close **#841**. (Siblings #832, #833, #836 are already closed.) Confirm `railway-token-health.yml` next scheduled run goes green. |

> ⚠️ **Do NOT create `.github/RAILWAY_TOKEN_ROTATION_841.md`** — Category 1 error per `CLAUDE.md > Railway Token Rotation`.
>
> ⚠️ **Do NOT re-mail mayor** — the structural fix (env-var rename to `RAILWAY_API_TOKEN`, validator that distinguishes wrong-class vs expired tokens, scheduled secret-validation cron, GitHub OIDC federation) is already in mayor's queue from prior cycles.

---

## Patterns to Follow

The validator at `.github/workflows/staging-pipeline.yml:49-58` is the contract a fresh token must satisfy — verify against it before storing. Snippet (unchanged from 1st pickup):

```bash
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  exit 1
fi
```

A token that returns a non-null `data.me.id` against this probe is, by construction, accepted by the validator.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Run `25215295472` is too old to rerun by the time the human acts | Step 4 fallback: push a no-op commit to `main` to trigger a fresh `staging-pipeline.yml` run. |
| Pickup cron re-fires #841 (3rd pickup) before the human rotates | Expected per the cron's "no live run + no linked PR" heuristic at the same 7200s threshold. The 3rd pickup will reach the same conclusion. This artifact already documents it; the next pickup's investigation can be even shorter. |
| `pipeline-health-cron.sh` files a 36th-cycle issue on the merge SHA of *this* PR | Possible if the human has not rotated by the time this PR merges. Resolution is identical (same root cause, same fix). The cron-deduplication / structural fix is already in mayor's queue; do not re-mail. |
| Rotator selects a workspace at `/account/tokens` | Pre-save verification curl in Step 2 surfaces the rejection before the secret is stored. |
| Rotator creates a Project Token (web-research Finding 2) and stores it in `RAILWAY_TOKEN` | Pre-save curl will fail because Project Tokens use `Project-Access-Token` header, not `Authorization: Bearer`. Recommend an account-scoped token with workspace blank for the existing validator's shape. |
| Runbook's "1-day/7-day TTL" guidance leads the rotator to expect another expiration in days | Per web-research Finding 5 (1st pickup) — re-validated this pickup — no Railway public doc supports a TTL on Project/Account/Workspace tokens. Repeated expirations are likely scope/type mismatches. |
| Railway-side platform incident masquerades as token issue | Per this pickup's new Finding N1 (Railway's official Jan 28-29 incident report), check Railway status before assuming rotation is the only path. The current reli failures match the validator-rejection shape, not a Railway-side outage shape, so rotation remains the correct first action. |

---

## Validation

### Automated checks (post-rotation, human-run)

```bash
gh run rerun 25215295472 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN
gh run list --repo alexsiri7/reli --workflow railway-token-health.yml --limit 1
```

Expected sequence: `Validate Railway secrets` passes → `Deploy staging image to Railway` reaches Railway → `Wait for staging health` returns ok → `Deploy to production` proceeds → `/healthz` on `RAILWAY_PRODUCTION_URL` returns `{"status":"ok"}` → next scheduled `railway-token-health.yml` goes green.

### This pickup's validation (pre-rotation)

Diff is docs-only (one new investigation artifact + the pre-existing canonical web-research.md, both at `artifacts/runs/cad662fda0d3b96c2e4bd299f4480e15/`). N/A across type-check, lint, tests, build. The rotation that would unblock CI is human-only and cannot be performed by this agent.

---

## Scope Boundaries

**IN SCOPE:**

- Authoring this 2nd-pickup investigation artifact for #841 at the canonical workflow path.
- Posting a GitHub comment on #841 with the assessment, evidence chain, and pointer to `docs/RAILWAY_TOKEN_ROTATION_742.md` plus the web-research caveats.
- Carrying the existing `web-research.md` into the worktree alongside the investigation for the PR.
- Pointing the human at the existing runbook and the workspace-blank pre-save verification, with the latest run number `25215295472`.

**OUT OF SCOPE (do not touch):**

- The actual `RAILWAY_TOKEN` rotation (human-only per `CLAUDE.md`).
- `.github/workflows/staging-pipeline.yml` (failing closed correctly during an active incident).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` corrections (drop unverified TTL claim; clarify Project vs Account token; add OAuth troubleshooting link from this pickup's Finding N2) — record findings here for the runbook-update bead already in mayor's queue; do not edit during this pickup.
- A `.github/RAILWAY_TOKEN_ROTATION_841.md` rotation receipt (Category 1 error).
- The structural fix (env-var rename, validator rewrite, scheduled secret-validation cron, OIDC federation). Already mailed-to-mayor; **do not re-mail** per PR #840 and PR #842.
- Migration off Railway (#629).
- Re-mailing mayor or filing additional issues — #841 alone is sufficient and accurate.
- Closing #841 — that requires the rotation to land first.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-05-01T15:10:00Z
- **Workflow**: `cad662fda0d3b96c2e4bd299f4480e15` (2nd pickup of #841)
- **Predecessor PRs (lineage)**: #834 (1st of #833, merged), #837 (1st of #836, merged), #838 (2nd of #836, merged), #839 (#758 stale-dup investigation, merged), #840 (3rd of #833, merged), #842 (1st of #841, merged 12:30Z)
- **Companion artifact**: `artifacts/runs/cad662fda0d3b96c2e4bd299f4480e15/web-research.md` (authored 15:05Z, 18 sources, 3 new vs 1st pickup)
- **Predecessor investigation**: `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/investigation.md`
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/cad662fda0d3b96c2e4bd299f4480e15/investigation.md`
