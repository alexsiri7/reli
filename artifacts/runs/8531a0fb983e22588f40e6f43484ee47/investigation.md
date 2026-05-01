# Investigation: Prod deploy failed on main (#841 — 34th `RAILWAY_TOKEN` expiration cycle, prod-deploy framing)

**Issue**: #841 (https://github.com/alexsiri7/reli/issues/841)
**Type**: BUG
**Investigated**: 2026-05-01T12:15:00Z
**Workflow**: `8531a0fb983e22588f40e6f43484ee47`

## Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | HIGH | Prod auto-deploy on every push to `main` is still broken at `Validate Railway secrets`. The latest failing run `25209787350` (09:34:51Z, SHA `da29247` — the merge commit of PR #840 itself, the 3rd-pickup investigation of #833) confirms the secret has not been rotated since the original 03:35Z incident. `Deploy to production` is `skipped` on every merge. HIGH (not CRITICAL) because a documented human-only rotation workaround exists. |
| Complexity | LOW | Single human action — rotate the `RAILWAY_TOKEN` GitHub Actions secret per `docs/RAILWAY_TOKEN_ROTATION_742.md`. No code, workflow, or config edit is in scope. Agents are forbidden from rotating per `CLAUDE.md > Railway Token Rotation`. |
| Confidence | HIGH | Run `25209787350` emits the validator's exact diagnostic — `RAILWAY_TOKEN is invalid or expired: Not Authorized` at `.github/workflows/staging-pipeline.yml:55`. 8 consecutive identical-shape red runs on `main` since 03:35Z (`25200994188`, `25201008471`, `25202385518`, `25202388806`, `25203795132`, `25207459124`, `25208240731`, `25209787350`). Web research for this run (`web-research.md` Findings 1–2) further explains the structural recurrence: `RAILWAY_TOKEN` only accepts a *Project Token* per Railway employee statements. |

---

## Problem Statement

The `RAILWAY_TOKEN` GitHub Actions secret is still expired/wrong-class. The `Validate Railway secrets` pre-flight in `.github/workflows/staging-pipeline.yml:32-58` issues `Authorization: Bearer $RAILWAY_TOKEN` against Railway's `{me{id}}` GraphQL probe, receives `Not Authorized`, exits 1, and `Deploy to production` is skipped.

This is a **fresh prod-deploy framing** of a defect already tracked by **two open issues**:

- **#833** — original CI-red framing (32nd recurrence, original SHA `d01d31c`). Three pickups merged: PR #834 (1st), `09146632082d189318409846f65d7fd6` (2nd, no PR), PR #840 (3rd).
- **#836** — CI-red framing for next-day SHA `392291c` (33rd recurrence). Two pickups merged: PR #837 (1st), PR #838 (2nd).
- **#832** (closed) — staging-side framing on the same original run.

Issue #841 was filed by `pipeline-health-cron.sh` at 10:00:29Z when the prod-deploy pipeline observed run `25209787350` red on the merge commit of PR #840. The archon pickup cron then re-queued it at 12:00:40Z with the comment *"archon was labeled in-progress 7207s ago but no live run and no linked PR were found"* — making this the **1st pickup of #841** specifically (worktree `task-archon-fix-github-issue-1777636849757`, workflow `8531a0fb983e22588f40e6f43484ee47`).

---

## Analysis

### First-Principles: Primitive Soundness

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Secret-validator probe | `.github/workflows/staging-pipeline.yml:49-58` | Partial | Fails closed correctly, but the `{me{id}}` shape only accepts *account/workspace* tokens (returning `data.me.id`); a true *Project Token* uses a different header (`Project-Access-Token`) and would fail this validator even when valid. The diagnostic message ("invalid or expired") collapses three distinct failure modes — true expiration, wrong-class token, wrong-scope token — into one indistinguishable string, which is the proximate enabler of the 34-cycle recurrence. |
| Token rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Partial | Directs the rotator to `https://railway.com/account/tokens` and asserts a "1-day or 7-day default TTL." Per this run's `web-research.md` Finding 5, no Railway public doc describes a TTL on Project / Account / Workspace tokens — that claim is folklore. Per Findings 1–2, `/account/tokens` produces account or workspace tokens, **not** project tokens; a Railway employee says `RAILWAY_TOKEN` "now only accepts project token." So the runbook may be directing rotators to a URL that produces a token the validator will reject by design. |
| Issue/pickup taxonomy | n/a (cron behavior) | Partial | Three crons (`pipeline-health-cron.sh` for prod-deploy, the staging-CI-red filer, and archon's pickup cron) each open or re-queue an issue per cycle. One unrotated secret consequently produces 3+ open issues with overlapping causes, and successive-pickup PRs whose merge commits become the SHA on which the *next* failed run is filed (this issue was filed against PR #840's merge SHA). The taxonomy is fixable structurally but is out-of-scope for this bead. |

