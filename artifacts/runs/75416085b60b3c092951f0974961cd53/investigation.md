# Investigation: Prod deploy failed on main (33rd `RAILWAY_TOKEN` expiration, 3rd pickup of #833)

**Issue**: #833 (https://github.com/alexsiri7/reli/issues/833)
**Type**: BUG
**Investigated**: 2026-05-01T09:10:00Z
**Workflow**: `75416085b60b3c092951f0974961cd53`

## Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Production auto-deploy on every push to `main` is still broken at `Validate Railway secrets`. The latest failing run `25208240731` (08:34Z on SHA `76b58f5`, the merge of PR #839 for sibling-of-sibling #758) confirms the secret has *still* not been rotated since the original incident at 03:35Z. `Deploy to production` is `skipped` on every merge. HIGH (not CRITICAL) because a documented human-only rotation workaround exists. |
| Complexity | LOW | Single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit. Agents are forbidden from rotating per `CLAUDE.md > Railway Token Rotation`. |
| Confidence | HIGH | Original run `25201008471` and every subsequent run on `main` (`25202385518`, `25202388806`, `25203795132`, `25207459124`, `25208240731`) emit the validator's exact diagnostic — `RAILWAY_TOKEN is invalid or expired: Not Authorized` at `.github/workflows/staging-pipeline.yml:55`. 33rd identical-shape recurrence; 3rd archon pickup of this specific issue. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` issues `Authorization: Bearer $RAILWAY_TOKEN` against Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, exits 1, and `Deploy to production` is skipped.

This is the **3rd archon pickup** of #833 specifically. Issue #833's first investigation merged as PR #834 at 04:30Z; archon's pickup cron then re-fired the issue at 06:30Z stating "no live run and no linked PR were found", producing a second investigation in workflow `09146632082d189318409846f65d7fd6` (no new PR). The cron has now re-fired #833 a third time at 09:00Z with the same observation. Sibling issue **#836** (33rd recurrence on next-day SHA `392291c`) is also open and traces to the same secret. Sibling **#832** (32nd recurrence, staging-side framing on the same original run) is already CLOSED.

---

## Analysis

### Root Cause / Change Rationale

**Process / human-action defect, not a code defect.** The workflow is failing closed exactly as designed (`.github/workflows/staging-pipeline.yml:32-58`); editing it to mask the failure would itself be a defect. Per `CLAUDE.md > Railway Token Rotation`:

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
>
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

The structural recurrence is now well-characterized in the companion `web-research.md` for this run: the validator at line 49–58 uses `Authorization: Bearer` against `{me{id}}`, which is **account-token semantics** — project tokens have no `me` user and workspace-scoped account tokens also return `data.me = null`. Both failure modes surface the same misleading "invalid or expired" string. The rotator must produce an **account-scoped token with no workspace selected**.

### Evidence Chain

```
WHY: Run 25208240731 (latest, 08:34Z on SHA 76b58f5) failed.
↓ BECAUSE: Deploy to staging → Validate Railway secrets exited 1.
  Evidence: ##[error]Process completed with exit code 1.

↓ BECAUSE: Railway GraphQL {me{id}} returned no data.me.id.
  Evidence: ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized

↓ ROOT CAUSE (immediate): RAILWAY_TOKEN GitHub Actions secret has
  expired/been revoked and has not been rotated since the original
  03:35Z incident on SHA d01d31c (run 25201008471).
  Evidence: .github/workflows/staging-pipeline.yml:49-58 — validator
  issues Authorization: Bearer $RAILWAY_TOKEN against {me{id}} and
  exits 1 on missing data.me.id.

↓ ROOT CAUSE (structural, recurring): the validator only passes for
  account-scoped (workspace-blank) Railway tokens. Project tokens and
  workspace-scoped tokens both produce data.me = null and the same
  "Not Authorized" message — making rotation mistakes invisible
  until CI runs again. See web-research.md § Findings 1-2.
```

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/75416085b60b3c092951f0974961cd53/investigation.md` | NEW | CREATE | This investigation artifact (3rd-pickup re-confirmation + latest-run evidence + pointer to existing PR #834 and #837/#838 lineage). |
| `artifacts/runs/75416085b60b3c092951f0974961cd53/web-research.md` | (already in canonical workspace) | CARRY-FORWARD | Pre-existing web-research artifact authored earlier in this run that documents the account-vs-project-vs-workspace token failure-mode taxonomy and the pre-save verification curl. |

**Deliberately not changed** (per `CLAUDE.md`):
- `.github/workflows/staging-pipeline.yml` — failing closed correctly; editing would mask the real defect.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook remains correct.
- **No `.github/RAILWAY_TOKEN_ROTATION_833.md` will be created** — Category 1 error.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step using `{me{id}}` probe.
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` (`serviceInstanceUpdate` + `serviceInstanceDeploy` mutations), would also fail without rotation.
- `.github/workflows/railway-token-health.yml` — independent health-check workflow the operator can use to verify the new secret before re-running deploys.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook referenced from `CLAUDE.md`.

### Git History

