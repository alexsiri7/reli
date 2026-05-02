# Investigation: Main CI red: Deploy to staging (issue #907)

**Issue**: [#907](https://github.com/alexsiri7/reli/issues/907) — Main CI red: Deploy to staging
**Type**: BUG (operational / external-credential expiry — out-of-scope for code change)
**Investigated**: 2026-05-02T17:35:00Z
**Run**: [25256579563](https://github.com/alexsiri7/reli/actions/runs/25256579563)
**SHA**: `3521481dfd3d472b63bdfa909372bcac3be5ba64`

---

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | **HIGH** | The `Deploy to staging` workflow is fully blocked at the `Validate Railway secrets` step on every main-branch CI completion; staging is the gate for production, so the deploy chain is paused until the human admin rotates `RAILWAY_TOKEN`. There is no in-repo workaround and the same chain has now blocked 21 deploys in the same calendar day. |
| Complexity | **LOW** | Zero code changes are required in this repo. The fix is a human-only Railway dashboard action followed by `gh secret set RAILWAY_TOKEN`. The investigation deliverable is docs-only (this artifact + routing comment + web-research findings already in place). |
| Confidence | **HIGH** | The failed-job log explicitly returns `RAILWAY_TOKEN is invalid or expired: Not Authorized` from the validator block in `.github/workflows/staging-pipeline.yml:49-58`. This is the same exact failure mode and message as the previous 60 incidents in this repo's history, including the immediately prior chain link #904 (PR #906) ~1 hour ago. |

---

## Problem Statement

The `Deploy to staging` job in `.github/workflows/staging-pipeline.yml` failed at the `Validate Railway secrets` step. The validator's `me{id}` GraphQL probe against `https://backboard.railway.app/graphql/v2` returned `Not Authorized`, so the workflow exited 1 with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. This is the **61st** consecutive `RAILWAY_TOKEN` rejection in repository history and the **21st** in a single calendar day (2026-05-02), continuing the rapid-rotation chain `#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #903/#904 → #907`. Per `CLAUDE.md` § "Railway Token Rotation", **agents cannot rotate this token** — the deliverable is the artifact set + a routing comment directing the human operator to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Analysis

### First-Principles: Primitive Soundness

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Railway-secrets validator (token-liveness probe) | `.github/workflows/staging-pipeline.yml:32-58` | **Yes** | Correctly fast-fails before any deploy mutation; emits a clear `::error::` and points the operator to the rotation runbook. The validator is doing exactly what it was designed to do — it is the **token** that is invalid, not the validator. |
| `RAILWAY_TOKEN` GitHub Actions secret | (external — Repository secret) | **No — repeating failure** | A token that authenticated successfully ~1 hour ago is now `Not Authorized` again. After 60 rotations the token keeps getting rejected within minutes-to-hours of each rotation, suggesting either (a) the token is being created with a default short TTL in the Railway dashboard, (b) the wrong workspace is being selected at creation time, or (c) the token is being revoked/superseded by some external process. The systemic failure is **not in this repo** — it is in either Railway's token issuance or the operator's rotation procedure. |
| Rotation runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | **Possibly incomplete** | The existing runbook does not yet explicitly call out the No-workspace-selected + No-expiration creation requirements that the Railway community thread (see `web-research.md`) has flagged. This is captured in this run's `web-research.md` for a separate documentation bead, **not fixed in this PR** (Polecat scope). |

**Root cause vs symptom**: The error manifests in the GitHub Actions log, but the root cause is at the credential-issuance boundary in Railway. No edit to the workflow, runbook, or any source file in this repo can resolve a `Not Authorized` response from `backboard.railway.app/graphql/v2` — that requires a fresh, valid token issued in the Railway dashboard.

**Minimal change**: Zero. This investigation produces the routing comment and artifact set; the fix is a human-only dashboard action.

**What this unlocks**: Once the human admin rotates the token following the runbook (with the No-workspace + No-expiration recommendations from `web-research.md` verified before re-rotating like-for-like), the entire backlog of staging deploys auto-recovers via `gh run rerun --failed`.

---

### Root Cause / Evidence Chain

```
WHY 1: Why did the Deploy-to-staging job fail?
↓ BECAUSE: The "Validate Railway secrets" step exited 1 after the token-liveness probe
   returned a `Not Authorized` GraphQL error.
   Evidence: .github/workflows/staging-pipeline.yml:53-57
     `if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then`
     `  MSG=$(echo "$RESP" | jq -r '.errors[0].message // ...')`
     `  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"`
     `  exit 1`
   Run log (run 25256579563):
     `2026-05-02T16:34:55.3061519Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`

↓ BECAUSE: The Railway GraphQL endpoint at https://backboard.railway.app/graphql/v2
   returned `{"errors":[{"message":"Not Authorized"}]}` for the `{me{id}}` query against
   the Bearer token supplied via `secrets.RAILWAY_TOKEN`.
   Evidence: validator probe at staging-pipeline.yml:49-52 — POSTs `{me{id}}` with the
   secret as `Authorization: Bearer …`. A `Not Authorized` from `me{id}` means the token
   itself is rejected (not a permission scope issue, not a missing variable — those would
   produce different errors).

↓ BECAUSE: The current value of the GitHub Actions repository secret `RAILWAY_TOKEN` is
   no longer accepted by Railway as a valid identity. Either it was revoked, expired,
   re-rotated externally, or was created with a wrong-workspace scope that has since
   become invalid for this account.
   Evidence: identical failure mode and message has occurred 60 times before in this
   repo's history (see commit log `git log --grep="RAILWAY_TOKEN expiration"`), with the
   immediately prior chain link #904 occurring ~1 hour ago at 16:12Z (PR #906) and
   #903 at the same window. The chain shows that even after each successful rotation,
   the next deploy attempt within minutes-to-hours rejects again with the same message.

ROOT CAUSE: Railway's auth backend rejects the token currently held in
`secrets.RAILWAY_TOKEN`. Resolution requires a human admin to rotate the secret in the
Railway dashboard and update the GitHub Actions secret. **This is explicitly out of
scope for any agent per `CLAUDE.md` § Railway Token Rotation.**
```

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| _(none — code-side fix)_ | — | — | No source code, workflow, runbook, or `.github/RAILWAY_TOKEN_ROTATION_*.md` file is to be modified. The validator is correct; the runbook is the human's responsibility; creating a `RAILWAY_TOKEN_ROTATION_907.md` claiming success on a human-only action is a Category 1 error per `CLAUDE.md`. |
| `artifacts/runs/82f3717c5ef377464cba9b91fd484398/investigation.md` | NEW | CREATE | This file. |
| `artifacts/runs/82f3717c5ef377464cba9b91fd484398/web-research.md` | EXISTING | (already present) | Captures Railway community/docs evidence for No-workspace + No-expiration token-creation requirements and `.app` vs `.com` host observations. Read by the implementing agent (and surfaced in the routing comment) so the human admin can verify both checkboxes before re-rotating like-for-like. |

### Integration Points

- `.github/workflows/staging-pipeline.yml:32-58` — `Validate Railway secrets` step. **Not modified.** It correctly emits the actionable error.
- `.github/workflows/staging-pipeline.yml:60-100+` — `Deploy staging image to Railway` and downstream steps. Never reached because the validator fast-fails (correct fail-fast behaviour).
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — the human-only rotation runbook referenced by the validator's error message. **Not modified** (out of scope; potential improvements are catalogued in `web-research.md` for a separate bead).
- `pipeline-health-cron.sh` — auto-filed this issue with the `archon:in-progress` label, which is how Archon picked it up. **Not modified** (its behaviour is correct).

### Git History

- **Validator step introduced**: long-standing in `.github/workflows/staging-pipeline.yml` — predates this incident chain.
- **Last RAILWAY_TOKEN rotation observed via this repo**: the human admin actions are not committed to git (they happen in the GitHub Secrets UI), so git history alone cannot timestamp them. The chain of investigation PRs (`#851 → #852 → … → #905 → #906`) is the operational record.
- **Chain implication**: 61 rejections in repo history, 21 today alone, with the `#904 → #907` interval ~1 hour. This is well beyond a one-off expiration and points to either (i) Railway-side credential lifecycle (short TTL or external revocation) or (ii) operator-side rotation choices (wrong workspace, default expiration). See `web-research.md` for both hypotheses.

---

## Implementation Plan

This is a **docs-only investigation deliverable**. The implementing agent's job is to produce the artifact set, post the routing comment, and open a PR with `Fixes #907` — **not** to modify code, the workflow, the runbook, or any `.github/RAILWAY_TOKEN_ROTATION_*.md` file.

### Step 1: Write the investigation artifact

**File**: `artifacts/runs/82f3717c5ef377464cba9b91fd484398/investigation.md`
**Action**: CREATE (this file)
**Why**: It IS the specification. The implementing agent reads it to know what to produce.

### Step 2: Reference (do not duplicate) `web-research.md`

**File**: `artifacts/runs/82f3717c5ef377464cba9b91fd484398/web-research.md`
**Action**: ALREADY PRESENT — link from the routing comment and the investigation artifact.
**Why**: Polecat Scope Discipline. The systemic hypotheses (No-workspace, No-expiration, `.app` vs `.com`) belong in their own doc and a separate bead targeting the runbook; they are out of scope for #907 itself.

### Step 3: Post a routing comment on issue #907

**Channel**: `gh issue comment 907 --body …`
**Content** (verbatim, including the four-step human checklist):

```markdown
## 🔍 Investigation: Main CI red: Deploy to staging

**Type**: `BUG` (operational — external credential expiry)
**61st `RAILWAY_TOKEN` rejection / 21st today** — chain `#878 → … → #903/#904 → #907`.

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | `HIGH` | Staging deploy chain blocked at validator step; no in-repo workaround. |
| Complexity | `LOW` | Zero code changes; fix is a human-only Railway dashboard rotation. |
| Confidence | `HIGH` | Identical message + step + endpoint as the prior 60 incidents (most recently #904 ~1h ago). |

### Root cause (one line)

Railway's auth backend rejects the token currently held in `secrets.RAILWAY_TOKEN`
(`{"errors":[{"message":"Not Authorized"}]}` from `{me{id}}`). The validator at
`.github/workflows/staging-pipeline.yml:49-58` is correct; the token is not.

### Per `CLAUDE.md` § Railway Token Rotation

> Agents cannot rotate the Railway API token. The token lives in GitHub Actions secrets
> (`RAILWAY_TOKEN`) and requires human access to railway.com.

### Human follow-up required

1. Rotate `RAILWAY_TOKEN` per `docs/RAILWAY_TOKEN_ROTATION_742.md` — **with No workspace
   selected and No expiration** (see `web-research.md` § Recommendations #1–#2 in this
   run before re-rotating like-for-like, since the chain has now repeated 12 times in
   <8 hours).
2. `gh workflow run railway-token-health.yml --repo alexsiri7/reli` — verify the new
   token authenticates.
3. `gh run rerun 25256579563 --repo alexsiri7/reli --failed` — re-run the failed
   pipeline.
4. Confirm `Validate Railway secrets` passes; close #907 with the green run URL.

### What this investigation does NOT do

- Does **not** rotate the token (human-only).
- Does **not** create a `.github/RAILWAY_TOKEN_ROTATION_907.md` claiming success on a
  human-only action (Category 1 error per `CLAUDE.md`).
- Does **not** modify the validator, the runbook, or `DEPLOYMENT_SECRETS.md` (Polecat
  scope; runbook revisions belong in a separate bead — hypotheses captured in
  `artifacts/runs/82f3717c5ef377464cba9b91fd484398/web-research.md`).

### Artifact

📄 `artifacts/runs/82f3717c5ef377464cba9b91fd484398/investigation.md`
📄 `artifacts/runs/82f3717c5ef377464cba9b91fd484398/web-research.md`

---
*Investigated by Claude • 2026-05-02T17:35:00Z*
```

### Step 4: Open the PR

**Branch**: `archon/task-archon-fix-github-issue-1777741225437` (current)
**Title**: `docs: investigation for issue #907 (61st RAILWAY_TOKEN expiration, 21st today)`
**Body**: PR description mirroring the routing comment, with `Fixes #907`.
**Why**: Per `CLAUDE.md` § GitHub Issue Linking, every PR must link the issue it
contributes to.

---

## Patterns to Follow

**Mirror the prior chain link verbatim** — same artifact layout, same routing-comment
shape, same Polecat scope guards. The implementing agent should follow PR #906
(`docs: investigation for #904 (60th RAILWAY_TOKEN expiration)`) as the canonical
template for this incident class. Diff vs that PR should be:

- chain count: `60th → 61st`
- today count: `20th → 21st`
- run ID: `25255409159 → 25256579563`
- issue/PR cross-references: `#904 → #907`
- artifact run hash: `75b15c4… → 82f3717c…`
- chain history line: append `→ #907`

Everything else (scope guards, validation matrix, "what this PR does NOT do" section)
should be **identical** to PR #906.

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| The implementing agent fabricates a "rotation done" file (`.github/RAILWAY_TOKEN_ROTATION_907.md`) | Explicit Category 1 guard in the implementation plan + repeated reminders in routing comment, PR body, and `CLAUDE.md`. The validation step must explicitly check that no such file was added to the diff. |
| The implementing agent edits the validator step to soften the failure | Out of scope per Polecat. The validator is doing the right thing — fail fast with an actionable error. Any change to it would mask the underlying token problem. |
| The implementing agent edits `docs/RAILWAY_TOKEN_ROTATION_742.md` to add the No-workspace / No-expiration guidance from `web-research.md` | Out of scope for #907 — that is a separate runbook-improvement bead. The hypotheses are documented in `web-research.md` so a future bead can pick them up without re-doing the research. |
| Rotation chain continues after this PR merges (i.e., #908 / #909 / …) | Each new issue gets its own investigation artifact + routing comment. The chain count line in the PR title makes the systemic pattern visible to the human admin so they escalate to Railway support if the No-workspace / No-expiration verification doesn't break the loop. |
| Issue #907 is closed by the human admin before the PR merges | PR still merges with `Fixes #907` (or `Refs #907` if already closed). Artifact remains as historical record. |

---

## Validation

### Automated Checks

This is a docs-only diff. The standard suites (type / lint / format / tests / build) are
non-applicable. The implementing agent should verify:

```bash
# Diff is docs-only (no code, no workflow, no runbook, no .github/RAILWAY_TOKEN_ROTATION_*.md)
git diff --name-only main...HEAD | grep -vE '^artifacts/runs/82f3717c5ef377464cba9b91fd484398/' && echo "OUT OF SCOPE FILE FOUND" || echo "OK"

# Markdown files render (basic sanity — no broken fences)
for f in artifacts/runs/82f3717c5ef377464cba9b91fd484398/*.md; do head -1 "$f"; done

# No Category 1 file
test -f .github/RAILWAY_TOKEN_ROTATION_907.md && echo "CATEGORY 1 VIOLATION" || echo "OK"
```

### Manual Verification (post-merge, human-only)

1. Human admin completes the four-step rotation checklist in the routing comment.
2. `Validate Railway secrets` passes on a re-run of run `25256579563` (or the next main
   CI completion).
3. Issue #907 is closed by the human with the green run URL.

---

## Scope Boundaries

**IN SCOPE:**
- Create `artifacts/runs/82f3717c5ef377464cba9b91fd484398/investigation.md` (this file).
- Reference the existing `web-research.md` from the routing comment and PR body.
- Post the routing comment on #907.
- Open a PR titled `docs: investigation for issue #907 (61st RAILWAY_TOKEN expiration, 21st today)` with `Fixes #907`.

**OUT OF SCOPE (do not touch):**
- `RAILWAY_TOKEN` itself (human-only).
- `.github/workflows/staging-pipeline.yml` — the validator is correct.
- `docs/RAILWAY_TOKEN_ROTATION_742.md` — runbook revisions are a separate bead; hypotheses captured in `web-research.md`.
- `DEPLOYMENT_SECRETS.md`, `pipeline-health-cron.sh`, any frontend/backend code.
- Creating a `.github/RAILWAY_TOKEN_ROTATION_907.md` (Category 1 error).
- Producing screenshot updates (`frontend/e2e/visual.spec.ts-snapshots/`) — no UI changes.

---

## Metadata

- **Investigated by**: Claude
- **Timestamp**: 2026-05-02T17:35:00Z
- **Artifact**: `artifacts/runs/82f3717c5ef377464cba9b91fd484398/investigation.md`
- **Companion**: `artifacts/runs/82f3717c5ef377464cba9b91fd484398/web-research.md`
- **Chain**: 61st `RAILWAY_TOKEN` rejection in repo history, 21st in calendar day 2026-05-02 — `#878 → #880 → #882 → #884 → #886 → #888 → #891 → #894 → #896 → #898 → #901 → #903/#904 → #907`.
