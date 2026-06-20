#!/usr/bin/env bash
# run_aiottalk_rtp.sh
#
# 啟動 LAEA + AIoTtalk_plus RTP pipeline（單次實驗）。
# 以 pybind11 uvgRTP 取代 rtp_gazebo 的 C++ sender/receiver。
#
# Runtime path:
#   - LAEA/PX4/Gazebo/MAVROS core stack
#   - laea_aiottalk_rtp.py for IoTtalk SDP negotiation + pybind11 RTP
#   - experiment_manager.py for one mission and KPI outcome handling
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ========= User-tunable params =========
EXP_NUM_RUNS="${EXP_NUM_RUNS:-1}"
EXP_SLEEP_BETWEEN_RUNS="${EXP_SLEEP_BETWEEN_RUNS:-2.0}"
EXP_MAX_DURATION_S="${EXP_MAX_DURATION_S:-900.0}"
EXP_FAIL_ERROR_M="${EXP_FAIL_ERROR_M:-10.0}"
EXP_FAIL_HOLD_S="${EXP_FAIL_HOLD_S:-1.0}"
EXP_FINISH_TOKEN="${EXP_FINISH_TOKEN:-finish exploration.}"
EXP_FINISH_NODE_NAME="${EXP_FINISH_NODE_NAME:-}"
EXP_DELETE_ON_NON_SUCCESS="${EXP_DELETE_ON_NON_SUCCESS:-true}"
EXP_SCENARIO="${EXP_SCENARIO:-normal}"
EXP_TRANSPORT_MODE="${EXP_TRANSPORT_MODE:-aiottalk_rtp}"
EXP_WORLD_NAME="${EXP_WORLD_NAME:-indoor_01}"
EXP_DEPTH_TOPIC="${EXP_DEPTH_TOPIC:-/rtp/depth/image_raw}"
EXP_TERMINATE_ON_HOVER="${EXP_TERMINATE_ON_HOVER:-true}"
EXP_SUPERVISOR_COMMAND_TOPIC="${EXP_SUPERVISOR_COMMAND_TOPIC:-/laea/supervisor/command}"
# Default baseline confirmed to preserve the expected RViz map.
# Callers may still override these explicitly for controlled comparisons.
LAEA_RUNTIME_PROFILE="${LAEA_RUNTIME_PROFILE:-scan_mapping_explore_test}"
MAPPING_LAUNCH="${MAPPING_LAUNCH:-scan_mapping.launch}"
MAPPING_LAUNCH_ARGS="${MAPPING_LAUNCH_ARGS:-}"
EXPLORE_LAUNCH="${EXPLORE_LAUNCH:-explore_test.launch}"
EXPLORE_LAUNCH_ARGS="${EXPLORE_LAUNCH_ARGS:-}"
LAEA_LOG_DIR="${LAEA_LOG_DIR:-${SCRIPT_DIR}/laea_twin_tools/laea_logs/aiottalk}"
EXP_MANIFEST_PATH="${EXP_MANIFEST_PATH:-${LAEA_LOG_DIR}/run_manifest.csv}"
LAEA_SYS_LOG_DIR="${LAEA_SYS_LOG_DIR:-/tmp/laea_aiottalk_logs}"
ROUND_STATUS_FILE="${ROUND_STATUS_FILE:-${LAEA_LOG_DIR}/last_round_status.env}"
ENABLE_RVIZ="${ENABLE_RVIZ:-1}"
ENABLE_DITTO_BRIDGE="${ENABLE_DITTO_BRIDGE:-1}"
DITTO_ENABLE_SLAM="${DITTO_ENABLE_SLAM:-false}"
ENABLE_AIOTTALK_RTP="${ENABLE_AIOTTALK_RTP:-1}"
ENABLE_MISSION_AWARE="${ENABLE_MISSION_AWARE:-0}"
ATTACK_PROFILE="${ATTACK_PROFILE:-none}"
ATTACK_SEED="${ATTACK_SEED:-42}"
DETECTOR_NAME="${DETECTOR_NAME:-rule_mad}"
SUPERVISOR_POLICY="${SUPERVISOR_POLICY:-hybrid}"

mkdir -p "${LAEA_LOG_DIR}" "${LAEA_SYS_LOG_DIR}"

