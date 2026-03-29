#!/usr/bin/env bash
# dolt-repair.sh — Detect and repair Dolt database corruption.
# Usage: scripts/dolt-repair.sh [--dry-run]
#   --dry-run: show what would happen without making changes
set -euo pipefail

# --- City root ---
CITY="${GC_CITY_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DOLT_DIR="$CITY/.beads/dolt"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# --- PATH ---
export PATH="$HOME/go/bin:$HOME/.local/bin:$PATH"

# --- Colors (skip if not a terminal) ---
if [[ -t 1 ]]; then
  RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'; DIM='\033[0;90m'; RST='\033[0m'
else
  RED=''; YEL=''; GRN=''; DIM=''; RST=''
fi

ok()   { echo -e "  ${GRN}OK${RST}  $*"; }
warn() { echo -e "  ${YEL}WARN${RST} $*"; }
fail() { echo -e "  ${RED}FAIL${RST} $*"; }
info() { echo -e "  ${DIM}--${RST}  $*"; }

TIMESTAMP=$(date +%s)
LOGFILE="/tmp/dolt-repair-${TIMESTAMP}.log"

log() {
  echo "$*" >> "$LOGFILE"
}

log_and_print() {
  echo -e "$*"
  # Strip ANSI codes for log file
  echo "$*" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE"
}

# --- 1. Detect corruption ---
echo "=== DOLT CORRUPTION SCAN ==="
log "dolt-repair started at $(date)"
log "City root: $CITY"
log "Dry run: $DRY_RUN"

if [[ ! -d "$DOLT_DIR" ]]; then
  fail "Dolt directory not found: $DOLT_DIR"
  exit 1
fi

CORRUPTED_DBS=()

for db_dir in "$DOLT_DIR"/*/; do
  [[ -d "$db_dir" ]] || continue
  db_name=$(basename "$db_dir")
  [[ "$db_name" == .* ]] && continue
  [[ "$db_name" == dolt-backup-* ]] && continue

  JOURNAL="$db_dir.dolt/noms/vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv"
  has_journal=false
  has_checksum_error=false

  # Check for journal files
  if ls "$db_dir".dolt/noms/vvvv* &>/dev/null; then
    has_journal=true
  fi

  # Check for checksum errors in dolt logs
  for logfile in "$CITY/dolt-server.log" "$CITY/.gc/runtime/packs/dolt/dolt.log" "$CITY/.beads/dolt-server.log"; do
    if [[ -f "$logfile" ]]; then
      if tail -200 "$logfile" 2>/dev/null | grep -qi "checksum error.*$db_name\|connectionDb=$db_name.*checksum\|database.*$db_name.*corrupt\|corrupted journal\|possible data loss.*journal"; then
        has_checksum_error=true
        break
      fi
    fi
  done

  if $has_journal && $has_checksum_error; then
    fail "$db_name — CORRUPT (journal file + checksum errors)"
    CORRUPTED_DBS+=("$db_name")
    log "CORRUPT: $db_name (journal + checksum)"
  elif $has_checksum_error; then
    fail "$db_name — CORRUPT (checksum errors in logs)"
    CORRUPTED_DBS+=("$db_name")
    log "CORRUPT: $db_name (checksum)"
  elif $has_journal; then
    warn "$db_name — journal file present (may need gc, not necessarily corrupt)"
    log "JOURNAL: $db_name (journal present, no checksum errors)"
  else
    ok "$db_name"
  fi
done

# --- 2. No corruption? Exit clean ---
echo ""
if (( ${#CORRUPTED_DBS[@]} == 0 )); then
  ok "No corruption detected"
  log "No corruption detected"
  echo ""
  echo -e "${GRN}All databases healthy.${RST}"
  exit 0
fi

echo -e "${RED}Corruption detected in ${#CORRUPTED_DBS[@]} database(s): ${CORRUPTED_DBS[*]}${RST}"
log "Corruption detected in: ${CORRUPTED_DBS[*]}"

if $DRY_RUN; then
  echo ""
  echo "=== DRY RUN — would perform these steps ==="
  info "1. List tmux sessions on .gc/socket"
  info "2. Kill all agent tmux sessions"
  info "3. Wait 5 seconds for in-flight writes"
  info "4. Stop dolt server: gc dolt stop"
  info "5. Create backup: cp -a $DOLT_DIR $DOLT_DIR-backup-$TIMESTAMP"
  for db in "${CORRUPTED_DBS[@]}"; do
    info "6. Repair $db: cd $DOLT_DIR/$db && dolt fsck --revive-journal-with-data-loss"
  done
  info "7. Restart dolt: gc dolt start"
  info "8. Controller reconciliation will restart killed agents"
  echo ""
  echo -e "${YEL}Re-run without --dry-run to execute repair.${RST}"
  log "Dry run complete — no changes made"
  exit 1
fi

# --- 3. Repair sequence ---
echo ""
echo "=== REPAIR SEQUENCE ==="

# 3a. List tmux sessions
echo ""
echo "--- Active tmux sessions ---"
log_and_print "Active sessions before repair:"
if tmux -L gc list-sessions 2>/dev/null; then
  tmux -L gc list-sessions 2>/dev/null >> "$LOGFILE"
else
  info "No tmux sessions found on .gc/socket"
  log "No tmux sessions found"
fi

# 3b. Kill all agent sessions
echo ""
echo "--- Killing agent sessions ---"
log "Killing agent sessions..."
SESSIONS=$(tmux -L gc list-sessions -F '#{session_name}' 2>/dev/null || true)
if [[ -n "$SESSIONS" ]]; then
  while IFS= read -r session; do
    info "Killing session: $session"
    log "Killing session: $session"
    tmux -L gc kill-session -t "$session" 2>/dev/null || true
  done <<< "$SESSIONS"
  ok "All agent sessions killed"
else
  info "No sessions to kill"
fi

# 3c. Wait for in-flight writes
echo ""
info "Waiting 5 seconds for in-flight writes to flush..."
log "Waiting 5 seconds..."
sleep 5

# 3d. Stop dolt server
echo ""
echo "--- Stopping dolt server ---"
log "Stopping dolt server..."
if gc dolt stop 2>&1; then
  ok "Dolt server stopped"
  log "Dolt server stopped"
else
  warn "gc dolt stop returned non-zero (server may already be down)"
  log "gc dolt stop returned non-zero"
fi

# 3e. Create backup
echo ""
echo "--- Creating backup ---"
BACKUP_DIR="$DOLT_DIR-backup-$TIMESTAMP"
info "Backing up to $BACKUP_DIR"
log "Creating backup: $BACKUP_DIR"
if cp -a "$DOLT_DIR" "$BACKUP_DIR"; then
  BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
  ok "Backup created ($BACKUP_SIZE)"
  log "Backup created: $BACKUP_DIR ($BACKUP_SIZE)"
else
  fail "Backup failed — aborting repair"
  log "ABORT: backup failed"
  # Try to restart dolt even though repair is aborted
  gc dolt start 2>/dev/null || true
  exit 1
fi

# 3f. Repair each corrupted database
echo ""
echo "--- Repairing databases ---"
REPAIR_FAILURES=0
for db in "${CORRUPTED_DBS[@]}"; do
  DB_PATH="$DOLT_DIR/$db"
  info "Repairing $db..."
  log "Repairing: $db (path: $DB_PATH)"

  if (cd "$DB_PATH" && dolt fsck --revive-journal-with-data-loss 2>&1) | tee -a "$LOGFILE"; then
    ok "$db repaired"
    log "Repair succeeded: $db"
  else
    fail "$db repair failed"
    log "Repair FAILED: $db"
    ((REPAIR_FAILURES++))
  fi
done

# 3g. Restart dolt
echo ""
echo "--- Restarting dolt server ---"
log "Restarting dolt server..."
if gc dolt start 2>&1; then
  ok "Dolt server restarted"
  log "Dolt server restarted"
else
  fail "Dolt server failed to start"
  log "FAIL: dolt server failed to start"
fi

# 3h. Summary
echo ""
echo "=== REPAIR SUMMARY ==="
log "=== REPAIR SUMMARY ==="
echo "  Databases repaired: ${#CORRUPTED_DBS[@]}"
echo "  Failures: $REPAIR_FAILURES"
echo "  Backup: $BACKUP_DIR"
echo "  Log: $LOGFILE"
log "Databases repaired: ${#CORRUPTED_DBS[@]}, Failures: $REPAIR_FAILURES"

if (( REPAIR_FAILURES > 0 )); then
  echo ""
  echo -e "${RED}${REPAIR_FAILURES} repair(s) failed. Check log: $LOGFILE${RST}"
  log "Completed with $REPAIR_FAILURES failures"
  exit 1
fi

# === 4. POST-REPAIR RECOVERY ===
# All agents lost context. Wait for controller, then run flow enforcement.
echo ""
echo "=== POST-REPAIR RECOVERY ==="
log "Starting post-repair recovery..."

# 4a. Wait for controller to restart agents (2 patrol cycles = ~60s)
info "Waiting 60s for controller to restart agents..."
log "Waiting for controller reconciliation..."
sleep 60

# 4b. Verify Dolt is serving queries
info "Verifying Dolt connectivity..."
if timeout 10s bd list --type=session --json --limit=1 &>/dev/null; then
  ok "Dolt responding to queries"
  log "Dolt query check passed"
else
  fail "Dolt not responding after repair — manual intervention needed"
  log "FAIL: Dolt not responding post-repair"
  exit 1
fi

# 4c. Run health.sh --fix to enforce work flow
# This handles: orphaned beads, unmerged PRs, unslung issues, stuck agents
info "Running health.sh --fix for work flow recovery..."
log "Running health.sh --fix..."
"$CITY/scripts/health.sh" --fix 2>&1 | tee -a "$LOGFILE" || true

echo ""
echo -e "${GRN}Repair and recovery complete. All databases restored. Work resumption in progress.${RST}"
log "Repair and recovery completed successfully"
exit 0
