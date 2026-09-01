#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/config.sh"
if [[ ! "${PHYSICAL_GPU}" =~ ^[0-9]+$ ]]; then
  echo 'Set PHYSICAL_GPU in worker.env to your assigned physical GPU index.' >&2
  exit 1
fi
command -v screen >/dev/null || { echo 'GNU Screen is required.' >&2; exit 1; }

if screen -list | grep -q "[.]${SESSION_NAME}[[:space:]]"; then
  echo "Screen 会话 ${SESSION_NAME} 已经在运行。"
  exit 0
fi

mkdir -p "${WORKER_ROOT}/logs"
screen -L -Logfile "${WORKER_ROOT}/logs/worker.log" \
  -dmS "${SESSION_NAME}" bash "${WORKER_ROOT}/run_worker.sh"

echo "已启动 Screen 会话 ${SESSION_NAME}。"
echo "查看控制台: screen -r ${SESSION_NAME}"
echo "退出查看但保持服务运行: Ctrl+A，然后按 D"