if [ "${EXP_NUM_RUNS}" -ne 1 ]; then
  echo "[run_aiottalk_rtp] ERROR: this stack supports one SLAM mission per process." >&2
  echo "[run_aiottalk_rtp] Use run_aiottalk_batches_restart.sh with TOTAL_ROUNDS=<n> for dataset collection." >&2
  exit 2
fi

# ========= ROS env =========
if [ -f /opt/ros/noetic/setup.bash ]; then
  source /opt/ros/noetic/setup.bash
fi
if [ -f /home/tim/laea/devel/setup.bash ]; then
  source /home/tim/laea/devel/setup.bash
fi

export PYTHONPATH="/usr/lib/python3/dist-packages:${PYTHONPATH:-}"

LOCAL_ROS_PACKAGE_PATHS=(
  "${SCRIPT_DIR}/px4_gazebo"
  "/home/tim/PX4-Autopilot"
  "${SCRIPT_DIR}/laea_ditto_bridge"
  "${SCRIPT_DIR}/laea_twin_tools"
  "${SCRIPT_DIR}/rtabmap/kinect_publisher"
  "${SCRIPT_DIR}/mavros_controllers/mavros_controllers"
  "${SCRIPT_DIR}/mavros_controllers/controller_msgs"
  "${SCRIPT_DIR}/mavros_controllers/geometric_controller"
  "${SCRIPT_DIR}/mavros_controllers/trajectory_publisher"
  "${SCRIPT_DIR}/laea_planner/poly_traj"
  "${SCRIPT_DIR}/laea_planner/plan_env"
  "${SCRIPT_DIR}/laea_planner/octomap_mapping/octomap_mapping"
  "${SCRIPT_DIR}/laea_planner/octomap_mapping/octomap_server"
  "${SCRIPT_DIR}/laea_planner/active_perception"
  "${SCRIPT_DIR}/laea_planner/path_searching"
  "${SCRIPT_DIR}/laea_planner/plan_manage"
  "${SCRIPT_DIR}/laea_planner/traj_utils"
  "${SCRIPT_DIR}/laea_planner/bspline_opt"
  "${SCRIPT_DIR}/laea_planner/bspline"
  "${SCRIPT_DIR}/laea_planner/exploration_manager"
  "${SCRIPT_DIR}/laea_planner/utils/rviz_plugins"
  "${SCRIPT_DIR}/laea_planner/utils/quadrotor_msgs"
  "${SCRIPT_DIR}/laea_planner/utils/waypoint_generator"
  "${SCRIPT_DIR}/laea_planner/utils/uav_utils"
  "${SCRIPT_DIR}/laea_planner/utils/laserscan_to_pointcloud"
  "${SCRIPT_DIR}/laea_planner/utils/pose_utils"
  "${SCRIPT_DIR}/laea_planner/utils/lkh_tsp_solver"
  "${SCRIPT_DIR}/laea_planner/utils/cmake_utils"
  "${SCRIPT_DIR}/laea_planner/utils/ldlidar_stl_ros"
  "${SCRIPT_DIR}/laea_planner/utils/odom_visualization"
  "${SCRIPT_DIR}/laea_planner/utils/depthimage_to_laserscan"
)
export ROS_PACKAGE_PATH="$(IFS=:; echo "${LOCAL_ROS_PACKAGE_PATHS[*]}"):/opt/ros/noetic/share"

declare -a BG_PIDS=()

