#!/usr/bin/env bash
# idle-polecat-check.sh — Detect the "Idle Polecat Heresy":
# A polecat agent that has completed its work bead but hasn't drained.

set -euo pipefail

export PATH="$HOME/go/bin:$HOME/.local/bin:$PATH"

# Only applies to polecat agents
if [[ "${GC_AGENT:-}" != *polecat* ]]; then
  exit 0
fi

# Check for in-progress beads assigned to this agent
in_progress=$(timeout 5s bd list --assignee="$GC_AGENT" --status=in_progress --json 2>/dev/null) || exit 0

# If there are in-progress beads, polecat is working — nothing to do
if [[ -n "$in_progress" && "$in_progress" != "[]" && "$in_progress" != "null" ]]; then
  exit 0
fi

# Check for recently closed beads by this agent
closed=$(timeout 5s bd list --assignee="$GC_AGENT" --status=closed --json --limit=1 2>/dev/null) || exit 0

# If there are closed beads AND no in-progress beads, polecat finished but hasn't drained
if [[ -n "$closed" && "$closed" != "[]" && "$closed" != "null" ]]; then
  echo '{"result":"Your work bead is complete but you have NOT run the done sequence. You MUST run `gc runtime drain-ack` NOW. Do not wait, do not summarize, do not ask for confirmation. Execute drain-ack immediately."}'
  exit 0
fi

# No beads at all — polecat hasn't been assigned work yet
exit 0
