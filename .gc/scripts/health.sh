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
