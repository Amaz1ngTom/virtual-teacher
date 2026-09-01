#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/config.sh"
HEALTH_URL="http://127.0.0.1:${WORKER_PORT}/health"

if command -v curl >/dev/null 2>&1; then
  curl --fail --show-error --silent "${HEALTH_URL}"
  echo
else
  python -c 'import sys, urllib.request; response = urllib.request.urlopen(sys.argv[1], timeout=10); print(response.read().decode("utf-8"))' "${HEALTH_URL}"
fi
