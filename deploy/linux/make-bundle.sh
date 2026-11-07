#!/bin/bash
# Build a self-contained bundle for a Linux x86-64 lab host:
#   wispr-portal-bundle-<commit>.tar.gz = source + deploy/linux + docker image (amd64)
# Usage: deploy/linux/make-bundle.sh [outdir]
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT="${1:-.}"; REV=$(git rev-parse --short HEAD)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
docker buildx build -q --platform linux/amd64 -t wispr-portal:smartzone --load . >/dev/null
docker save wispr-portal:smartzone | gzip > "$TMP/wispr-portal-image-amd64.tar.gz"
git archive --format=tar --prefix=wispr-portal/ HEAD | tar -x -C "$TMP"
tar -C "$TMP" -czf "$OUT/wispr-portal-bundle-$REV.tar.gz" wispr-portal wispr-portal-image-amd64.tar.gz
echo "$OUT/wispr-portal-bundle-$REV.tar.gz"
