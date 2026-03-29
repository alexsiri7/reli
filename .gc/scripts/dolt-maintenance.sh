#!/usr/bin/env bash
# dolt-maintenance.sh — Periodic Dolt maintenance to prevent corruption.
# Run via cron or systemd timer (hourly recommended).
# Does NOT require stopping the server — dolt gc works online.
set -uo pipefail

CITY="${GC_CITY_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DOLT_DIR="$CITY/.beads/dolt"
export PATH="$HOME/go/bin:$HOME/.local/bin:$PATH"

if [[ -t 1 ]]; then
  GRN='\033[0;32m'; YEL='\033[0;33m'; DIM='\033[0;90m'; RST='\033[0m'
else
  GRN=''; YEL=''; DIM=''; RST=''
fi
ok()   { echo -e "  ${GRN}OK${RST}  $*"; }
warn() { echo -e "  ${YEL}WARN${RST} $*"; }
info() { echo -e "  ${DIM}--${RST}  $*"; }

echo "=== DOLT MAINTENANCE ==="

# 1. Run dolt gc on each database to compact journals
for db_dir in "$DOLT_DIR"/*/; do
  [[ -d "$db_dir" ]] || continue
  db_name=$(basename "$db_dir")
  [[ "$db_name" == .* || "$db_name" == dolt-backup-* ]] && continue

  JOURNAL="$db_dir.dolt/noms/vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv"
  if [[ -f "$JOURNAL" ]]; then
    JSIZE=$(du -sh "$JOURNAL" 2>/dev/null | cut -f1)
    info "$db_name: journal exists ($JSIZE) — running gc..."
    if (cd "$db_dir" && timeout 120s dolt gc 2>&1); then
      ok "$db_name: gc complete"
    else
      warn "$db_name: gc failed (may need fsck)"
    fi
  else
    ok "$db_name: no journal (clean)"
  fi
done

# 2. Clean up old save files from previous fsck repairs
SAVES=0
for save in "$DOLT_DIR"/*/.dolt/noms/*_save_*; do
  [[ -f "$save" ]] || continue
  AGE_DAYS=$(( ( $(date +%s) - $(stat -c %Y "$save") ) / 86400 ))
  if (( AGE_DAYS > 7 )); then
    info "Removing old save file: $(basename "$save") (${AGE_DAYS}d old)"
    rm -f "$save"
    ((SAVES++)) || true
  fi
done
(( SAVES > 0 )) && ok "Cleaned $SAVES old save files"

# 3. Clean up old backup directories (keep last 3)
BACKUPS=( $(ls -dt "$CITY/.beads/dolt-backup-"* 2>/dev/null) )
if (( ${#BACKUPS[@]} > 3 )); then
  for ((i=3; i<${#BACKUPS[@]}; i++)); do
    BSIZE=$(du -sh "${BACKUPS[$i]}" 2>/dev/null | cut -f1)
    info "Removing old backup: $(basename "${BACKUPS[$i]}") ($BSIZE)"
    rm -rf "${BACKUPS[$i]}"
  done
  ok "Kept 3 most recent backups, removed $(( ${#BACKUPS[@]} - 3 ))"
fi

# 4. Report database sizes
echo ""
echo "=== DATABASE SIZES ==="
for db_dir in "$DOLT_DIR"/*/; do
  [[ -d "$db_dir" ]] || continue
  db_name=$(basename "$db_dir")
  [[ "$db_name" == .* || "$db_name" == dolt-backup-* ]] && continue
  SIZE=$(du -sh "$db_dir" 2>/dev/null | cut -f1)
  COMMITS=$(cd "$db_dir" && dolt log --oneline 2>/dev/null | wc -l || echo "?")
  echo "  $db_name: $SIZE ($COMMITS commits)"
done

echo ""
ok "Maintenance complete"
