#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f /opt/ros/noetic/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/noetic/setup.bash
fi
if [ -f /home/tim/laea/devel/setup.bash ]; then
  # shellcheck disable=SC1091
  source /home/tim/laea/devel/setup.bash
fi

USER_SITE="$(python3 -m site --user-site)"
export PYTHONPATH="${USER_SITE}:${PYTHONPATH:-}:/usr/lib/python3/dist-packages"

ROSCORE_PID=""
if ! rosparam list >/dev/null 2>&1; then
  mkdir -p /tmp/laea_dashboard
  roscore >/tmp/laea_dashboard/roscore.log 2>&1 &
  ROSCORE_PID="$!"
  for _ in $(seq 1 30); do
    rosparam list >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

cleanup() {
  if [ -n "${ROSCORE_PID}" ]; then
    kill "${ROSCORE_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[laea_dashboard] http://${LAEA_DASHBOARD_HOST:-127.0.0.1}:${LAEA_DASHBOARD_PORT:-8088}"
python3 "${SCRIPT_DIR}/laea_twin_tools/scripts/dashboard_server.py"
