#!/usr/bin/env bash
set -euo pipefail

# ========= User-tunable params =========
EXP_NUM_RUNS="${EXP_NUM_RUNS:-1}"
EXP_SLEEP_BETWEEN_RUNS="${EXP_SLEEP_BETWEEN_RUNS:-2.0}"
EXP_MAX_DURATION_S="${EXP_MAX_DURATION_S:-900.0}"
EXP_FAIL_ERROR_M="${EXP_FAIL_ERROR_M:-10.0}"
EXP_FAIL_HOLD_S="${EXP_FAIL_HOLD_S:-1.0}"
EXP_FINISH_TOKEN="${EXP_FINISH_TOKEN:-finish exploration.}"
EXP_FINISH_NODE_NAME="${EXP_FINISH_NODE_NAME:-}"
EXP_DELETE_ON_NON_SUCCESS="${EXP_DELETE_ON_NON_SUCCESS:-true}"
LAEA_LOG_DIR="${LAEA_LOG_DIR:-/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip}"
LAEA_SYS_LOG_DIR="${LAEA_SYS_LOG_DIR:-/tmp/laea_nosip_logs}"
ROUND_STATUS_FILE="${ROUND_STATUS_FILE:-${LAEA_LOG_DIR}/last_round_status.env}"
ENABLE_RVIZ="${ENABLE_RVIZ:-1}"

mkdir -p "${LAEA_LOG_DIR}" "${LAEA_SYS_LOG_DIR}"

# ========= ROS env =========
if [ -f /opt/ros/noetic/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/noetic/setup.bash
fi

if [ -f /home/tim/laea/devel/setup.bash ]; then
  # shellcheck disable=SC1091
  source /home/tim/laea/devel/setup.bash
fi

export ROS_PACKAGE_PATH="/home/tim/laea/src/LAEA:/home/tim/laea/src:/opt/ros/noetic/share"

declare -a BG_PIDS=()

launch_bg() {
  local name="$1"
  shift
  local log_file="${LAEA_SYS_LOG_DIR}/${name}.log"
  echo "[run_nosip_depth] launch ${name} -> ${log_file}"
  "$@" >"${log_file}" 2>&1 &
  BG_PIDS+=("$!")
}

cleanup() {
  for pid in "${BG_PIDS[@]:-}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

count_kept_logs() {
  find "${LAEA_LOG_DIR}" -maxdepth 1 -type f -name "kpi_log_run_*.csv" | wc -l
}

echo "[run_nosip_depth] logs: ${LAEA_SYS_LOG_DIR}"
echo "[run_nosip_depth] dataset dir: ${LAEA_LOG_DIR}"
before_kept_count="$(count_kept_logs)"
echo "[run_nosip_depth] kept logs before run: ${before_kept_count}"

# ========= 1) Core stack =========
launch_bg "px4_gazebo" roslaunch px4_gazebo laea_gazebo_lidar.launch
sleep 5

launch_bg "controller" roslaunch px4_gazebo controller.launch
sleep 5

# No SIP / No IoTtalk: direct RTP stream config
launch_bg "rtp_receiver" roslaunch rtp_gazebo rtp_receiver.launch use_iottalk:=false use_sip:=false
sleep 5

launch_bg "rtp_sender" roslaunch rtp_gazebo rtp_sender.launch use_iottalk:=false use_sip:=false
sleep 5

launch_bg "mapping" roslaunch octomap_server scan_mapping.launch
sleep 5

launch_bg "explore" roslaunch exploration_manager explore_test.launch
sleep 5

if [ "${ENABLE_RVIZ}" = "1" ]; then
  launch_bg "rviz" roslaunch exploration_manager rviz_alg.launch
  sleep 3
fi

# ========= 2) OFFBOARD + ARM =========
rosrun mavros mavsys mode -c OFFBOARD || true
sleep 3
rosrun mavros mavsafety arm || true
sleep 3

# ========= 3) Experiment manager (foreground) =========
set +e
rosrun laea_twin_tools experiment_manager.py \
  _start_topic:=/traj_start_trigger \
  _start_frame_id:=map \
  _max_duration_s:="${EXP_MAX_DURATION_S}" \
  _num_runs:="${EXP_NUM_RUNS}" \
  _sleep_between_runs_s:="${EXP_SLEEP_BETWEEN_RUNS}" \
  _fail_error_m:="${EXP_FAIL_ERROR_M}" \
  _fail_hold_s:="${EXP_FAIL_HOLD_S}" \
  _rosout_topic:=/rosout_agg \
  _finish_token:="${EXP_FINISH_TOKEN}" \
  _finish_node_name:="${EXP_FINISH_NODE_NAME}" \
  _output_dir:="${LAEA_LOG_DIR}" \
  _use_roslaunch_logger:=false \
  _delete_on_non_success:="${EXP_DELETE_ON_NON_SUCCESS}"
exp_rc=$?
set -e

after_kept_count="$(count_kept_logs)"
kept_delta=$((after_kept_count - before_kept_count))

round_result="FAIL"
if [ "${exp_rc}" -eq 0 ] && [ "${kept_delta}" -gt 0 ]; then
  round_result="SUCCESS"
fi

cat > "${ROUND_STATUS_FILE}" <<EOF
ROUND_RESULT=${round_result}
EXPERIMENT_MANAGER_RC=${exp_rc}
KEPT_LOG_BEFORE=${before_kept_count}
KEPT_LOG_AFTER=${after_kept_count}
KEPT_LOG_DELTA=${kept_delta}
TIMESTAMP_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo "[run_nosip_depth] finished."
echo "[run_nosip_depth] mission logs: ${LAEA_LOG_DIR}"
echo "[run_nosip_depth] round_result=${round_result}, kept_delta=${kept_delta}, exp_rc=${exp_rc}"
echo "[run_nosip_depth] status file: ${ROUND_STATUS_FILE}"

if [ "${round_result}" = "SUCCESS" ]; then
  exit 0
fi
exit 2
