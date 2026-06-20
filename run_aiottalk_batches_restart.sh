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
BASE_LAEA_SYS_LOG_DIR="${LAEA_SYS_LOG_DIR:-/tmp/laea_aiottalk_logs}"
ROUND_STATUS_FILE="${ROUND_STATUS_FILE:-${LAEA_LOG_DIR}/last_round_status.env}"
BATCH_PROGRESS_FILE="${BATCH_PROGRESS_FILE:-${LAEA_LOG_DIR}/batch_progress.json}"
BATCH_INCREMENT_SEED="${BATCH_INCREMENT_SEED:-true}"
BATCH_RUN_SCRIPT="${BATCH_RUN_SCRIPT:-${SCRIPT_DIR}/run_aiottalk_rtp.sh}"
BATCH_SKIP_CLEANUP="${BATCH_SKIP_CLEANUP:-false}"
BASE_ATTACK_SEED="${ATTACK_SEED:-42}"
export LAEA_LOG_DIR ROUND_STATUS_FILE

mkdir -p "${LAEA_LOG_DIR}" "${BASE_LAEA_SYS_LOG_DIR}"

completed_rounds=0
success_rounds=0
failed_rounds=0
current_round=0
current_seed="${BASE_ATTACK_SEED}"
last_result=""
last_rc=""
batch_state="RUNNING"

write_progress() {
  python3 - \
    "${BATCH_PROGRESS_FILE}" \
    "${batch_state}" \
    "${TOTAL_ROUNDS}" \
    "${current_round}" \
    "${completed_rounds}" \
    "${success_rounds}" \
    "${failed_rounds}" \
    "${current_seed}" \
    "${last_result}" \
    "${last_rc}" \
    "${LAEA_LOG_DIR}" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

(
    path,
    state,
    total_rounds,
    current_round,
    completed_rounds,
    success_rounds,
    failed_rounds,
    current_seed,
    last_result,
    last_rc,
    dataset_dir,
) = sys.argv[1:]

payload = {
    "state": state,
    "total_rounds": int(total_rounds),
    "current_round": int(current_round),
    "completed_rounds": int(completed_rounds),
    "success_rounds": int(success_rounds),
    "failed_rounds": int(failed_rounds),
    "current_seed": int(current_seed),
    "last_result": last_result,
    "last_rc": int(last_rc) if last_rc else None,
    "dataset_dir": dataset_dir,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
parent = os.path.dirname(path)
if parent:
    os.makedirs(parent, exist_ok=True)
temp_path = path + ".tmp"
with open(temp_path, "w") as target:
    json.dump(payload, target, sort_keys=True)
    target.write("\n")
os.replace(temp_path, path)
PY
}

cleanup_round() {
  if [ "${BATCH_SKIP_CLEANUP}" = "true" ]; then
    return
  fi

  # Keep roscore/rosmaster and the dashboard node alive. Only experiment
  # components are restarted between rounds.
  pkill -f roslaunch || true
  pkill -f gzserver || true
  pkill -f gzclient || true
  pkill -f px4 || true
  pkill -f mavros || true
  pkill -f laea_aiottalk_rtp.py || true
  pkill -f experiment_manager.py || true
  pkill -f slam_kpi_logger.py || true
  pkill -f attack_scheduler.py || true
  pkill -f mission_state_node.py || true
  pkill -f supervisor_node.py || true
  pkill -f exploration_node || true
  pkill -f waypoint_generator || true
  pkill -f octomap_server_node || true
  pkill -f laserscan_to_pointcloud_assembler || true
  pkill -f depthimage_to_laserscan || true
  pkill -f topic2tf || true
  pkill -f tf2topic_tf || true
  pkill -f trajectory_msg_converter.py || true
  pkill -f geometric_controller_node || true
}

on_interrupt() {
  batch_state="STOPPED"
  write_progress
  cleanup_round
  exit 130
}
trap on_interrupt INT TERM

write_progress

for round in $(seq 1 "${TOTAL_ROUNDS}"); do
  current_round="${round}"
  if [ "${BATCH_INCREMENT_SEED}" = "true" ]; then
    current_seed=$(( BASE_ATTACK_SEED + round - 1 ))
  else
    current_seed="${BASE_ATTACK_SEED}"
  fi
  batch_state="RUNNING"
  write_progress

  echo "=============================="
  echo "[aiottalk-wrapper] ROUND ${round}/${TOTAL_ROUNDS} seed=${current_seed}"
  echo "=============================="

  rm -f "${ROUND_STATUS_FILE}"
  round_sys_log_dir="${BASE_LAEA_SYS_LOG_DIR}/round_$(printf "%03d" "${round}")"
  mkdir -p "${round_sys_log_dir}"

  set +e
  ATTACK_SEED="${current_seed}" \
    LAEA_SYS_LOG_DIR="${round_sys_log_dir}" \
    "${BATCH_RUN_SCRIPT}"
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

  completed_rounds=$(( completed_rounds + 1 ))
  if [ "${round_result}" = "SUCCESS" ] && [ "${success_delta}" -gt 0 ]; then
    success_rounds=$(( success_rounds + 1 ))
  else
    failed_rounds=$(( failed_rounds + 1 ))
  fi
  last_result="${round_result}"
  last_rc="${run_rc}"
  batch_state="RUNNING"
  write_progress

  echo "[aiottalk-wrapper] run_rc=${run_rc}, round_result=${round_result}, kept_delta=${kept_delta}, success_delta=${success_delta}"
  echo "[aiottalk-wrapper] Restarting full ROS/PX4/Gazebo stack for the next mission..."

  cleanup_round

  if [ "${round}" -lt "${TOTAL_ROUNDS}" ]; then
    batch_state="SLEEPING"
    write_progress
    echo "[aiottalk-wrapper] Sleep ${SLEEP_BETWEEN_ROUNDS}s then restart..."
    sleep "${SLEEP_BETWEEN_ROUNDS}"
  fi
done

batch_state="COMPLETED"
write_progress
echo "[aiottalk-wrapper] All rounds finished."
