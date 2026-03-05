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

TOTAL_ROUNDS="${TOTAL_ROUNDS:-100}"
SLEEP_BETWEEN_ROUNDS="${SLEEP_BETWEEN_ROUNDS:-5}"
ROUND_STATUS_FILE="${ROUND_STATUS_FILE:-/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip/last_round_status.env}"

for round in $(seq 1 "${TOTAL_ROUNDS}"); do
  echo "=============================="
  echo "[nosip-wrapper] ROUND ${round}/${TOTAL_ROUNDS}"
  echo "=============================="

  set +e
  "${SCRIPT_DIR}/run_nosip_depth.sh"
  run_rc=$?
  set -e

  round_result="UNKNOWN"
  kept_delta="0"
  if [ -f "${ROUND_STATUS_FILE}" ]; then
    # shellcheck disable=SC1090
    source "${ROUND_STATUS_FILE}"
    round_result="${ROUND_RESULT:-UNKNOWN}"
    kept_delta="${KEPT_LOG_DELTA:-0}"
  fi

  echo "[nosip-wrapper] run_rc=${run_rc}, round_result=${round_result}, kept_delta=${kept_delta}"

  echo "[nosip-wrapper] run_nosip_depth.sh returned. Killing all ROS nodes..."
  rosnode kill -a || true

  echo "[nosip-wrapper] Extra cleanup (best-effort)..."
  pkill -f roslaunch || true
  pkill -f gzserver || true
  pkill -f gzclient || true
  pkill -f px4 || true
  pkill -f mavros || true
  pkill -f roscore || true
  pkill -f rosmaster || true
  pkill -f RTPSender || true
  pkill -f RTPReceiver || true
  pkill -f experiment_manager.py || true
  pkill -f slam_kpi_logger.py || true

  echo "[nosip-wrapper] Sleep ${SLEEP_BETWEEN_ROUNDS}s then restart..."
  sleep "${SLEEP_BETWEEN_ROUNDS}"
done

echo "[nosip-wrapper] All rounds finished."
