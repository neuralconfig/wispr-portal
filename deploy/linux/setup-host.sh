#!/bin/bash
# One-time host prep (run as root): config dir, secrets, log dir, service user uid 10001.
# Usage: sudo ./setup-host.sh /path/to/sz-nbi.password /path/to/sz9443-leaf.pem
set -euo pipefail
PW="${1:?NBI password file}"; LEAF="${2:?SZ 9443 leaf PEM}"
id -u wispr >/dev/null 2>&1 || useradd --system --uid 10001 --user-group --home-dir /nonexistent --shell /usr/sbin/nologin wispr
install -d -m 750 -o root -g wispr /etc/wispr-portal /etc/wispr-portal/secrets
install -d -m 750 -o wispr -g wispr /var/log/wispr-portal
install -m 640 -o root -g wispr "$PW" /etc/wispr-portal/secrets/sz_nbi_password
install -m 644 -o root -g wispr "$LEAF" /etc/wispr-portal/secrets/sz9443-leaf.pem
[ -s /etc/wispr-portal/secrets/secret_key ] || (umask 027; openssl rand -hex 32 > /etc/wispr-portal/secrets/secret_key)
[ -s /etc/wispr-portal/secrets/events_token ] || (umask 027; openssl rand -hex 24 > /etc/wispr-portal/secrets/events_token)
chgrp wispr /etc/wispr-portal/secrets/secret_key /etc/wispr-portal/secrets/events_token
[ -f /etc/wispr-portal/portal.env ] || install -m 640 -o root -g wispr "$(dirname "$0")/portal.env.example" /etc/wispr-portal/portal.env
echo "ok: edit /etc/wispr-portal/portal.env, then ./run-docker.sh or ./install-native.sh"
