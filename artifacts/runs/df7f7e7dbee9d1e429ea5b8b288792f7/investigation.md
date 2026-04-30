# Investigation: Deploy down — duplicate of #758, production currently UP

**Issue**: #759 (https://github.com/alexsiri7/reli/issues/759)
**Type**: BUG
**Investigated**: 2026-04-29T23:40:00Z
**Workflow ID**: df7f7e7dbee9d1e429ea5b8b288792f7

### Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | LOW | Production is currently UP — 3/3 sequential `/healthz` probes returned `200 OK` in 248–470 ms during this investigation; the 03:00:34 UTC alert was a transient `HTTP 000` (no-response) blip from the daily cron monitor, identical to the one filed 24h earlier as #758, and there is no current user impact. |
| Complexity | LOW | This bead's correct disposition is administrative — close #759 as a duplicate of #758 and commit this investigation as the linkable docs artifact (mirroring the PR #761 → #755 pattern). No backend code is touched in this bead; the underlying lifespan-hang fix is already owned by PR #760 (`Fixes #758`). |
| Confidence | HIGH | Direct, reproducible evidence: live `curl https://reli.interstellarai.net/healthz` returns `{"status":"ok","service":"reli"}` repeatedly; #758 has a byte-identical title and a structurally identical body (same template, only the detected timestamp differs) filed exactly 24h earlier; PR #760 explicitly says `Fixes #758`; web research (`web-research.md` in this run) corroborates that `HTTP 000` is curl's "no response" sentinel and that the suspected MCP-lifespan startup-hang is a known upstream failure mode. |

---

## Problem Statement

An external daily cron monitor filed #759 at 2026-04-29 03:00:34 UTC reporting
`HTTP status: 000000` for `https://reli.interstellarai.net`. `HTTP 000` is not a
real HTTP status — it is curl's sentinel for "no HTTP response line was received
at all" (DNS / TCP / TLS / read-timeout / connection-refused). Production is
currently up and serving traffic normally, and #758 (filed 24h earlier with a
structurally identical body — same template, only the detected timestamp
differs) already owns this alert. PR #760 declares `Fixes #758` and
is the canonical fix for the underlying intermittent FastAPI/MCP lifespan
startup hang. Per CLAUDE.md Polecat Scope Discipline, this bead's job is the
duplicate disposition only — not to also fix the lifespan hang from #758.

---

## Analysis

### 3.0 First-Principles — Primitive Audit

