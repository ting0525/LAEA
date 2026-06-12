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

export PYTHONPATH="/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
export EXP_NUM_RUNS=1

TOTAL_ROUNDS="${TOTAL_ROUNDS:-10}"
SLEEP_BETWEEN_ROUNDS="${SLEEP_BETWEEN_ROUNDS:-5}"
LAEA_LOG_DIR="${LAEA_LOG_DIR:-${SCRIPT_DIR}/laea_twin_tools/laea_logs/aiottalk}"
ROUND_STATUS_FILE="${ROUND_STATUS_FILE:-${LAEA_LOG_DIR}/last_round_status.env}"
export LAEA_LOG_DIR ROUND_STATUS_FILE

mkdir -p "${LAEA_LOG_DIR}"

for round in $(seq 1 "${TOTAL_ROUNDS}"); do
  echo "=============================="
  echo "[aiottalk-wrapper] ROUND ${round}/${TOTAL_ROUNDS}"
  echo "=============================="

  rm -f "${ROUND_STATUS_FILE}"

  set +e
  "${SCRIPT_DIR}/run_aiottalk_rtp.sh"
  run_rc=$?
  set -e

  round_result="NO_STATUS"
  kept_delta="0"
  success_delta="0"
  if [ -f "${ROUND_STATUS_FILE}" ]; then
    # shellcheck disable=SC1090
    source "${ROUND_STATUS_FILE}"
    round_result="${ROUND_RESULT:-UNKNOWN}"
    kept_delta="${KEPT_LOG_DELTA:-0}"
    success_delta="${SUCCESS_LOG_DELTA:-0}"
  fi

  echo "[aiottalk-wrapper] run_rc=${run_rc}, round_result=${round_result}, kept_delta=${kept_delta}, success_delta=${success_delta}"
  echo "[aiottalk-wrapper] Restarting full ROS/PX4/Gazebo stack for the next mission..."

  rosnode kill -a >/dev/null 2>&1 || true
  pkill -f roslaunch || true
  pkill -f gzserver || true
  pkill -f gzclient || true
  pkill -f px4 || true
  pkill -f mavros || true
  pkill -f roscore || true
  pkill -f rosmaster || true
  pkill -f laea_aiottalk_rtp.py || true
  pkill -f experiment_manager.py || true
  pkill -f slam_kpi_logger.py || true

  if [ "${round}" -lt "${TOTAL_ROUNDS}" ]; then
    echo "[aiottalk-wrapper] Sleep ${SLEEP_BETWEEN_ROUNDS}s then restart..."
    sleep "${SLEEP_BETWEEN_ROUNDS}"
  fi
done

echo "[aiottalk-wrapper] All rounds finished."
