#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/config.sh"

if screen -list | grep -q "[.]${SESSION_NAME}[[:space:]]"; then
  screen -S "${SESSION_NAME}" -X quit
  echo "已停止 Screen 会话 ${SESSION_NAME}。"
else
  echo "Screen 会话 ${SESSION_NAME} 当前未运行。"
fi