| Primitive | File:Lines | Sound? | Notes |
|-----------|-----------|--------|-------|
| Issue-tracker dedup (one open `Deploy down` issue per outage) | external monitor (no workflow in `.github/workflows` matches) | **No** | The monitor opens a fresh issue per failure rather than commenting on the existing one — that is exactly why #758 and #759 coexist for byte-identical alerts. Out of scope here; routed to mayor as a follow-up. |
| FastAPI + MCP nested lifespan | `backend/main.py:68-132` | **Partial** | Uses a one-shot `_session_manager.run()` with a private-attribute reset (`sm._has_started = False`, `sm._run_lock = anyio.Lock()`) to allow re-entry. Touches MCP-SDK private internals; canonical pattern is `AsyncExitStack`. Owned by PR #760 — **out of scope for #759**. |
| Curl-based health probe semantics (`%{http_code} == 000`) | external monitor payload format | **Partial** | Reports six concatenated zeros (`000000`) with no separate exit code — caller cannot distinguish DNS vs TCP vs TLS vs timeout. Out of scope here; routed to mayor. |
| GitHub-issue duplicate handling (the only primitive in this bead's scope) | `gh issue close --reason "not planned"` | **Yes** | Standard, fully-supported. Just needs to be invoked. |

**Minimal change for #759:** close it as a duplicate of #758 and commit this
investigation artifact as the linkable docs file. Do not extend new
abstractions, do not touch `backend/main.py`.

### 3.1 Root Cause — 5 Whys

```
WHY 1: Why was #759 filed?
↓ BECAUSE: The external 03:00 UTC daily monitor saw HTTP_CODE=000 from
   curl when probing https://reli.interstellarai.net.
   Evidence: issue body — "HTTP status: 000000 ... Detected: 2026-04-29 03:00:34 UTC"

WHY 2: Why did the monitor see HTTP_CODE=000?
↓ BECAUSE: curl's `%{http_code}` is `000` whenever no HTTP status line was
   received — DNS failure, TCP refused, TLS error, or read timeout.
   Evidence: web-research.md §1 (curl maintainers' mailing list + libcurl
   docs); the `000000` (six zeros) means all retries failed at the
   connection layer, not that the app returned a 5xx.

WHY 3: Why would the connection layer have failed at exactly 03:00 UTC?
↓ BECAUSE: A momentary container restart or unfinished startup at the
   Railway edge — the same hypothesis behind #758. Likely the MCP
   StreamableHTTPSessionManager's startup hung, blocking the lifespan
   before `yield`, so Railway's healthcheck saw connection-refused while
   the new container was being swapped in.
   Evidence: `backend/main.py:113-128` runs the MCP session manager in
   the lifespan and uses a private-attribute reset (`sm._has_started`,
   `sm._run_lock`) — a workaround for exactly this re-entry hazard.
   web-research.md §2 corroborates this is a known MCP-SDK failure mode
   (issues #713, #1220, #1367, fastapi-mcp #256).

WHY 4: Why is #759 a separate issue from #758 if it's the same alert?
↓ BECAUSE: The external monitor lacks issue-dedup logic — it opens a
   fresh issue per failure rather than commenting on the existing
   open one. That's a monitor-side defect, not an app defect.
   Evidence: #758 (2026-04-28 03:00:33 UTC) and #759 (2026-04-29
   03:00:34 UTC) have byte-identical titles and structurally identical
   bodies (same template, only the detected timestamp differs), exactly
   24h apart, both filed by the daily cron.

ROOT CAUSE (for #759 disposition): #759 is a duplicate of #758.
The underlying intermittent startup-hang is owned by #758 / PR #760
and must NOT be re-fixed in this bead.
Evidence:
  - `gh pr view 760` body: `Fixes #758`, headRef `fix/issue-758-deploy-down`
  - PR #760 currently DIRTY/CONFLICTING with +117,151 / -124 lines
    (most additions are accidentally-committed `.archon-logs/`).
  - `gh issue list --search "Deploy down" --state all` returns only
    #758 and #759.
```

### Evidence Chain (terse)

WHY: Monitor reports `HTTP 000000`
↓ BECAUSE: curl `%{http_code}` is `000` when no response line is received
  Evidence: `everything.curl.dev/cmdline/exitcode.html` (web-research.md §1)

↓ BECAUSE: Connection-layer failure at the edge during a momentary container
  restart / unfinished startup
  Evidence: `backend/main.py:113-128` — one-shot MCP session-manager run with
  private-attribute reset; web-research.md §2 (MCP SDK #713, #1220, #1367).

↓ ROOT CAUSE for #759: This issue is a duplicate of #758, which already has
  PR #760 (`Fixes #758`) in flight as the canonical fix.
  Evidence: byte-identical title and structurally identical body 24h apart;
  `gh pr view 760` confirms `Fixes #758`.

### Affected Files

| File | Lines | Action | Description |
|------|-------|--------|-------------|
| (none in `backend/`) | — | — | **No code changes in this bead.** PR #760 owns the lifespan fix. |
| `artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/investigation.md` | NEW | CREATE | Commit this investigation artifact into the repo so PR-based Archon closure has a linkable change (mirrors PR #761 → #755 pattern). |
| `artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/web-research.md` | NEW | CREATE | Already present in this run dir; commit alongside `investigation.md` for completeness. |

### Integration Points

- **#758** — canonical issue for this alert, must be referenced in the close comment
- **PR #760** (`fix/issue-758-deploy-down`) — owns the lifespan fix; do **not** touch
- **mayor mailbox** — receives two out-of-scope follow-ups (see "Scope Boundaries" below)
- **`backend/main.py:68-132`** — the lifespan touched by PR #760; this bead does **not** edit it

### Git History

- **#759 created**: 2026-04-29 03:00:35 UTC (external daily cron monitor, owner: `alexsiri7`)
- **#758 created**: 2026-04-28 03:00:33 UTC (same monitor, structurally identical body — same template, only the detected timestamp differs)
- **PR #760 created**: targeting #758, currently `mergeStateStatus: DIRTY`, `mergeable: CONFLICTING`, +117,151 / -124
- **Last touch on `backend/main.py`**: pre-PR-#760 (PR #760 changes are not yet in `main`)
- **Implication**: The same external monitor will continue refiling #758-style alerts daily until either (a) PR #760 lands cleanly, or (b) the monitor itself learns to comment-vs-reopen.

---

## Implementation Plan

### Step 1: VERIFY — Re-confirm production is UP at execution time

**Action**: SHELL
**Why**: A LOW severity disposition is only correct if production is genuinely up *at the time we close the issue*. If `/healthz` fails at execute time, escalate (do not close, do not commit).

```bash
for i in 1 2 3; do
  curl -sf --max-time 15 -w "probe $i: HTTP %{http_code} %{time_total}s\n" \
    -o /dev/null https://reli.interstellarai.net/healthz || echo "probe $i FAILED"
done
```

**Expected**: 3/3 `HTTP 200` in <2s each. If any probe fails, abort the close-as-duplicate path and re-investigate as a live outage.

---

### Step 2: COMMIT — Add `investigation.md` and `web-research.md` to the repo

**File**: `artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/investigation.md`
**Action**: CREATE
**Why**: Mirrors the PR #761 → #755 pattern — a docs-only PR gives Archon a linkable change so the `archon:in-progress` label can transition out cleanly. Without a PR, the workflow keeps re-queuing (see #759 comment history: 12 re-queue notices from 06:00 UTC through 22:30 UTC).

```bash
mkdir -p artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7
cp /home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/investigation.md \
   artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/investigation.md
cp /home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/web-research.md \
   artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/web-research.md
git add artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/
git commit -m "docs: add investigation for issue #759 (duplicate of #758)"
```

---

### Step 3: PUSH + PR — Open PR with `Fixes #759` (close-as-duplicate)

**Action**: PR
**Why**: Archon's tracking expects a linked PR. The PR body must declare the duplicate disposition explicitly so reviewers know there is no code change to evaluate.

```bash
git push -u origin archon/task-archon-fix-github-issue-1777501834756
gh pr create --title "docs: add investigation for issue #759 (duplicate of #758)" \
  --body "$(cat <<'EOF'
## Summary

#759 is a duplicate of #758 — same external 03:00 UTC daily monitor refired
exactly 24h later with a byte-identical title and a structurally identical
body (same template, only the detected timestamp differs). Production was
verified UP during investigation (3/3 `/healthz` 200 OK, sub-500ms). The
canonical fix for
the underlying intermittent FastAPI/MCP lifespan startup hang is owned by
PR #760 (`Fixes #758`), so per CLAUDE.md Polecat Scope Discipline this PR adds
**no code changes** — only the investigation artifact.

## Changes

- `artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/investigation.md` (NEW)
- `artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/web-research.md` (NEW)

## Validation

- `curl https://reli.interstellarai.net/healthz` returns `200 OK` in <500ms
- `gh issue list --search "Deploy down" --state open` shows only #758 + #759
- No `backend/` code touched

Fixes #759
EOF
)"
```

---

### Step 4: COMMENT + CLOSE — Post duplicate-of-#758 comment, then close #759

**Action**: GH-API
**Why**: The previous bead's "✅ Issue Resolution Report" claimed completion but never actually closed #759 — that's why the issue is still OPEN and Archon kept re-queuing. Do the close this time.

```bash
gh issue comment 759 --body "$(cat <<'EOF'
## Closing as duplicate of #758

Production verified UP at this time:

\`\`\`
$ for i in 1 2 3; do curl -sf --max-time 15 -w "HTTP %{http_code} %{time_total}s\n" -o /dev/null https://reli.interstellarai.net/healthz; done
HTTP 200 0.4xx s
HTTP 200 0.4xx s
HTTP 200 0.4xx s
\`\`\`

The 03:00 UTC daily monitor refired the same alert as #758 exactly 24h later
with a byte-identical title and a structurally identical body (same template,
only the detected timestamp differs). The underlying intermittent FastAPI/MCP
lifespan startup hang is owned by **PR #760** (\`Fixes #758\`).

Closing as `not planned` (duplicate). Track the fix on #758 / PR #760.
EOF
)"

gh issue close 759 --reason "not planned"
```

---

### Step 5: NOTIFY — Mail mayor about two out-of-scope follow-ups

**Action**: SHELL (mail)
**Why**: Per CLAUDE.md Polecat Scope Discipline, real but out-of-scope findings go to mayor — they don't get fixed in this bead.

```bash
gt mail send mayor/ \
  --subject "Found while investigating #759: PR #760 unmergeable, monitor lacks dedup" \
  --body "Two out-of-scope follow-ups surfaced while investigating #759 (duplicate of #758):

1. **PR #760 (Fixes #758) is unmergeable.** mergeStateStatus=DIRTY,
   mergeable=CONFLICTING, +117,151/-124 lines — bulk of additions are
   accidentally-committed .archon-logs/cron-issue-*.log. Until cleaned/rebased,
   the canonical lifespan-hang fix can't land and the daily 03:00 UTC alert
   will keep refiring.

2. **The 03:00 UTC monitor opens a new issue per failure** rather than
   commenting on the existing open one — which is exactly why #758 and #759
   coexist for byte-identical alerts. The monitor is external (no workflow in
   .github/workflows matches 'Deploy down' / 'interstellarai' / 'HTTP 000').
   Worth deduping at the monitor level (Upptime pattern: one open issue per
   target, comment on subsequent failures, auto-close on recovery).

Routed here per Polecat Scope Discipline — both are real but firmly out of
scope for #759, which is just a duplicate-close."
```

---

### Test Cases / Acceptance

This bead has no code under test. Acceptance is administrative:

- [ ] PR opened with `Fixes #759` and the close-as-duplicate body
- [ ] #759 closed with reason `not planned` and a duplicate-of-#758 pointer
- [ ] mayor received the two-item out-of-scope mail
- [ ] Working tree clean; only `artifacts/runs/.../*.md` added

---

## Patterns to Follow

**From the codebase — mirror PR #761 → #755 pattern exactly:**

```
PR #761 (merged 2026-04-29):
  - Title: "Fix: rotate expired RAILWAY_TOKEN"
  - Files: artifacts/runs/f1aad5a4c565a621f7bd50a32068e729/investigation.md (+160 / -0)
  - Body ends with: "Fixes #755"
```

The same shape applies here: one investigation file, declares `Fixes #759`,
closes the issue on merge. (Note: PR #761's *substance* — claiming agents
rotated `RAILWAY_TOKEN` — was problematic per CLAUDE.md "Railway Token
Rotation"; we are mirroring only its *structural* pattern of a docs-only PR
for an admin-only fix, not its content.)

---

## Edge Cases & Risks

| Risk / Edge Case | Mitigation |
|------------------|------------|
| Production goes down between investigation and close | Step 1 re-probes `/healthz` at execute time; if any probe fails, abort the close path and re-investigate as a live outage. |
| Closing #759 hides a *different* failure mode that happens to share the alert template | The 24h-apart, byte-identical title and structurally identical body and the `HTTP 000` (connection-layer) signature strongly indicate the same recurring transient; any new alert with a different signature would file a new issue. Cross-link in the close comment so future readers can re-open if needed. |
| Archon re-queues again because the workflow doesn't recognize a docs-only PR as "closing the issue" | PR body declares `Fixes #759`; on merge, GitHub auto-closes the issue. If for some reason auto-close is disabled, Step 4's explicit `gh issue close` is a belt-and-braces fallback. |
| PR #760's accidental log-file additions get cherry-picked into this PR | This worktree branch is `archon/task-archon-fix-github-issue-1777501834756` — independent from `fix/issue-758-deploy-down`. Only files explicitly added in Step 2 should be committed. `git status` before commit must show only `artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/*.md`. |
| Closing as `not planned` reads as "we won't fix" | The close comment explicitly points at #758 / PR #760 as the active fix, so the message is "tracked elsewhere" not "ignored." |

---

## Validation

### Automated Checks (no app code touched, so the usual stack is N/A)

```bash
# Verify the only changes are the two markdown files in this run dir
git status --porcelain
# Expected: only artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/{investigation,web-research}.md

git diff --stat main...HEAD
# Expected: exactly two .md files added, zero backend/frontend code changes
```

### Manual Verification

1. `curl -sf https://reli.interstellarai.net/healthz` returns `200` (production still up)
2. `gh issue view 759 --json state` returns `"CLOSED"` after Step 4
3. `gh issue list --search "Deploy down" --state open` returns only #758 (PR #760 still owns it)
4. `gh pr view <new-pr> --json body` body contains `Fixes #759`
5. mayor mailbox shows the two-item follow-up message

---

## Scope Boundaries

**IN SCOPE for this bead:**

- Verify production is UP at execute time
- Commit the investigation artifact as the linkable docs file
- Open a docs-only PR with `Fixes #759`
- Comment + close #759 as duplicate of #758
- Mail mayor with the two out-of-scope follow-ups

**OUT OF SCOPE — DO NOT TOUCH:**

- `backend/main.py` (lifespan / MCP session manager) — owned by PR #760
- Any rebase / cleanup of PR #760's +117k log additions — separate bead, route to mayor
- The external 03:00 UTC monitor's lack of issue dedup — separate bead, route to mayor
- Switching from the `_has_started` private-attr reset to `AsyncExitStack` — owned by PR #760
- Wrapping MCP startup in `asyncio.wait_for` — owned by PR #760
- Any change to `.github/workflows/*.yml`
- Any change to `frontend/`
- Re-investigating #758 itself

If the implementing agent finds any of these tempting, **stop and mail
mayor** instead of fixing inline — that is the entire point of CLAUDE.md
Polecat Scope Discipline and the previous bead at this same workflow ID
already established the duplicate-disposition path.

---

## Metadata

- **Investigated by**: Claude (claude-opus-4-7[1m])
- **Timestamp**: 2026-04-29T23:40:00Z
- **Workflow ID**: df7f7e7dbee9d1e429ea5b8b288792f7
- **Worktree branch**: `archon/task-archon-fix-github-issue-1777501834756`
- **Companion artifact**: `web-research.md` (already present in this run dir)
- **Artifact path**: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/df7f7e7dbee9d1e429ea5b8b288792f7/investigation.md`
