#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p /tmp/laea_dashboard

# Keep one dashboard controller per ROS master. Multiple dashboard processes
# can disagree about experiment ownership and make stop/cleanup unreliable.
exec 9>/tmp/laea_dashboard/run_dashboard.lock
if ! flock -n 9; then
  echo "[laea_dashboard] another dashboard instance is already running." >&2
  exit 1
fi

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

if ! rosparam list >/dev/null 2>&1; then
  # Keep the ROS master independent from the Dashboard process. Experiments
  # and the Dashboard must stay on the same master across UI restarts;
  # otherwise rospy subscribers remain attached to a dead master and all
  # telemetry/trend data silently stops.
  # Do not let the independent roscore inherit fd 9. Otherwise it keeps the
  # Dashboard singleton lock after the web server exits and prevents restart.
  setsid roscore 9>&- </dev/null >/tmp/laea_dashboard/roscore.log 2>&1 &
  for _ in $(seq 1 30); do
    rosparam list >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

echo "[laea_dashboard] http://${LAEA_DASHBOARD_HOST:-127.0.0.1}:${LAEA_DASHBOARD_PORT:-12346}"
python3 "${SCRIPT_DIR}/laea_twin_tools/scripts/dashboard_server.py"
