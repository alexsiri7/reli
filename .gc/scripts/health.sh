#!/usr/bin/env bash
# health.sh — Quick city health check with inactivity detection.
# Usage: scripts/health.sh [--fix]
#   --fix: restart dead/stale critical agents automatically
set -uo pipefail

CITY="${GC_CITY_ROOT:-/mnt/ext-fast/gc}"
FIX=false
[[ "${1:-}" == "--fix" ]] && FIX=true

NOW=$(date +%s)
STALE_THRESHOLD=600  # 10 minutes with no output = stale
PROBLEMS=0

# --- Colors (skip if not a terminal) ---
if [[ -t 1 ]]; then
  RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'; DIM='\033[0;90m'; RST='\033[0m'
else
  RED=''; YEL=''; GRN=''; DIM=''; RST=''
fi

ok()   { echo -e "  ${GRN}OK${RST}  $*"; }
warn() { echo -e "  ${YEL}WARN${RST} $*"; ((PROBLEMS++)); }
fail() { echo -e "  ${RED}FAIL${RST} $*"; ((PROBLEMS++)); }

# --- 1. Disk ---
echo "=== DISK ==="
DISK_PCT=$(df / --output=pcent 2>/dev/null | tail -1 | tr -d ' %')
DISK_AVAIL=$(df -h / --output=avail 2>/dev/null | tail -1 | tr -d ' ')
if (( DISK_PCT >= 95 )); then
  fail "Root filesystem ${DISK_PCT}% (${DISK_AVAIL} free)"
elif (( DISK_PCT >= 90 )); then
  warn "Root filesystem ${DISK_PCT}% (${DISK_AVAIL} free)"
else
  ok "Root filesystem ${DISK_PCT}% (${DISK_AVAIL} free)"
fi

# --- 2. Dolt ---
echo ""
echo "=== DOLT ==="
DOLT_PID=$(pgrep -f "dolt sql-server.*${CITY}" 2>/dev/null | head -1)
[[ -z "$DOLT_PID" ]] && DOLT_PID=$(pgrep -f "dolt sql-server.*dolt-config" 2>/dev/null | head -1)
if [[ -n "$DOLT_PID" ]]; then
  DOLT_PORT=$(ss -tlnp 2>/dev/null | grep "pid=${DOLT_PID}" | grep -oP ':\K\d+' | head -1)
  DOLT_SIZE=$(du -sh "$CITY/.beads/dolt" 2>/dev/null | cut -f1)
  HAS_JOURNAL=false
  for db_dir in "$CITY"/.beads/dolt/*/; do
    if ls "$db_dir".dolt/noms/vvvv* &>/dev/null 2>&1; then HAS_JOURNAL=true; break; fi
  done
  # Check for journal corruption
  JOURNAL_CORRUPT=false
  for db_dir in "$CITY"/.beads/dolt/*/; do
    db_name=$(basename "$db_dir")
    [[ "$db_name" == .* ]] && continue
    JOURNAL="$db_dir.dolt/noms/vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv"
    if [[ -f "$JOURNAL" ]]; then
      # Check dolt log for recent checksum errors on this db
      if tail -50 "$CITY/.gc/runtime/packs/dolt/dolt.log" 2>/dev/null | grep -q "checksum error.*$db_name\|connectionDb=$db_name.*checksum"; then
        fail "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE) — JOURNAL CORRUPT in $db_name (run: cd .beads/dolt/$db_name && dolt fsck --revive-journal-with-data-loss)"
        JOURNAL_CORRUPT=true
      fi
    fi
  done
  if $JOURNAL_CORRUPT && $FIX; then
    echo "       → running automated dolt repair..."
    if "$CITY/scripts/dolt-repair.sh"; then
      ok "Dolt repair completed — agents restarting"
      # After repair, skip remaining health checks (agents are restarting)
      echo ""
      echo -e "${GRN}Dolt repair triggered full recovery. Skipping remaining checks.${RST}"
      exit 0
    else
      fail "Dolt repair failed — check /tmp/dolt-repair-*.log"
    fi
  fi
  if ! $JOURNAL_CORRUPT; then
    # Write health test — try a lightweight read via bd
    if command -v bd &>/dev/null; then
      if ! bd list --type=session --json 2>/dev/null | head -1 >/dev/null 2>&1; then
        # Check if it's a checksum error specifically
        BD_ERR=$(bd list --type=session 2>&1 || true)
        if echo "$BD_ERR" | grep -qi "checksum error"; then
          fail "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE) — WRITE CORRUPTION detected (checksum error)"
        elif echo "$BD_ERR" | grep -qi "database.*not found\|connection refused"; then
          fail "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE) — DATABASE UNREACHABLE"
        else
          if $HAS_JOURNAL; then
            warn "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE) — journal file exists (run dolt gc)"
          else
            ok "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE)"
          fi
        fi
      else
        if $HAS_JOURNAL; then
          warn "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE) — journal file exists (run dolt gc)"
        else
          ok "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE)"
        fi
      fi
    else
      if $HAS_JOURNAL; then
        warn "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE) — journal file exists (run dolt gc)"
      else
        ok "Dolt UP (PID $DOLT_PID, port ${DOLT_PORT:-?}, $DOLT_SIZE)"
      fi
    fi
  fi
else
  fail "Dolt server not running"
fi

# --- 3. Agent Sessions ---
echo ""
echo "=== AGENTS ==="

declare -A EXPECTED_CRITICAL=(
  [mayor]=1
  [reli--refinery]=1
)

TOTAL=0
DEAD=0
STALE=0
QUOTA=0
AUTH=0

while IFS=' ' read -r NAME ACTIVITY CREATED PANE_DEAD PANE_PID; do
  ((TOTAL++))

  # Skip witness sessions (s-gc-*)
  [[ "$NAME" == s-gc-* ]] && continue

  AGE=$(( NOW - ACTIVITY ))
  AGE_MIN=$(( AGE / 60 ))

  # Check pane dead
  if [[ "$PANE_DEAD" == "1" ]]; then
    fail "$NAME — pane dead"
    ((DEAD++))
    if $FIX && [[ -n "${EXPECTED_CRITICAL[$NAME]+x}" ]]; then
      echo "       → restarting via gc nudge..."
      tmux -L gc kill-session -t "$NAME" 2>/dev/null
      # The reconciler will recreate it
    fi
    continue
  fi

  # Check if process is still alive
  if [[ -n "$PANE_PID" ]] && ! kill -0 "$PANE_PID" 2>/dev/null; then
    fail "$NAME — process gone (PID $PANE_PID)"
    ((DEAD++))
    continue
  fi

  # Capture last few lines for pattern matching
  TAIL=$(tmux -L gc capture-pane -t "$NAME" -p 2>/dev/null | tail -8)

  # Quota/auth checks
  if echo "$TAIL" | grep -qi "hit your limit\|exceeded.*quota\|insufficient_quota\|rate limit exceeded"; then
    fail "$NAME — QUOTA BLOCKED (idle ${AGE_MIN}m)"
    ((QUOTA++))
    if $FIX; then
      echo "       → killing quota-blocked session"
      tmux -L gc kill-session -t "$NAME" 2>/dev/null
    fi
    continue
  fi
  if echo "$TAIL" | grep -qi "authentication_error\|Please run /login\|OAuth token.*expired"; then
    fail "$NAME — AUTH ERROR (idle ${AGE_MIN}m)"
    ((AUTH++))
    continue
  fi

  # Stale check — present but no output for a while
  if (( AGE > STALE_THRESHOLD )); then
    # Check if it's actively using CPU (process might be thinking)
    CPU=$(ps -p "$PANE_PID" -o %cpu= 2>/dev/null | tr -d ' ' | cut -d. -f1)
    if [[ -n "$CPU" ]] && (( CPU > 5 )); then
      ok "$NAME — active (CPU ${CPU}%, last output ${AGE_MIN}m ago)"
    else
      warn "$NAME — STALE (no output for ${AGE_MIN}m, CPU ${CPU:-?}%)"
      ((STALE++))
    fi
  else
    ok "$NAME${DIM} (${AGE_MIN}m ago)${RST}"
  fi

done < <(tmux -L gc list-sessions -F '#{session_name} #{session_activity} #{session_created} #{pane_dead} #{pane_pid}' 2>/dev/null | sort)

echo ""
echo "  Total: $TOTAL sessions | Dead: $DEAD | Stale: $STALE | Quota: $QUOTA | Auth: $AUTH"

# Check for missing critical agents
echo ""
echo "=== CRITICAL AGENTS ==="
for AGENT in mayor reli--refinery; do
  # Check both direct name and reconciler-managed s-gc-* sessions
  if tmux -L gc has-session -t "$AGENT" 2>/dev/null; then
    ok "$AGENT present"
  elif gc session list 2>/dev/null | grep -qE "$AGENT.*(awake|active|creating)"; then
    ok "$AGENT present (reconciler-managed)"
  else
    fail "$AGENT MISSING"
    if $FIX; then
      echo "       → reconciler should recreate on next cycle"
    fi
  fi
done

# --- 3b. Session bead collision detection ---
# The controller can get stuck when closed session beads hold name reservations.
# Detect this by checking supervisor logs for the collision pattern and restart
# the controller if agents have been blocked for multiple cycles.
if $FIX; then
  COLLISION_COUNT=$(gc supervisor logs 2>/dev/null | grep -c "session.*alias already exists\|session.*name already exists" || echo 0)
  if (( COLLISION_COUNT > 5 )); then
    # Check if any refinery/witness/mayor is stuck stopped with work waiting
    STUCK_AGENTS=0
    for rig in gascity reli annie; do
      for role in refinery witness; do
        SESSION="${rig}--${role}"
        if ! tmux -L gc has-session -t "$SESSION" 2>/dev/null; then
          # Agent not running — is there work for it?
          RIG_DIR="$CITY/rigs/$rig"
          if [[ "$role" == "refinery" ]]; then
            REPO=$(git -C "$RIG_DIR" remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||' || true)
            HAS_WORK=$(timeout 10s gh pr list -R "$REPO" --state open --json number --jq 'length' 2>/dev/null || echo 0)
          else
            HAS_WORK=$(cd "$RIG_DIR" && timeout 10s bd list --status=in_progress --json --limit=1 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
          fi
          if (( ${HAS_WORK:-0} > 0 )); then
            ((STUCK_AGENTS++)) || true
          fi
        fi
      done
    done
    if ! tmux -L gc has-session -t "mayor" 2>/dev/null; then
      ((STUCK_AGENTS++)) || true
    fi

    if (( STUCK_AGENTS > 0 )); then
      fail "Session bead collision blocking $STUCK_AGENTS agent(s) — restarting controller"
      # Close ALL open session beads to clear the collision, then restart
      bd list --type=session --status=open --json --limit=0 2>/dev/null | \
        jq -r '.[].id' 2>/dev/null | while read -r SB_ID; do
          bd close "$SB_ID" --reason "health.sh: clearing session bead collision" 2>/dev/null || true
        done
      # Restart the city to clear the in-memory cache
      gc stop 2>/dev/null
      sleep 5
      gc start 2>/dev/null &
      ok "Controller restart initiated — agents should recover within 2 minutes"
    fi
  fi
fi

# --- 4. Delivery ---
echo ""
echo "=== DELIVERY (last 1h) ==="
for rig in gascity reli annie; do
  DIR="$CITY/rigs/$rig"
  [[ -d "$DIR/.git" ]] || continue
  COMMITS=$(git -C "$DIR" log --oneline --since="1 hour ago" master 2>/dev/null | wc -l)
  BRANCHES=$(git -C "$DIR" branch -r --no-merged master 2>/dev/null | grep -c "origin/" 2>/dev/null || true)
  BRANCHES=${BRANCHES:-0}
  if (( COMMITS > 0 )); then
    LATEST=$(git -C "$DIR" log --oneline -1 master 2>/dev/null)
    ok "$rig: $COMMITS commits merged, $BRANCHES unmerged branches — latest: $LATEST"
  else
    echo -e "  ${DIM}--${RST}  $rig: no merges in last hour ($BRANCHES unmerged branches)"
  fi
done

# --- 4b. Pipeline health ---
VERY_STALE=600  # 10 minutes — if no output, it's not working
FIXES=()        # collect fixes, print under question 2

echo ""
echo "=== 1. IS EVERYTHING FLOWING? ==="
for rig in gascity reli annie; do
  DIR="$CITY/rigs/$rig"
  [[ -d "$DIR/.git" ]] || continue

  REPO=$(git -C "$DIR" remote get-url origin 2>/dev/null | sed 's|.*github.com/||;s|\.git$||')
  ISSUES=$(gh issue list -R "$REPO" --state open --json number 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
  PRS=$(gh pr list -R "$REPO" --state open --json number 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
  ISSUES=${ISSUES:-0}; PRS=${PRS:-0}

  POLECATS_ACTIVE=0; POLECATS_STALE=0; POLECATS_VERY_STALE=0
  VERY_STALE_NAMES=()
  while IFS=' ' read -r SNAME SACTIVITY; do
    [[ "$SNAME" == ${rig}--polecat* ]] || continue
    AGE=$(( NOW - SACTIVITY ))
    if (( AGE > VERY_STALE )); then
      ((POLECATS_VERY_STALE++))
      VERY_STALE_NAMES+=("$SNAME")
    elif (( AGE > STALE_THRESHOLD )); then
      ((POLECATS_STALE++))
    else
      ((POLECATS_ACTIVE++))
    fi
  done < <(tmux -L gc list-sessions -F '#{session_name} #{session_activity}' 2>/dev/null)
  POLECATS_TOTAL=$(( POLECATS_ACTIVE + POLECATS_STALE + POLECATS_VERY_STALE ))

  HAS_REFINERY=false
  tmux -L gc has-session -t "${rig}--refinery" 2>/dev/null && HAS_REFINERY=true

  # Pipeline status line
  STATUS="  $rig: ${ISSUES} issues → ${POLECATS_ACTIVE} polecats"
  [[ $POLECATS_STALE -gt 0 ]] && STATUS+=" (+${POLECATS_STALE} stale)"
  [[ $POLECATS_VERY_STALE -gt 0 ]] && STATUS+=" (+${POLECATS_VERY_STALE} hung)"
  STATUS+=" → ${PRS} PRs"
  $HAS_REFINERY && STATUS+=" → refinery" || STATUS+=" → ${DIM}no refinery${RST}"
  echo -e "$STATUS"

  # Detect stuck states — warn now, collect fixes for later
  if (( ISSUES > 0 )) && (( POLECATS_TOTAL == 0 )); then
    warn "$rig: $ISSUES open issues but NO polecats — work not being picked up"
    FIXES+=("$rig: mail mayor to sling work|gc mail send mayor --subject 'Read $rig issues' 'Read the GitHub issues for $rig and sling work to polecats. There are $ISSUES open issues and no polecats working.'")
  elif (( ISSUES > 0 )) && (( POLECATS_ACTIVE == 0 )) && (( POLECATS_VERY_STALE > 0 )); then
    warn "$rig: all $POLECATS_VERY_STALE polecats hung 60m+ — probably finished or stuck"
    local_fix="kill hung polecats so reconciler creates fresh ones"
    local_cmd=""
    for sn in "${VERY_STALE_NAMES[@]}"; do local_cmd+="tmux -L gc kill-session -t $sn; "; done
    FIXES+=("$rig: $local_fix|$local_cmd")
  elif (( ISSUES > 0 )) && (( POLECATS_ACTIVE == 0 )) && (( POLECATS_STALE > 0 )); then
    warn "$rig: $ISSUES open issues, all $POLECATS_STALE polecats stale — work may be stuck (waiting before killing)"
  fi

  if (( PRS > 0 )) && ! $HAS_REFINERY; then
    warn "$rig: $PRS open PRs but no refinery — PRs not being merged"
    FIXES+=("$rig: mail refinery to wake and merge|gc mail send ${rig}--refinery --subject 'PRs waiting' 'There are $PRS open PRs on $rig waiting for review and merge.'")
  fi

  if (( PRS > 0 )) && $HAS_REFINERY; then
    REF_ACTIVITY=$(tmux -L gc list-sessions -F '#{session_name} #{session_activity}' 2>/dev/null \
      | grep "^${rig}--refinery " | awk '{print $2}')
    if [[ -n "$REF_ACTIVITY" ]]; then
      REF_AGE=$(( NOW - REF_ACTIVITY ))
      if (( REF_AGE > VERY_STALE )); then
        warn "$rig: refinery idle $(( REF_AGE / 60 ))m with $PRS PRs open — may be stuck"
        FIXES+=("$rig: kill stuck refinery, reconciler will restart|tmux -L gc kill-session -t ${rig}--refinery")
      fi
    fi
  fi
done

# --- Question 2: What can we do? ---
echo ""
echo "=== 2. WHAT CAN WE DO TO UNSTICK THINGS? ==="
if (( ${#FIXES[@]} == 0 )); then
  echo -e "  ${GRN}Nothing stuck — pipeline is flowing.${RST}"
else
  for i in "${!FIXES[@]}"; do
    DESC="${FIXES[$i]%%|*}"
    CMD="${FIXES[$i]#*|}"
    echo -e "  $((i+1)). $DESC"
    echo -e "     ${DIM}$ $CMD${RST}"
  done
  echo ""
  echo -e "  ${YEL}REMEMBER: IT'S YOUR JOB TO KEEP THINGS FLOWING.${RST}"
  echo "  Don't just report — fix it. Run with --fix or take the actions above."
  if $FIX; then
    echo ""
    echo "  Applying fixes..."
    for i in "${!FIXES[@]}"; do
      DESC="${FIXES[$i]%%|*}"
      CMD="${FIXES[$i]#*|}"
      echo -e "  → $DESC"
      eval "$CMD" 2>/dev/null && echo "    done" || echo "    failed"
    done
  fi
fi

# --- 5. WORK FLOW ENFORCEMENT (--fix only) ---
# Ensure the full pipeline is flowing: Issues → Code → PRs → Merged
if $FIX; then
  echo ""
  echo "=== WORK FLOW ENFORCEMENT ==="

  RUNNING_AGENTS=$(tmux -L gc list-sessions -F '#{session_name}' 2>/dev/null | sort || true)

  for rig in gascity reli annie; do
    RIG_DIR="$CITY/rigs/$rig"
    [[ -d "$RIG_DIR/.beads" ]] || continue

    REPO=$(git -C "$RIG_DIR" remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||' || true)

    # --- 5a. Orphaned bead recovery ---
    # Beads assigned to agents that aren't running → reset to pool
    IN_PROGRESS=$(cd "$RIG_DIR" && timeout 15s bd list --status=in_progress --json --limit=0 2>/dev/null || echo "[]")
    if [[ "$IN_PROGRESS" != "[]" ]] && [[ -n "$IN_PROGRESS" ]]; then
      echo "$IN_PROGRESS" | jq -r '.[] | "\(.id) \(.assignee // "")"' 2>/dev/null | while read -r BEAD_ID ASSIGNEE; do
        [[ -z "$ASSIGNEE" ]] && continue
        # Skip beads assigned to roles that are always restarted (witness, refinery, deacon, mayor)
        [[ "$ASSIGNEE" == *witness* || "$ASSIGNEE" == *refinery* || "$ASSIGNEE" == *deacon* || "$ASSIGNEE" == *mayor* ]] && continue

        # Check if the assigned agent is running (match by assignee substring in session names)
        AGENT_RUNNING=false
        if echo "$RUNNING_AGENTS" | grep -qF "${ASSIGNEE//\//-}"; then
          AGENT_RUNNING=true
        elif echo "$RUNNING_AGENTS" | grep -qF "${ASSIGNEE}"; then
          AGENT_RUNNING=true
        fi

        if ! $AGENT_RUNNING; then
          BRANCH=$(cd "$RIG_DIR" && timeout 10s bd show "$BEAD_ID" --json 2>/dev/null | jq -r '.metadata.branch // empty' || true)
          if [[ -n "$BRANCH" ]]; then
            HAS_REMOTE=$(cd "$RIG_DIR" && timeout 10s git ls-remote --heads origin "$BRANCH" 2>/dev/null | head -1 || true)
            if [[ -n "$HAS_REMOTE" ]]; then
              # Branch on origin — safe to reset, new polecat will pick it up
              (cd "$RIG_DIR" && timeout 10s bd update "$BEAD_ID" --status=open --assignee="" 2>/dev/null) && \
                ok "$rig: reset orphaned $BEAD_ID to pool (branch $BRANCH on origin)" || \
                warn "$rig: failed to reset $BEAD_ID"
            fi
            # If branch NOT on origin, leave for witness to salvage from worktree
          else
            # No branch yet — reset to pool, fresh polecat will start from scratch
            (cd "$RIG_DIR" && timeout 10s bd update "$BEAD_ID" --status=open --assignee="" 2>/dev/null) && \
              ok "$rig: reset orphaned $BEAD_ID to pool (no branch)" || \
              warn "$rig: failed to reset $BEAD_ID"
          fi
        fi
      done
    fi

    # --- 5b. Branches without PRs ---
    # Code that's been pushed but never got a PR → ensure refinery picks it up
    if [[ -n "$REPO" ]]; then
      # Find unmerged remote branches that look like polecat work
      UNMERGED=$(git -C "$RIG_DIR" branch -r --no-merged master 2>/dev/null | grep "origin/" | grep -v "HEAD" | sed 's|.*origin/||' || true)
      if [[ -n "$UNMERGED" ]]; then
        # Check if these branches have beads tracking them
        UNTRACKED_BRANCHES=0
        while IFS= read -r BRANCH; do
          [[ -z "$BRANCH" ]] && continue
          # Skip non-work branches
          [[ "$BRANCH" == "main" || "$BRANCH" == "master" || "$BRANCH" == "develop" ]] && continue
          # Check if any bead references this branch
          HAS_BEAD=$(cd "$RIG_DIR" && timeout 10s bd list --status=open --json --limit=0 2>/dev/null | jq -r --arg b "$BRANCH" '[.[] | select(.metadata.branch == $b)] | length' 2>/dev/null || echo "0")
          HAS_IP_BEAD=$(cd "$RIG_DIR" && timeout 10s bd list --status=in_progress --json --limit=0 2>/dev/null | jq -r --arg b "$BRANCH" '[.[] | select(.metadata.branch == $b)] | length' 2>/dev/null || echo "0")
          if (( HAS_BEAD == 0 )) && (( HAS_IP_BEAD == 0 )); then
            ((UNTRACKED_BRANCHES++)) || true
          fi
        done <<< "$UNMERGED"

        if (( UNTRACKED_BRANCHES > 0 )); then
          warn "$rig: $UNTRACKED_BRANCHES unmerged branch(es) with no tracking bead"
          gc nudge mayor "FLOW CHECK: $rig has $UNTRACKED_BRANCHES unmerged branch(es) on origin with no work bead tracking them. Check if they should be adopted or cleaned up." 2>/dev/null || true
        fi
      fi
    fi

    # --- 5c. PRs waiting with no refinery bead ---
    # The critical gap: polecats create PRs but sometimes crash before creating
    # a refinery bead. These PRs pile up with nobody processing them.
    if [[ -n "$REPO" ]]; then
      PR_DATA=$(timeout 15s gh pr list -R "$REPO" --state open --json number,headRefName 2>/dev/null || echo "[]")
      PR_COUNT=$(echo "$PR_DATA" | jq 'length' 2>/dev/null || echo 0)
      PR_COUNT=${PR_COUNT:-0}

      if (( PR_COUNT > 0 )); then
        # Check how many PRs have a matching refinery bead (by branch name)
        ALL_REFINERY_BEADS=$(cd "$RIG_DIR" && timeout 10s bd list --assignee="${rig}/refinery" --status=open --json --limit=0 2>/dev/null || echo "[]")
        BEADLESS_PRS=0
        BEADLESS_LIST=""

        while IFS=$'\t' read -r PR_NUM PR_BRANCH; do
          [[ -z "$PR_BRANCH" ]] && continue
          HAS_BEAD=$(echo "$ALL_REFINERY_BEADS" | jq -r --arg b "$PR_BRANCH" '[.[] | select(.metadata.branch == $b)] | length' 2>/dev/null || echo "0")
          if (( HAS_BEAD == 0 )); then
            ((BEADLESS_PRS++)) || true
            BEADLESS_LIST+="#${PR_NUM} "
          fi
        done < <(echo "$PR_DATA" | jq -r '.[] | "\(.number)\t\(.headRefName)"' 2>/dev/null)

        if (( BEADLESS_PRS > 0 )); then
          warn "$rig: $BEADLESS_PRS of $PR_COUNT open PR(s) have NO refinery bead: ${BEADLESS_LIST}"
          # Nudge refinery to scan and process all PRs directly
          gc session nudge "${rig}/refinery" "FLOW CHECK: $BEADLESS_PRS open PR(s) have no tracking bead (${BEADLESS_LIST}). Run 'gh pr list -R $REPO --state open' and process each PR: rebase on master, run tests, merge if clean. Do not wait for beads — process the PRs directly." 2>/dev/null || true
        fi

        # Also check if refinery is idle with PRs waiting
        REF_SESSION="${rig}--refinery"
        if tmux -L gc has-session -t "$REF_SESSION" 2>/dev/null; then
          REF_ACTIVITY=$(tmux -L gc list-sessions -F '#{session_name} #{session_activity}' 2>/dev/null \
            | grep "^${REF_SESSION} " | awk '{print $2}')
          REF_AGE=$(( NOW - ${REF_ACTIVITY:-$NOW} ))
          if (( REF_AGE > 1200 )); then  # 20 minutes idle with PRs waiting
            warn "$rig: refinery idle $(( REF_AGE / 60 ))m with $PR_COUNT PR(s) — killing to restart"
            tmux -L gc kill-session -t "$REF_SESSION" 2>/dev/null || true
            ok "$rig: killed idle refinery — reconciler will restart"
          fi
        else
          ok "$rig: $PR_COUNT PR(s) open, refinery not running (work_query should auto-wake)"
        fi
      fi
    fi

    # --- 5d. Issues with no work beads ---
    # Every open GitHub issue should have a bead tracking it. If not, sling it.
    if [[ -n "$REPO" ]]; then
      ISSUE_DATA=$(timeout 15s gh issue list -R "$REPO" --state open --json number,title,url --jq '.[]' 2>/dev/null || true)
      ISSUE_COUNT=$(timeout 15s gh issue list -R "$REPO" --state open --json number 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
      ISSUE_COUNT=${ISSUE_COUNT:-0}

      if (( ISSUE_COUNT > 0 )); then
        # Get all beads that reference GitHub issues (by URL pattern in title)
        ALL_BEADS=$(cd "$RIG_DIR" && timeout 15s bd list --json --limit=0 --status=open 2>/dev/null || echo "[]")
        ALL_IP_BEADS=$(cd "$RIG_DIR" && timeout 15s bd list --json --limit=0 --status=in_progress 2>/dev/null || echo "[]")
        ALL_CLOSED_RECENT=$(cd "$RIG_DIR" && timeout 15s bd list --json --limit=0 --status=closed 2>/dev/null || echo "[]")

        UNSLUNG=0
        UNSLUNG_URLS=""
        while IFS=$'\t' read -r INUM IURL; do
          [[ -z "$IURL" ]] && continue
          # Check if any bead references this issue URL (in title or metadata)
          HAS_BEAD=false
          if echo "$ALL_BEADS" | jq -e --arg u "$IURL" '.[] | select(.title | contains($u))' &>/dev/null; then
            HAS_BEAD=true
          elif echo "$ALL_IP_BEADS" | jq -e --arg u "$IURL" '.[] | select(.title | contains($u))' &>/dev/null; then
            HAS_BEAD=true
          elif echo "$ALL_CLOSED_RECENT" | jq -e --arg u "$IURL" '.[] | select(.title | contains($u))' &>/dev/null; then
            HAS_BEAD=true  # Already worked on and closed — don't re-sling
          fi

          if ! $HAS_BEAD; then
            ((UNSLUNG++)) || true
            UNSLUNG_URLS+="$IURL "
          fi
        done < <(timeout 15s gh issue list -R "$REPO" --state open --json number,url -q '.[] | "\(.number)\t\(.url)"' 2>/dev/null)

        if (( UNSLUNG > 0 )); then
          warn "$rig: $UNSLUNG of $ISSUE_COUNT open issue(s) have no work bead"
          # Nudge mayor to sling these specific issues
          gc session nudge mayor "FLOW CHECK: $rig has $UNSLUNG open issue(s) with no work bead. Sling them to polecats: $UNSLUNG_URLS" 2>/dev/null || true
        else
          ok "$rig: all $ISSUE_COUNT open issue(s) have tracking beads"
        fi
      fi
    fi

    # --- 5e. Stale session beads blocking agent starts ---
    # When agents restart, old session beads can hold aliases, preventing new sessions.
    # Cross-reference open session beads against running tmux sessions; close stale ones.
    STALE_SESSIONS=0
    SESSION_BEADS=$(cd "$CITY" && timeout 15s bd list --type=session --status=open --json --limit=0 2>/dev/null || echo "[]")
    if [[ "$SESSION_BEADS" != "[]" ]] && [[ -n "$SESSION_BEADS" ]]; then
      echo "$SESSION_BEADS" | jq -r '.[] | "\(.id)\t\(.title)"' 2>/dev/null | while IFS=$'\t' read -r SB_ID SB_TITLE; do
        [[ -z "$SB_TITLE" ]] && continue
        # Only process beads related to this rig
        [[ "$SB_TITLE" == *"$rig"* ]] || continue
        # Check if the session is actually running
        SB_SESSION="${SB_TITLE//\//-}"  # reli/refinery → reli-refinery
        SB_RUNNING=false
        if echo "$RUNNING_AGENTS" | grep -qF "$SB_SESSION"; then
          SB_RUNNING=true
        elif echo "$RUNNING_AGENTS" | grep -qF "$SB_TITLE"; then
          SB_RUNNING=true
        fi
        if ! $SB_RUNNING; then
          (cd "$CITY" && timeout 10s bd close "$SB_ID" --reason "Stale session bead — agent not running" 2>/dev/null) && \
            ok "$rig: closed stale session bead $SB_ID ($SB_TITLE)" || \
            warn "$rig: failed to close stale session bead $SB_ID"
          ((STALE_SESSIONS++)) || true
        fi
      done
    fi

    # --- 5f. Beads with no assignee (stuck in pool) ---
    if [[ -d "$RIG_DIR/.beads" ]]; then
      UNASSIGNED=$(cd "$RIG_DIR" && timeout 10s bd list --status=open --json --limit=0 2>/dev/null | \
        jq '[.[] | select((.assignee // "") == "" and (.type // "") != "warrant" and (.title // "" | test("mol-") | not))] | length' 2>/dev/null || echo 0)
      UNASSIGNED=${UNASSIGNED:-0}
      if (( UNASSIGNED > 3 )); then
        warn "$rig: $UNASSIGNED unassigned work beads sitting in pool"
      fi
    fi
  done
fi

# --- Summary ---
echo ""
if (( PROBLEMS == 0 )); then
  echo -e "${GRN}All healthy.${RST} $TOTAL agents running, no issues."
else
  echo -e "${YEL}${PROBLEMS} issue(s) found.${RST}"
  if ! $FIX; then
    echo "  Run with --fix to auto-restart dead critical agents."
  fi
fi

exit $PROBLEMS
