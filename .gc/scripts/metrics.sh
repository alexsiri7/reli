#!/usr/bin/env bash
# metrics.sh — Factory performance metrics: uptime, workload, cycle times.
# Usage: scripts/metrics.sh [--json]
set -uo pipefail

CITY="${GC_CITY_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="$HOME/go/bin:$HOME/.local/bin:$PATH"
JSON=false
[[ "${1:-}" == "--json" ]] && JSON=true

NOW=$(date +%s)

# --- Colors ---
if [[ -t 1 ]] && ! $JSON; then
  GRN='\033[0;32m'; YEL='\033[0;33m'; DIM='\033[0;90m'; BLD='\033[1m'; RST='\033[0m'
else
  GRN=''; YEL=''; DIM=''; BLD=''; RST=''
fi

# ============================================================
# 1. UPTIME
# ============================================================
CONTROLLER_PID=$(pgrep -f "gc supervisor run" 2>/dev/null | head -1)
if [[ -n "$CONTROLLER_PID" ]]; then
  CONTROLLER_START=$(ps -p "$CONTROLLER_PID" -o lstart= 2>/dev/null)
  CONTROLLER_EPOCH=$(date -d "$CONTROLLER_START" +%s 2>/dev/null || echo "$NOW")
  UPTIME_SECS=$(( NOW - CONTROLLER_EPOCH ))
  UPTIME_HRS=$(( UPTIME_SECS / 3600 ))
  UPTIME_MIN=$(( (UPTIME_SECS % 3600) / 60 ))
  UPTIME_STR="${UPTIME_HRS}h ${UPTIME_MIN}m"
else
  UPTIME_SECS=0
  UPTIME_STR="DOWN"
fi

TOTAL_AGENTS=$(tmux -L gc list-sessions -F '#{session_name}' 2>/dev/null | grep -v "^s-gc-" | wc -l)
ACTIVE_AGENTS=0
STALE_AGENTS=0
while IFS=' ' read -r SNAME SACTIVITY; do
  [[ "$SNAME" == s-gc-* ]] && continue
  AGE=$(( NOW - SACTIVITY ))
  if (( AGE < 600 )); then
    ((ACTIVE_AGENTS++)) || true
  else
    ((STALE_AGENTS++)) || true
  fi
done < <(tmux -L gc list-sessions -F '#{session_name} #{session_activity}' 2>/dev/null)

