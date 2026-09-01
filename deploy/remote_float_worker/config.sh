#!/usr/bin/env bash
# Trusted operator configuration only. Never put passwords/API keys in worker.env.
WORKER_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${WORKER_ROOT}/worker.env" ]]; then
  source "${WORKER_ROOT}/worker.env"
fi
FLOAT_ROOT="${FLOAT_ROOT:-$(dirname -- "${WORKER_ROOT}")/float-main}"
FLOAT_ENV="${FLOAT_ENV:-FLOAT}"
WORKER_PORT="${WORKER_PORT:-8011}"
SESSION_NAME="${SESSION_NAME:-float-worker}"
PHYSICAL_GPU="${PHYSICAL_GPU:-}"
if [[ ! "${SESSION_NAME}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo 'SESSION_NAME may contain only letters, digits, underscore or hyphen.' >&2
  exit 1
fi
if [[ ! "${WORKER_PORT}" =~ ^[0-9]{1,5}$ ]] || (( 10#${WORKER_PORT} < 1 || 10#${WORKER_PORT} > 65535 )); then
  echo 'WORKER_PORT must be between 1 and 65535.' >&2
  exit 1
fi
export WORKER_ROOT FLOAT_ROOT FLOAT_ENV WORKER_PORT SESSION_NAME PHYSICAL_GPU
