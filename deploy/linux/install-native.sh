#!/bin/bash
# Native install (no Docker): venv + gunicorn under systemd, as user 'wispr'. Ubuntu 24.04 (python3.12).
# Usage: sudo ./install-native.sh /path/to/wispr-portal-checkout
set -euo pipefail
SRC="${1:?path to the wispr-portal checkout}"
apt-get install -y python3-venv >/dev/null
install -d -m 755 /opt/wispr-portal
cp -r "$SRC"/{server.py,gunicorn.conf.py,requirements.txt,wispr,templates,static,content} /opt/wispr-portal/
python3 -m venv /opt/wispr-portal/.venv
/opt/wispr-portal/.venv/bin/pip install -q --no-cache-dir -r /opt/wispr-portal/requirements.txt
chown -R root:root /opt/wispr-portal
install -m 644 "$(dirname "$0")/wispr-portal.service" /etc/systemd/system/wispr-portal.service
systemctl daemon-reload
systemctl enable wispr-portal
systemctl restart wispr-portal          # restart, so a re-install (upgrade) serves the new code
sleep 2
PORT=$(sed -n "s/^PORT=//p" /etc/wispr-portal/portal.env | tail -1)
curl -fsS "http://127.0.0.1:${PORT:-8080}/healthz" && echo
echo "log: tail -f /var/log/wispr-portal/events.jsonl   console: journalctl -fu wispr-portal"