- **Original failing run cited by #833**: `25201008471` at 2026-05-01T03:35:29Z on SHA `d01d31c`.
- **Latest failing run** (still red): `25208240731` at 2026-05-01T08:34:57Z on SHA `76b58f5` (the merge commit of PR #839 for sibling-of-sibling #758).
- **All intervening main runs failed identically**: `25202385518`/`25202388806` (`3db8f1b`, merge of PR #834 — this issue's first investigation); `25203795132` (`392291c`, merge of PR #837 — first investigation for sibling #836); `25207459124` (`ee9d0fb`, merge of PR #838 — second pickup of #836). Six consecutive red runs on `main` since the original incident, all matching the validator's `Not Authorized` shape.
- **Pickup lineage for #833**: 1st pickup → PR #834 (merged 04:30Z); 2nd pickup → workflow `09146632082d189318409846f65d7fd6` at 06:30Z, no new PR; 3rd pickup (this) → workflow `75416085b60b3c092951f0974961cd53` at 09:00Z.
- **Sibling issues**: #832 (32nd recurrence, closed); #836 (33rd recurrence, open). One rotation resolves all three.

---

## Implementation Plan (HUMAN-ONLY)

| Step | Where | Action |
|------|-------|--------|
| 1 | https://railway.com/account/tokens | Create a new **account-scoped** token. **Leave the workspace selector blank** (do not pick a default workspace). Select **"No expiration"** if available. Project and workspace-scoped tokens both fail the `{me{id}}` validator immediately — see `web-research.md` § Findings 1-2 in this run dir. |
| 2 | Local terminal (pre-save check) | Verify the new token *before* storing it: `curl -sf -X POST https://backboard.railway.app/graphql/v2 -H "Authorization: Bearer <NEW_TOKEN>" -H "Content-Type: application/json" -d '{"query":"{me{id}}"}' \| jq '.data.me.id'`. Output must be a non-null string. Anything else (null, errors) means wrong class/scope — discard and recreate. |
| 3 | Local terminal | `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the verified token. |
| 4 | Local terminal | `gh run rerun 25208240731 --repo alexsiri7/reli --failed` (use the *latest* failing run; older runs may be locked). If rejected, push a no-op commit to `main`. |
| 5 | GitHub | Close **#833**, **#836**, and confirm **#832** stays closed once `Validate Railway secrets` passes and `Deploy to production` reaches Railway. |

> ⚠️ **Do NOT create `.github/RAILWAY_TOKEN_ROTATION_833.md`** — that is a Category 1 error per `CLAUDE.md`.
>
> ⚠️ **Do NOT pick a project or workspace token** — both fail the existing `{me{id}}` validator immediately and produce the same misleading "invalid or expired" message.

---

## Patterns to Follow

The validator that gates this deploy is unchanged from prior recurrences and remains the contract a fresh token must satisfy:

```bash
# .github/workflows/staging-pipeline.yml:49-58
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  echo "Rotate the token — see DEPLOYMENT_SECRETS.md Token Rotation section."
  exit 1
fi
```

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Rotator selects a project token (intuitive given the env-var name `RAILWAY_TOKEN`) | Pre-save verification curl in Step 2 surfaces the mistake before the secret is stored. |
| Rotator selects a workspace-scoped account token (Railway UI may pre-select a default workspace) | Step 1 explicitly directs the rotator to leave the workspace selector blank; pre-save curl catches it if missed. |
| Run `25208240731` is too old to rerun by the time the rotator acts | Step 4 fallback: push a no-op commit to `main`, which triggers a fresh `staging-pipeline.yml` run on the new HEAD. |
| Archon re-fires #833 a fourth time before the human rotates | Expected per the pickup-cron heuristic ("no live run + no linked PR"). The fourth pickup will reach the same conclusion; this artifact already documents it. The structural fix to break this loop is mailed-to-mayor and out-of-scope. |
| Sibling #836 re-fires concurrently | Resolution is identical (one rotation closes both). Step 5 prompts the human to close them together. |

---

## Validation

### Automated Checks (post-rotation)

```bash
gh run rerun 25208240731 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN
```

Expected: `Validate Railway secrets` passes → `Deploy staging image to Railway` reaches Railway → `Wait for staging health` returns ok → `Deploy to production` proceeds → `/healthz` on `RAILWAY_PRODUCTION_URL` returns `{"status":"ok"}` → `railway-token-health.yml` goes green.

### This Re-Fire's Validation (pre-rotation)

N/A across type-check, lint, tests, build — the diff is docs-only (one new investigation artifact in this run's directory). The rotation that would unblock CI is human-only and cannot be performed by this agent.

---

## Scope Boundaries

**IN SCOPE:**
- Authoring this 3rd-pickup investigation artifact at the canonical workflow path.
- Pointing the human at the existing runbook and the verified, workspace-blank rotation procedure.

**OUT OF SCOPE (do not touch):**
- The actual `RAILWAY_TOKEN` rotation (human-only per `CLAUDE.md`).
- `.github/workflows/staging-pipeline.yml` (failing closed correctly).
- A `.github/RAILWAY_TOKEN_ROTATION_833.md` rotation receipt (Category 1 error).
- The structural fix (validator that distinguishes wrong-class vs expired tokens, env-var rename, scheduled secret-validation cron, GitHub OIDC federation) — already mailed to mayor in prior cycles; do **not** re-mail.
- Migration off Railway (tracked separately in #629).

---

## Metadata

- **Investigated by**: Claude (Opus 4.7)
- **Timestamp**: 2026-05-01T09:10:00Z
- **Workflow**: `75416085b60b3c092951f0974961cd53` (3rd pickup of #833)
- **Predecessor PRs**: #834 (1st pickup of #833, merged), #837 / #838 (sibling #836 1st & 2nd pickups, merged)
- **Companion artifact**: `artifacts/runs/75416085b60b3c092951f0974961cd53/web-research.md`
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/75416085b60b3c092951f0974961cd53/investigation.md`
