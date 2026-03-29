#!/usr/bin/env bash
# Install logrotate config for gascity
# Either installs system-wide via sudo, or falls back to a user cron job.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/gc-logrotate.conf"
STATE_FILE="/mnt/ext-fast/gc/.gc/logrotate.state"

if [ ! -f "$CONF" ]; then
    echo "Error: $CONF not found" >&2
    exit 1
fi

if sudo -n true 2>/dev/null; then
    echo "Installing logrotate config to /etc/logrotate.d/gascity ..."
    sudo cp "$CONF" /etc/logrotate.d/gascity
    sudo chmod 644 /etc/logrotate.d/gascity
    echo "Done. System logrotate will pick it up automatically."
else
    echo "No passwordless sudo available. Setting up user cron job instead."
    CRON_CMD="0 3 * * * /usr/sbin/logrotate $CONF --state $STATE_FILE"
    if crontab -l 2>/dev/null | grep -qF "$CONF"; then
        echo "Cron entry for gc logrotate already exists. Skipping."
    else
        (crontab -l 2>/dev/null; echo "# gascity logrotate"; echo "$CRON_CMD") | crontab -
        echo "Cron job installed: $CRON_CMD"
    fi
fi