launch_bg() {
  local name="$1"; shift
  local log_file="${LAEA_SYS_LOG_DIR}/${name}.log"
  echo "[run_aiottalk_rtp] launch ${name} → ${log_file}"
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

count_success_logs() {
  python3 - "${LAEA_LOG_DIR}" <<'PY'
import csv
import glob
import os
import sys

count = 0
for path in glob.glob(os.path.join(sys.argv[1], "kpi_log_run_*.csv")):
    with open(path, newline="") as source:
        rows = list(csv.DictReader(source))
    if rows and rows[-1].get("mission_outcome") == "SUCCESS_FINISH":
        count += 1
print(count)
PY
}

wait_for_topic() {
  local topic="$1" timeout_s="${2:-60}" start_ts="${SECONDS}"
  echo "[run_aiottalk_rtp] waiting for topic ${topic} (timeout ${timeout_s}s)"
  until rostopic list 2>/dev/null | grep -Fxq "${topic}"; do
    if (( SECONDS - start_ts >= timeout_s )); then
      echo "[run_aiottalk_rtp] ERROR: timed out waiting for ${topic}" >&2
      return 1
    fi
    sleep 1
  done
}

wait_for_service() {
  local svc="$1" timeout_s="${2:-60}" start_ts="${SECONDS}"
  echo "[run_aiottalk_rtp] waiting for service ${svc} (timeout ${timeout_s}s)"
  until rosservice list 2>/dev/null | grep -Fxq "${svc}"; do
    if (( SECONDS - start_ts >= timeout_s )); then
      echo "[run_aiottalk_rtp] ERROR: timed out waiting for ${svc}" >&2
      return 1
    fi
    sleep 1
  done
}

prepare_offboard_and_arm() {
  local attempts=5
  wait_for_service /mavros/set_mode 60
  wait_for_service /mavros/cmd/arming 60
  for attempt in $(seq 1 "${attempts}"); do
    echo "[run_aiottalk_rtp] set OFFBOARD attempt ${attempt}/${attempts}"
    out="$(rosservice call /mavros/set_mode "{base_mode: 0, custom_mode: 'OFFBOARD'}" 2>&1)"
    echo "${out}"
    grep -q "mode_sent: True" <<<"${out}" && break
    [ "${attempt}" -eq "${attempts}" ] && { echo "ERROR: OFFBOARD failed" >&2; return 1; }
    sleep 2
  done
  sleep 2
  for attempt in $(seq 1 "${attempts}"); do
    echo "[run_aiottalk_rtp] arm attempt ${attempt}/${attempts}"
    out="$(rosservice call /mavros/cmd/arming "{value: true}" 2>&1)"
    echo "${out}"
    grep -q "success: True" <<<"${out}" && return 0
    [ "${attempt}" -eq "${attempts}" ] && { echo "ERROR: arm failed" >&2; return 1; }
    sleep 2
  done
}

echo "[run_aiottalk_rtp] log dir  : ${LAEA_SYS_LOG_DIR}"
echo "[run_aiottalk_rtp] kpi dir  : ${LAEA_LOG_DIR}"
echo "[run_aiottalk_rtp] profile  : ${LAEA_RUNTIME_PROFILE}"
echo "[run_aiottalk_rtp] mapping  : ${MAPPING_LAUNCH} ${MAPPING_LAUNCH_ARGS}"
echo "[run_aiottalk_rtp] explore  : ${EXPLORE_LAUNCH} ${EXPLORE_LAUNCH_ARGS}"
echo "[run_aiottalk_rtp] RTP bridge enabled: ${ENABLE_AIOTTALK_RTP}"
echo "[run_aiottalk_rtp] mission-aware: ${ENABLE_MISSION_AWARE}, attack=${ATTACK_PROFILE}, seed=${ATTACK_SEED}"
before_count="$(count_kept_logs)"
before_success_count="$(count_success_logs)"

declare -a MAPPING_LAUNCH_ARGS_ARRAY=()
declare -a EXPLORE_LAUNCH_ARGS_ARRAY=()
if [ -n "${MAPPING_LAUNCH_ARGS}" ]; then
  # shellcheck disable=SC2206
  MAPPING_LAUNCH_ARGS_ARRAY=(${MAPPING_LAUNCH_ARGS})
fi
if [ -n "${EXPLORE_LAUNCH_ARGS}" ]; then
  # shellcheck disable=SC2206
  EXPLORE_LAUNCH_ARGS_ARRAY=(${EXPLORE_LAUNCH_ARGS})
fi

# ========= 1) Core stack =========
launch_bg "px4_gazebo"  roslaunch px4_gazebo laea_gazebo_lidar.launch
sleep 5

launch_bg "controller"  roslaunch px4_gazebo controller.launch
wait_for_topic /mavros/state 60
wait_for_topic /mavros/local_position/pose 60
wait_for_topic /mavros/local_position/odom 60
wait_for_topic /mavros/local_position/velocity_local 60
wait_for_topic /mavros/imu/data 60
wait_for_topic /mavros/global_position/raw/fix 60
wait_for_topic /mavros/global_position/raw/gps_vel 60
wait_for_topic /mavros/global_position/raw/satellites 60
sleep 2

if [ "${ENABLE_DITTO_BRIDGE}" = "1" ]; then
  launch_bg "ditto_bridge" roslaunch laea_ditto_bridge ditto_bridge.launch enable_slam:="${DITTO_ENABLE_SLAM}"
  sleep 3
fi

# ── AIoTtalk_plus RTP bridge (replaces rtp_gazebo + iottalk/sip.py) ──────────
if [ "${ENABLE_AIOTTALK_RTP}" = "1" ]; then
  launch_bg "aiottalk_rtp" python3 "${SCRIPT_DIR}/laea_aiottalk_rtp.py"
  sleep 8   # IoTtalk registration + SDP negotiation needs a few seconds
fi
wait_for_topic "${EXP_DEPTH_TOPIC}" 90

if [ "${ENABLE_MISSION_AWARE}" = "1" ]; then
  launch_bg "mission_aware" roslaunch laea_twin_tools mission_aware_runtime.launch \
    attack_profile:="${ATTACK_PROFILE}" \
    attack_seed:="${ATTACK_SEED}" \
    detector_name:="${DETECTOR_NAME}" \
    supervisor_policy:="${SUPERVISOR_POLICY}" \
    depth_topic:="${EXP_DEPTH_TOPIC}"
  sleep 3
fi

# ========= 2) Mapping + Exploration =========
launch_bg "mapping" roslaunch octomap_server "${MAPPING_LAUNCH}" "${MAPPING_LAUNCH_ARGS_ARRAY[@]}"
sleep 5

launch_bg "explore" roslaunch exploration_manager "${EXPLORE_LAUNCH}" "${EXPLORE_LAUNCH_ARGS_ARRAY[@]}"
sleep 5

if [ "${ENABLE_RVIZ}" = "1" ]; then
  launch_bg "rviz" roslaunch exploration_manager rviz_alg.launch
  sleep 3
fi

# ========= 3) OFFBOARD + ARM =========
prepare_offboard_and_arm

# ========= 4) Experiment manager (foreground) =========
set +e
python3 "${SCRIPT_DIR}/laea_twin_tools/scripts/experiment_manager.py" \
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
  _scenario:="${EXP_SCENARIO}" \
  _transport_mode:="${EXP_TRANSPORT_MODE}" \
  _world_name:="${EXP_WORLD_NAME}" \
  _depth_topic:="${EXP_DEPTH_TOPIC}" \
  _use_roslaunch_logger:=false \
  _delete_on_non_success:="${EXP_DELETE_ON_NON_SUCCESS}" \
  _terminate_on_hover:="${EXP_TERMINATE_ON_HOVER}" \
  _supervisor_command_topic:="${EXP_SUPERVISOR_COMMAND_TOPIC}" \
  _manifest_path:="${EXP_MANIFEST_PATH}"
exp_rc=$?
set -e

after_count="$(count_kept_logs)"
kept_delta=$(( after_count - before_count ))
after_success_count="$(count_success_logs)"
success_delta=$(( after_success_count - before_success_count ))
round_result="FAIL"
if [ "${exp_rc}" -eq 0 ] && [ "${success_delta}" -gt 0 ]; then
  round_result="SUCCESS"
fi

cat > "${ROUND_STATUS_FILE}" <<EOF
ROUND_RESULT=${round_result}
EXPERIMENT_MANAGER_RC=${exp_rc}
KEPT_LOG_BEFORE=${before_count}
KEPT_LOG_AFTER=${after_count}
KEPT_LOG_DELTA=${kept_delta}
SUCCESS_LOG_BEFORE=${before_success_count}
SUCCESS_LOG_AFTER=${after_success_count}
SUCCESS_LOG_DELTA=${success_delta}
TIMESTAMP_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo "[run_aiottalk_rtp] done. result=${round_result} kept_delta=${kept_delta} success_delta=${success_delta} rc=${exp_rc}"
[ "${round_result}" = "SUCCESS" ] && exit 0 || exit 2
