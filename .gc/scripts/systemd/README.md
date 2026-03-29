# Gas City systemd units

## Install
sudo cp gc-supervisor.service gc-health.service gc-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gc-supervisor.service
sudo systemctl enable --now gc-health.timer

## Check status
systemctl status gc-supervisor
systemctl list-timers gc-health.timer
journalctl -u gc-supervisor -f
journalctl -u gc-health -f