**Root cause vs symptom.** The symptom (CI red, prod-deploy skipped, multiple open issues) originates from a single unrotated GitHub Actions secret. Every fix path that does not rotate the secret is fixing where the error manifests, not where it originates.

### Root Cause / Change Rationale

**Process / human-action defect, not a code defect.** Per `CLAUDE.md > Railway Token Rotation`:

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets (`RAILWAY_TOKEN`) and requires human access to railway.com.
>
> Creating documentation that claims success on an action you cannot perform is a Category 1 error.

The structural recurrence is now well-characterized in the companion `web-research.md` for this run (15 cited sources, including official Railway docs and Railway-employee statements):

- `RAILWAY_TOKEN` (the env-var name reli's workflow uses) accepts **only Project Tokens**, which are minted at `project settings → Tokens` and use the `Project-Access-Token` HTTP header. Source: Railway Help Station (employee-confirmed).
- An account/workspace token created at `/account/tokens` will return `Not Authorized` against `RAILWAY_TOKEN` "even if u just made it 2 seconds ago" — same diagnostic as a truly expired token.
- Railway's *own* GitHub Actions example uses `RAILWAY_API_TOKEN` (account-scoped, workspace blank) with `Authorization: Bearer`.
- No public Railway documentation describes a TTL on Project / Account / Workspace tokens; the "1-day / 7-day default TTL" guidance in `docs/RAILWAY_TOKEN_ROTATION_742.md` is unverified.

This finding strengthens the explanation for the 34-cycle recurrence: it is plausible that every prior rotation produced a wrong-class or wrong-scope token, which the validator rejected on next CI run with the same misleading "invalid or expired" string. The structural fix is mailed-to-mayor in prior cycles (per PR #840) and is **deliberately not re-mailed** per that PR's guidance.

### Evidence Chain

```
WHY: Run 25209787350 (latest, 09:34:51Z on SHA da29247 — the merge of PR #840)
     failed.
↓ BECAUSE: "Deploy to staging" → "Validate Railway secrets" exited 1.
  Evidence: gh run view 25209787350 →
    "X Validate Railway secrets" / "Process completed with exit code 1."

↓ BECAUSE: Railway GraphQL {me{id}} returned no data.me.id.
  Evidence: "RAILWAY_TOKEN is invalid or expired: Not Authorized"
            (.github/workflows/staging-pipeline.yml:55 emits this exact string)

↓ ROOT CAUSE (immediate): RAILWAY_TOKEN GitHub Actions secret has
  expired or is the wrong class/scope. It has not been rotated since
  the original 03:35Z incident on SHA d01d31c (run 25200994188 /
  25201008471).
  Evidence: 8 consecutive failed main runs since 03:35Z on 4 distinct
            merge SHAs (d01d31c, 3db8f1b, 392291c, ee9d0fb, 76b58f5,
            da29247), all matching the validator's "Not Authorized"
            shape.

↓ ROOT CAUSE (structural, recurring 34×): RAILWAY_TOKEN env-var name
  in .github/workflows/staging-pipeline.yml only authenticates against
  the {me{id}} probe when the secret is an account- or workspace-
  scoped token (which uses Authorization: Bearer). Per web-research.md
  Finding 2, Railway publicly states RAILWAY_TOKEN should only contain
  a Project Token (Project-Access-Token header). The validator's
  shape is incompatible with what the env-var name implies — every
  rotation that uses Railway's UI defaults at the namesake URL
  (/account/tokens) will fail on next CI run.
```

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/investigation.md` | NEW | CREATE | This investigation artifact (1st pickup of #841 — prod-deploy framing of the same #833/#836 root cause). |
| `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/web-research.md` | (already in canonical workspace) | CARRY-FORWARD | Web research authored earlier in this run that documents the four Railway token types, the `RAILWAY_TOKEN` ↔ Project-Token-only constraint, the workspace-blank account-token gotcha, and the unverified-TTL gap in the runbook. |

**Deliberately not changed** (per `CLAUDE.md`):

- `.github/workflows/staging-pipeline.yml` — failing closed correctly; the validator's *shape* is part of the structural defect, but editing it here would mask the unrotated-secret signal during an active incident.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical runbook is referenced from `CLAUDE.md`. Per scope discipline, runbook corrections (drop the unverified TTL claim; clarify Project vs Account token) are not this bead's concern; the structural findings are recorded here and in `web-research.md` for future reference.
- **No `.github/RAILWAY_TOKEN_ROTATION_841.md`** will be created — Category 1 error per `CLAUDE.md`.
- **No re-mail to mayor** — PR #840's test plan explicitly says *"do not re-mail"*; the structural fix is already in mayor's queue.

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step using `Authorization: Bearer $RAILWAY_TOKEN` against `{me{id}}` (account/workspace-token shape).
- `.github/workflows/staging-pipeline.yml:60-88` — `Deploy staging image to Railway` (`serviceInstanceUpdate` + `serviceInstanceDeploy` mutations) — also depends on `RAILWAY_TOKEN` and would also fail without rotation.
- `.github/workflows/railway-token-health.yml` — independent health-check workflow the operator can use to verify a freshly rotated secret before re-running deploys.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — canonical rotation runbook referenced from `CLAUDE.md`. (Note caveats above re: Project vs Account token framing.)
- `pipeline-health-cron.sh` — the cron that filed #841 against PR #840's merge SHA. Will re-fire on each subsequent failed deploy until `Deploy to production` reaches Railway green.

### Git History

- **Original failing run cited by sibling #833**: `25201008471` at 2026-05-01T03:35:29Z on SHA `d01d31c` (also `25200994188` at 03:34:43Z, same SHA — duplicate trigger).
- **This issue's failing run**: `25209787350` at 2026-05-01T09:34:51Z on SHA `da29247c1d9e94da19992e43f3f1f029b759016` (the merge commit of PR #840 itself, the 3rd pickup of #833).
- **All intervening main runs failed identically** (8 consecutive reds): `25202385518` & `25202388806` on `3db8f1b` (PR #834 merge); `25203795132` on `392291c` (PR #837 merge); `25207459124` on `ee9d0fb` (PR #838 merge); `25208240731` on `76b58f5` (PR #839 merge); `25209787350` on `da29247` (PR #840 merge).
- **Sibling-issue lineage**:
  - **#832** — 32nd recurrence, staging-side framing on the same original run. **Closed.**
  - **#833** — 32nd recurrence, deploy-down framing. **Open.** 3 pickups (PR #834, no-PR pickup, PR #840).
  - **#836** — 33rd recurrence, CI-red on next-day SHA. **Open.** 2 pickups (PR #837, PR #838).
  - **#841** (this) — 34th recurrence, prod-deploy framing on PR #840's merge SHA. **Open, in-progress.** 1st pickup.
- One rotation closes #833, #836, and #841 simultaneously.

---

## Implementation Plan (HUMAN-ONLY)

| Step | Where | Action |
|------|-------|--------|
| 1 | Read `docs/RAILWAY_TOKEN_ROTATION_742.md` end-to-end. | Note the runbook's URL is `https://railway.com/account/tokens`. **Caveat (this run's web-research.md Finding 2)**: Railway publicly states the env-var name `RAILWAY_TOKEN` only accepts Project Tokens (created at *project settings → Tokens*, not at `/account/tokens`). If the runbook's account-tokens URL is the historical source of the 34-cycle recurrence, the proper rotation is at project settings → Tokens. Until the runbook is corrected (out-of-scope here), the rotator's choice is between (a) following the runbook exactly and risking another rejected token, or (b) creating a Project Token and updating the runbook in a follow-up PR. |
| 2 | Pre-save verification — local terminal | Before storing the token, verify it against the *exact* probe the validator uses: `curl -sf -X POST https://backboard.railway.app/graphql/v2 -H "Authorization: Bearer <NEW_TOKEN>" -H "Content-Type: application/json" -d '{"query":"{me{id}}"}' \| jq '.data.me.id'`. Output **must** be a non-null string. If null/error, the token is the wrong class/scope for this validator — discard and retry. |
| 3 | Local terminal | `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and paste the verified token. |
| 4 | Local terminal | `gh run rerun 25209787350 --repo alexsiri7/reli --failed` (use the *latest* failing run; older runs may be locked). If rejected, push a no-op commit to `main` to trigger a fresh `staging-pipeline.yml` run. |
| 5 | GitHub | Once `Validate Railway secrets` passes, `Deploy staging image to Railway` reaches Railway, `Wait for staging health` returns ok, `Deploy to production` proceeds, and `/healthz` on `RAILWAY_PRODUCTION_URL` returns ok — close **#833**, **#836**, and **#841** together. Re-confirm **#832** stays closed. |

> ⚠️ **Do NOT create `.github/RAILWAY_TOKEN_ROTATION_841.md`** — that is a Category 1 error per `CLAUDE.md`.
>
> ⚠️ **Do NOT pick a workspace-scoped token** — selecting a workspace at `/account/tokens` creates a workspace-scoped token; per Railway employee "brody" (web-research.md Finding 3), workspace-scoped tokens fail many CLI/API operations. Leave the workspace selector blank for an account-scoped token, **or** rotate at project settings → Tokens for a true Project Token (web-research.md Finding 2 — strongly attested but inconsistent with the existing validator's `Authorization: Bearer` + `{me{id}}` shape).

---

## Patterns to Follow

The validator that gates this deploy remains the contract a fresh token must satisfy — verify against it before storing:

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

A token that returns a non-null `data.me.id` against this probe is, by construction, accepted by the validator. Any other response is rejected.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Rotator follows the runbook literally and creates a token at `/account/tokens` with a workspace selected | Pre-save verification curl in Step 2 surfaces the rejection before the secret is stored. Step 5 re-runs the workflow as final ground truth. |
| Rotator creates a Project Token (web-research.md Finding 2) and stores it in `RAILWAY_TOKEN` | Pre-save curl will fail because Project Tokens use `Project-Access-Token` header, not `Authorization: Bearer`. The token would also fail the existing validator at runtime. Recommend: account-scoped token with workspace blank for the existing validator's shape, OR a structural change (env-var rename, validator rewrite) tracked separately by the mailed-to-mayor structural fix. |
| Run `25209787350` is too old to rerun by the time the rotator acts | Step 4 fallback: push a no-op commit to `main` to trigger a fresh `staging-pipeline.yml` run on the new HEAD. |
| The pickup cron re-fires #841 before the human rotates | Expected per the cron's "no live run + no linked PR" heuristic. The next pickup will reach the same conclusion; this artifact already documents it. |
| `pipeline-health-cron.sh` files a 35th-cycle issue (e.g., #842) on the merge SHA of *this* PR | Possible if the human has not rotated by the time this PR merges. Resolution is identical: same root cause, same fix. The structural fix to break this loop has been mailed-to-mayor; do not re-mail. |
| Sibling #833 or #836 re-fires concurrently | Resolution is identical (one rotation closes all three). Step 5 prompts the human to close them together. |
| Runbook's "1-day/7-day TTL" claim leads the rotator to expect another expiration in days | Per web-research.md Finding 5, no Railway public doc supports a TTL on Project/Account/Workspace tokens. If repeated expirations are real, they are likely caused by scope/type mismatch — addressed by Step 2's pre-save verification, not by setting "No expiration." |

---

## Validation

### Automated Checks (post-rotation)

```bash
gh run rerun 25209787350 --repo alexsiri7/reli --failed
gh run watch --repo alexsiri7/reli
gh secret list --repo alexsiri7/reli | grep RAILWAY_TOKEN
```

Expected sequence: `Validate Railway secrets` passes → `Deploy staging image to Railway` reaches Railway → `Wait for staging health` returns ok → `Deploy to production` proceeds → `/healthz` on `RAILWAY_PRODUCTION_URL` returns `{"status":"ok"}` → `railway-token-health.yml` (independent health workflow) goes green.

### This Pickup's Validation (pre-rotation)

Diff is docs-only (one new investigation artifact + a copy in the worktree of the existing canonical web-research). N/A across type-check, lint, tests, build. The rotation that would unblock CI is human-only and cannot be performed by this agent.

---

## Scope Boundaries

**IN SCOPE:**

- Authoring this 1st-pickup investigation artifact for #841 at the canonical workflow path.
- Posting a GitHub comment on #841 with the assessment, evidence chain, and pointer to `docs/RAILWAY_TOKEN_ROTATION_742.md` plus the web-research.md caveats.
- Carrying the existing `web-research.md` into the worktree alongside the investigation for the PR.
- Pointing the human at the existing runbook and the workspace-blank pre-save verification.

**OUT OF SCOPE (do not touch):**

- The actual `RAILWAY_TOKEN` rotation (human-only per `CLAUDE.md`).
- `.github/workflows/staging-pipeline.yml` (failing closed correctly during an active incident).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` corrections (drop unverified TTL claim; clarify Project vs Account token semantics) — record findings here for a future bead; do not edit during this pickup.
- A `.github/RAILWAY_TOKEN_ROTATION_841.md` rotation receipt (Category 1 error).
- The structural fix (env-var rename to `RAILWAY_API_TOKEN`, validator that distinguishes wrong-class vs expired tokens, scheduled secret-validation cron, GitHub OIDC federation). Already mailed-to-mayor; **do not re-mail** per PR #840.
- Migration off Railway (tracked separately in #629).
- Re-mailing mayor or filing additional issues — three are already open for the same root cause.

---

## Metadata

- **Investigated by**: Claude (Opus 4.7, 1M context)
- **Timestamp**: 2026-05-01T12:15:00Z
- **Workflow**: `8531a0fb983e22588f40e6f43484ee47` (1st pickup of #841)
- **Predecessor PRs**: #834 (1st of #833, merged), #837 (1st of #836, merged), #838 (2nd of #836, merged), #839 (#758 stale-dup investigation, merged), #840 (3rd of #833, merged)
- **Companion artifact**: `artifacts/runs/8531a0fb983e22588f40e6f43484ee47/web-research.md`
- **Artifact**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/8531a0fb983e22588f40e6f43484ee47/investigation.md`
