#!/usr/bin/env bash
# poke.sh — Send a message to an agent's tmux prompt.
#
# Unlike gc nudge/mail, this works even when the agent is idle at
# the prompt (no hook needed — it types directly into tmux).
#
# Usage:
#   scripts/poke.sh <session-name> <message>
#   scripts/poke.sh reli--polecat-2 "Commit your work and create a PR"
#   scripts/poke.sh --stale 600 "You've been idle. Check your hook for work."
#
# Options:
#   --stale <seconds>   Poke ALL sessions idle longer than <seconds>
#   --polecats          Only poke polecats (combine with --stale)

set -euo pipefail

STALE_SECS=""
POLECATS_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stale)
      STALE_SECS="$2"
      shift 2
      ;;
    --polecats)
      POLECATS_ONLY=true
      shift
      ;;
    *)
      break
      ;;
  esac
done

poke_session() {
  local name="$1"
  local msg="$2"
  # Only poke if session is at an idle prompt (not mid-output)
  # The Claude prompt shows "❯" (U+276F) or "bypass permissions" in the
  # status bar. Check for the status bar text as a reliable indicator.
  local tail
  tail=$(tmux -L gc capture-pane -t "$name" -p 2>/dev/null | tail -5)
  if echo "$tail" | grep -q "bypass permissions"; then
    tmux -L gc send-keys -t "$name" "$msg" Enter
    echo "poked $name"
  else
    echo "skipped $name (not at prompt)"
  fi
}

if [[ -n "$STALE_SECS" ]]; then
  # Poke all stale sessions
  MSG="${1:-Check your hook for work assignments.}"
  NOW=$(date +%s)
  while read -r NAME ACT; do
    IDLE=$((NOW - ACT))
    if (( IDLE > STALE_SECS )); then
      if $POLECATS_ONLY && [[ "$NAME" != *polecat* ]]; then
        continue
      fi
      poke_session "$NAME" "$MSG"
    fi
  done < <(tmux -L gc list-sessions -F '#{session_name} #{session_activity}' 2>/dev/null)
else
  # Poke a specific session
  if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <session-name> <message>"
    echo "       $0 --stale <seconds> [--polecats] <message>"
    exit 1
  fi
  poke_session "$1" "$2"
fi
