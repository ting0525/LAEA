#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGS=("$@")
set --

if [ -f /opt/ros/noetic/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/noetic/setup.bash
fi
if [ -f /home/tim/laea/devel/setup.bash ]; then
  # shellcheck disable=SC1091
  source /home/tim/laea/devel/setup.bash
fi

export PYTHONPATH="/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
set -- "${ARGS[@]}"

exec python3 \
  "${SCRIPT_DIR}/laea_twin_tools/scripts/attack_terminal_monitor.py" \
  "$@"
