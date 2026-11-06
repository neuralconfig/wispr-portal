#!/bin/bash
# Local demo: fake NBI + portal (debug mode by default; MODE=customer ./run_local.sh for the guest page).
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install -r requirements-dev.txt
CA="$(mktemp -d)/fake-ca.pem"
.venv/bin/python tools/fake_nbi.py --port 19443 --password nbi-secret --ca-out "$CA" &
FAKE=$!
trap 'kill $FAKE 2>/dev/null' EXIT
sleep 1
ENC_MAC="ENC$(printf 'AA:BB:CC:DD:EE:01' | xxd -p)"
ENC_IP="ENC$(printf '10.7.39.50' | xxd -p)"
echo
echo "Open: http://127.0.0.1:8080/?client_mac=${ENC_MAC}&uip=${ENC_IP}&nbiIP=127.0.0.1&ssid=Guest&url=http%3A%2F%2Fexample.com%2F"
echo
PORTAL_MODE="${MODE:-debug}" PORTAL_BACKEND=smartzone SZ_NBI_HOSTS=127.0.0.1 SZ_NBI_PORT=19443 \
SZ_NBI_USERNAME=nbi SZ_NBI_PASSWORD=nbi-secret SZ_CA_BUNDLE="$CA" \
  .venv/bin/python server.py
