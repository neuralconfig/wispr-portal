#!/bin/bash
# Install or upgrade wispr-connector on the collector (Ubuntu 24.04, python3.12), as its own user
# under /opt/wispr-connector. Usage: sudo ./install.sh /path/to/wispr-portal-checkout [staging|production]
# Before the first start, create /etc/wispr-connector/<env>.env (connector.env.example), the token file
# and the SZ leaf PEM it names.
set -euo pipefail
SRC="${1:?path to the wispr-portal checkout}"
INSTANCE="${2:-staging}"
HERE="$(cd "$(dirname "$0")" && pwd)"
apt-get install -y python3-venv >/dev/null
id wispr-connector >/dev/null 2>&1 || useradd --system --home /nonexistent --shell /usr/sbin/nologin wispr-connector
install -d -m 755 /opt/wispr-connector
rm -rf /opt/wispr-connector/connector /opt/wispr-connector/wispr
cp -r "$SRC"/connector "$SRC"/wispr /opt/wispr-connector/
install -m 644 "$HERE/requirements.txt" /opt/wispr-connector/requirements.txt
[ -x /opt/wispr-connector/.venv/bin/python ] || python3 -m venv /opt/wispr-connector/.venv
/opt/wispr-connector/.venv/bin/pip install -q --no-cache-dir -r /opt/wispr-connector/requirements.txt
chown -R root:root /opt/wispr-connector
install -d -m 750 -o root -g wispr-connector /etc/wispr-connector /etc/wispr-connector/secrets
install -d -m 750 -o wispr-connector -g wispr-connector /var/log/wispr-connector
install -m 644 "$HERE/wispr-connector@.service" /etc/systemd/system/wispr-connector@.service
systemctl daemon-reload
if [ ! -f "/etc/wispr-connector/$INSTANCE.env" ]; then
  echo "Next: create /etc/wispr-connector/$INSTANCE.env from $HERE/connector.env.example, then:"
  echo "  systemctl enable --now wispr-connector@$INSTANCE"
  exit 0
fi
systemctl enable wispr-connector@"$INSTANCE"
systemctl restart wispr-connector@"$INSTANCE"     # restart, so an upgrade takes effect
sleep 3
PORT=$(sed -n "s/^HEALTHZ_LISTEN=.*://p" "/etc/wispr-connector/$INSTANCE.env" | tail -1)
curl -sS "http://127.0.0.1:${PORT:-9180}/healthz"; echo
echo "log: tail -f /var/log/wispr-connector/$INSTANCE.jsonl   console: journalctl -fu wispr-connector@$INSTANCE"