# ============================================================
# 2. WORKLOAD (last 24h, last 1h)
# ============================================================
declare -A COMMITS_24H COMMITS_1H PRS_MERGED_24H PRS_OPEN ISSUES_OPEN
for rig in gascity reli annie; do
  DIR="$CITY/rigs/$rig"
  [[ -d "$DIR/.git" ]] || continue

  COMMITS_24H[$rig]=$(git -C "$DIR" log --oneline --since="24 hours ago" master 2>/dev/null | wc -l)
  COMMITS_1H[$rig]=$(git -C "$DIR" log --oneline --since="1 hour ago" master 2>/dev/null | wc -l)

  REPO=$(git -C "$DIR" remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||' || true)
  if [[ -n "$REPO" ]]; then
    PRS_OPEN[$rig]=$(timeout 10s gh pr list -R "$REPO" --state open --json number 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
    # PRs merged in last 24h
    PRS_MERGED_24H[$rig]=$(timeout 10s gh pr list -R "$REPO" --state merged --json mergedAt 2>/dev/null | \
      jq --arg since "$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-24H +%Y-%m-%dT%H:%M:%SZ)" \
      '[.[] | select(.mergedAt > $since)] | length' 2>/dev/null || echo 0)
    ISSUES_OPEN[$rig]=$(timeout 10s gh issue list -R "$REPO" --state open --json number 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
  else
    PRS_OPEN[$rig]=0
    PRS_MERGED_24H[$rig]=0
    ISSUES_OPEN[$rig]=0
  fi
done

TOTAL_COMMITS_24H=0
TOTAL_COMMITS_1H=0
TOTAL_PRS_MERGED=0
TOTAL_PRS_OPEN=0
TOTAL_ISSUES=0
for rig in gascity reli annie; do
  TOTAL_COMMITS_24H=$(( TOTAL_COMMITS_24H + ${COMMITS_24H[$rig]:-0} ))
  TOTAL_COMMITS_1H=$(( TOTAL_COMMITS_1H + ${COMMITS_1H[$rig]:-0} ))
  TOTAL_PRS_MERGED=$(( TOTAL_PRS_MERGED + ${PRS_MERGED_24H[$rig]:-0} ))
  TOTAL_PRS_OPEN=$(( TOTAL_PRS_OPEN + ${PRS_OPEN[$rig]:-0} ))
  TOTAL_ISSUES=$(( TOTAL_ISSUES + ${ISSUES_OPEN[$rig]:-0} ))
done

# ============================================================
# 3. ISSUE → MASTER CYCLE TIME
# ============================================================
# Measure issue→master cycle time using closed beads that reference GitHub issues.
# Beads have titles like "https://github.com/alexsiri7/reli/issues/287" and
# closedAt timestamps. Compare issue createdAt vs bead closedAt.
CYCLE_TMP=$(mktemp)
trap "rm -f $CYCLE_TMP" EXIT
for rig in gascity reli annie; do
  DIR="$CITY/rigs/$rig"
  [[ -d "$DIR/.beads" ]] || continue
  REPO=$(git -C "$DIR" remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||' || true)
  [[ -z "$REPO" ]] && continue

  # Get recently closed beads that reference GitHub issues
  CLOSED=$(cd "$DIR" && timeout 15s bd list --status=closed --json --limit=50 2>/dev/null || echo "[]")
  echo "$CLOSED" | jq -r '.[] | select(.title | test("github.com/.*/issues/[0-9]+")) | "\(.title)\t\(.closed_at // .updated_at)"' 2>/dev/null | while IFS=$'\t' read -r BEAD_TITLE CLOSED_AT; do
    [[ -z "$CLOSED_AT" ]] && continue

    # Extract issue number from URL
    ISSUE_NUM=""
    if [[ "$BEAD_TITLE" =~ issues/([0-9]+) ]]; then
      ISSUE_NUM="${BASH_REMATCH[1]}"
    fi
    [[ -z "$ISSUE_NUM" ]] && continue

    ISSUE_CREATED=$(timeout 5s gh issue view "$ISSUE_NUM" -R "$REPO" --json createdAt -q '.createdAt' 2>/dev/null || true)
    if [[ -n "$ISSUE_CREATED" ]]; then
      CREATED_EPOCH=$(date -d "$ISSUE_CREATED" +%s 2>/dev/null || true)
      CLOSED_EPOCH=$(date -d "$CLOSED_AT" +%s 2>/dev/null || true)
      if [[ -n "$CREATED_EPOCH" ]] && [[ -n "$CLOSED_EPOCH" ]]; then
        CYCLE=$(( CLOSED_EPOCH - CREATED_EPOCH ))
        if (( CYCLE > 0 )); then
          echo "$CYCLE" >> "$CYCLE_TMP"
        fi
      fi
    fi
  done
done

# Compute median cycle time
MEDIAN_CYCLE="N/A"
MEDIAN_CYCLE_SECS=0
CYCLE_COUNT=$(wc -l < "$CYCLE_TMP" 2>/dev/null || echo 0)
if (( CYCLE_COUNT > 0 )); then
  SORTED_LINE=$(sort -n "$CYCLE_TMP" | sed -n "$(( (CYCLE_COUNT + 1) / 2 ))p")
  MEDIAN_CYCLE_SECS=${SORTED_LINE:-0}
  CYCLE_HRS=$(( MEDIAN_CYCLE_SECS / 3600 ))
  CYCLE_MIN=$(( (MEDIAN_CYCLE_SECS % 3600) / 60 ))
  if (( CYCLE_HRS > 24 )); then
    CYCLE_DAYS=$(( CYCLE_HRS / 24 ))
    MEDIAN_CYCLE="${CYCLE_DAYS}d $(( CYCLE_HRS % 24 ))h"
  else
    MEDIAN_CYCLE="${CYCLE_HRS}h ${CYCLE_MIN}m"
  fi
fi

# ============================================================
# 4. TOKEN USAGE
# ============================================================
TOKEN_5H=$(gc costs --window 5h 2>/dev/null | tail -1 | awk '{print $NF}' || echo "0")
TOKEN_OUTPUT_5H=$(gc costs --window 5h 2>/dev/null | tail -1 | awk '{print $(NF-1)}' || echo "0")

# ============================================================
# OUTPUT
# ============================================================
if $JSON; then
  cat <<JSONEOF
{
  "timestamp": "$NOW",
  "uptime": {
    "seconds": $UPTIME_SECS,
    "display": "$UPTIME_STR"
  },
  "agents": {
    "total": $TOTAL_AGENTS,
    "active": $ACTIVE_AGENTS,
    "stale": $STALE_AGENTS
  },
  "workload_24h": {
    "commits": $TOTAL_COMMITS_24H,
    "prs_merged": $TOTAL_PRS_MERGED,
    "prs_open": $TOTAL_PRS_OPEN,
    "issues_open": $TOTAL_ISSUES
  },
  "workload_1h": {
    "commits": $TOTAL_COMMITS_1H
  },
  "rigs": {
    "gascity": { "commits_24h": ${COMMITS_24H[gascity]:-0}, "commits_1h": ${COMMITS_1H[gascity]:-0}, "prs_open": ${PRS_OPEN[gascity]:-0}, "prs_merged_24h": ${PRS_MERGED_24H[gascity]:-0}, "issues_open": ${ISSUES_OPEN[gascity]:-0} },
    "reli": { "commits_24h": ${COMMITS_24H[reli]:-0}, "commits_1h": ${COMMITS_1H[reli]:-0}, "prs_open": ${PRS_OPEN[reli]:-0}, "prs_merged_24h": ${PRS_MERGED_24H[reli]:-0}, "issues_open": ${ISSUES_OPEN[reli]:-0} },
    "annie": { "commits_24h": ${COMMITS_24H[annie]:-0}, "commits_1h": ${COMMITS_1H[annie]:-0}, "prs_open": ${PRS_OPEN[annie]:-0}, "prs_merged_24h": ${PRS_MERGED_24H[annie]:-0}, "issues_open": ${ISSUES_OPEN[annie]:-0} }
  },
  "cycle_time": {
    "median_seconds": $MEDIAN_CYCLE_SECS,
    "median_display": "$MEDIAN_CYCLE",
    "sample_count": $CYCLE_COUNT
  },
  "tokens": {
    "total_5h": "$TOKEN_5H",
    "output_5h": "$TOKEN_OUTPUT_5H"
  }
}
JSONEOF
  exit 0
fi

echo -e "${BLD}=== FACTORY METRICS ===${RST}"
echo ""

echo -e "${BLD}UPTIME${RST}"
echo -e "  Supervisor:    $UPTIME_STR"
echo -e "  Agents:        $ACTIVE_AGENTS active, $STALE_AGENTS stale, $TOTAL_AGENTS total"
echo ""

echo -e "${BLD}WORKLOAD (24h)${RST}"
printf "  %-12s %8s %8s %8s %8s %8s\n" "Rig" "Commits" "1h" "PRs Open" "Merged" "Issues"
printf "  %-12s %8s %8s %8s %8s %8s\n" "---" "---" "---" "---" "---" "---"
for rig in reli annie gascity; do
  printf "  %-12s %8s %8s %8s %8s %8s\n" \
    "$rig" "${COMMITS_24H[$rig]:-0}" "${COMMITS_1H[$rig]:-0}" \
    "${PRS_OPEN[$rig]:-0}" "${PRS_MERGED_24H[$rig]:-0}" "${ISSUES_OPEN[$rig]:-0}"
done
printf "  %-12s %8s %8s %8s %8s %8s\n" \
  "TOTAL" "$TOTAL_COMMITS_24H" "$TOTAL_COMMITS_1H" \
  "$TOTAL_PRS_OPEN" "$TOTAL_PRS_MERGED" "$TOTAL_ISSUES"
echo ""

echo -e "${BLD}CYCLE TIME${RST} (issue created → PR merged to master)"
echo -e "  Median:        $MEDIAN_CYCLE ($CYCLE_COUNT samples)"
echo ""

echo -e "${BLD}TOKEN USAGE${RST} (5h rolling window)"
echo -e "  Total:         $TOKEN_5H"
echo -e "  Output:        $TOKEN_OUTPUT_5H"
echo ""

# Rate calculations
if (( UPTIME_SECS > 3600 )); then
  UPTIME_HRS_FLOAT=$(echo "scale=1; $UPTIME_SECS / 3600" | bc)
  COMMITS_PER_HR=$(echo "scale=1; $TOTAL_COMMITS_24H / 24" | bc 2>/dev/null || echo "?")
  echo -e "${BLD}RATES${RST}"
  echo -e "  Commits/hr:    $COMMITS_PER_HR (24h avg)"
  if (( TOTAL_PRS_MERGED > 0 )); then
    echo -e "  PRs merged/day: $TOTAL_PRS_MERGED"
  fi
  echo ""
fi

# Health summary
HEALTH_ISSUES=0
(( STALE_AGENTS > 2 )) && ((HEALTH_ISSUES++)) || true
(( TOTAL_PRS_OPEN > 10 )) && ((HEALTH_ISSUES++)) || true
(( TOTAL_COMMITS_1H == 0 )) && ((HEALTH_ISSUES++)) || true
[[ "$UPTIME_STR" == "DOWN" ]] && ((HEALTH_ISSUES++)) || true

if (( HEALTH_ISSUES == 0 )); then
  echo -e "${GRN}Factory healthy — pipeline flowing.${RST}"
elif (( HEALTH_ISSUES <= 2 )); then
  echo -e "${YEL}Factory degraded — $HEALTH_ISSUES concern(s).${RST}"
else
  echo -e "\033[0;31mFactory unhealthy — $HEALTH_ISSUES concern(s).${RST}"
fi
