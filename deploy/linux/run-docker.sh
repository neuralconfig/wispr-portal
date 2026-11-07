#!/bin/bash
# Run the portal container with host networking (real guest source IPs, no NAT).
# Usage: sudo ./run-docker.sh [debug|customer] [image-tarball.tar.gz]
set -euo pipefail
MODE="${1:-}"; TARBALL="${2:-}"
IMAGE=wispr-portal:smartzone
[ -n "$TARBALL" ] && gunzip -c "$TARBALL" | docker load
docker image inspect "$IMAGE" >/dev/null 2>&1 || IMAGE=wispr-portal:smartzone-amd64
docker rm -f wispr-portal >/dev/null 2>&1 || true
docker run -d --name wispr-portal --restart unless-stopped --network host \
  --user 10001:"$(getent group wispr | cut -d: -f3)" --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  --env-file /etc/wispr-portal/portal.env ${MODE:+-e PORTAL_MODE=$MODE} \
  -v /etc/wispr-portal/secrets:/etc/wispr-portal/secrets:ro \
  -v /var/log/wispr-portal:/var/log/wispr-portal \
  "$IMAGE"
sleep 2
PORT=$(sed -n "s/^PORT=//p" /etc/wispr-portal/portal.env | tail -1)
curl -fsS "http://127.0.0.1:${PORT:-8080}/healthz" && echo
echo "log: tail -f /var/log/wispr-portal/events.jsonl   console: docker logs -f wispr-portal"
