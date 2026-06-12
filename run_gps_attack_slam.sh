#!/usr/bin/env bash
# Run the simplest LAEA SLAM/exploration stack with GPS source attack enabled.
#
# This script intentionally does not start AIoTtalk/RTP or experiment_manager.py.
# It is for visual inspection: after GPS_ATTACK_START_SEC seconds of Gazebo sim
# time, the attack GPS model biases GPS before PX4 EKF2, so odom/pose can drift.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ========= User-tunable params =========
PX4_ROOT="${PX4_ROOT:-/home/tim/PX4-Autopilot}"
LAEA_SYS_LOG_DIR="${LAEA_SYS_LOG_DIR:-/tmp/laea_gps_attack_logs}"
ENABLE_RVIZ="${ENABLE_RVIZ:-1}"
ENABLE_DITTO_BRIDGE="${ENABLE_DITTO_BRIDGE:-0}"
DITTO_ENABLE_SLAM="${DITTO_ENABLE_SLAM:-false}"
RUN_DURATION_S="${RUN_DURATION_S:-0}"
SHOW_GPS_ATTACK_LOG="${SHOW_GPS_ATTACK_LOG:-1}"
ENABLE_GPS_ATTACK_MONITOR="${ENABLE_GPS_ATTACK_MONITOR:-1}"

# GPS attack defaults. Increase EAST_BIAS_M if the visual deviation is too small.
export LAEA_PX4_SDF="${LAEA_PX4_SDF:-iris_d435_lidar_gps_attack}"
export GPS_ATTACK_MODE="${GPS_ATTACK_MODE:-bias}"
export GPS_ATTACK_START_SEC="${GPS_ATTACK_START_SEC:-20}"
export GPS_ATTACK_END_SEC="${GPS_ATTACK_END_SEC:-0}"
export GPS_ATTACK_RAMP_SEC="${GPS_ATTACK_RAMP_SEC:-10}"
export GPS_ATTACK_EAST_BIAS_M="${GPS_ATTACK_EAST_BIAS_M:-6}"
export GPS_ATTACK_NORTH_BIAS_M="${GPS_ATTACK_NORTH_BIAS_M:-0}"
export GPS_ATTACK_UP_BIAS_M="${GPS_ATTACK_UP_BIAS_M:-0}"
export GPS_ATTACK_VELOCITY_EAST_BIAS_MPS="${GPS_ATTACK_VELOCITY_EAST_BIAS_MPS:-0}"
export GPS_ATTACK_VELOCITY_NORTH_BIAS_MPS="${GPS_ATTACK_VELOCITY_NORTH_BIAS_MPS:-0}"
export GPS_ATTACK_VELOCITY_UP_BIAS_MPS="${GPS_ATTACK_VELOCITY_UP_BIAS_MPS:-0}"

# Keep this enabled for a first run so PX4 has the attack model/plugin installed.
INSTALL_GPS_ATTACK="${INSTALL_GPS_ATTACK:-1}"
BUILD_GPS_ATTACK_PLUGIN="${BUILD_GPS_ATTACK_PLUGIN:-0}"
BUILD_JOBS="${BUILD_JOBS:-4}"

mkdir -p "${LAEA_SYS_LOG_DIR}"

# ========= ROS env =========
if [ -f /opt/ros/noetic/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/noetic/setup.bash
fi

if [ -f /home/tim/laea/devel/setup.bash ]; then
  # shellcheck disable=SC1091
  source /home/tim/laea/devel/setup.bash
fi

export PYTHONPATH="/usr/lib/python3/dist-packages:${PYTHONPATH:-}"

LOCAL_ROS_PACKAGE_PATHS=(
  "${SCRIPT_DIR}/px4_gazebo"
  "${PX4_ROOT}"
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

log() {
  echo "[run_gps_attack_slam] $*"
}

launch_bg() {
  local name="$1"
  shift
  local log_file="${LAEA_SYS_LOG_DIR}/${name}.log"
  log "launch ${name} -> ${log_file}"
  "$@" >"${log_file}" 2>&1 &
  BG_PIDS+=("$!")
}

start_gps_attack_log_monitor() {
  local log_file="${LAEA_SYS_LOG_DIR}/px4_gazebo.log"

  if [ "${SHOW_GPS_ATTACK_LOG}" != "1" ]; then
    return
  fi

  touch "${log_file}"
  log "monitor GPS attack messages from ${log_file}"
  (
    tail -n 0 -F "${log_file}" 2>/dev/null |
      stdbuf -oL grep -E "gazebo_gps_attack_plugin|GPS attack" |
      while IFS= read -r line; do
        echo "[gps_attack_log] ${line}"
      done
  ) &
  BG_PIDS+=("$!")
}

start_gps_attack_residual_monitor() {
  local log_file="${LAEA_SYS_LOG_DIR}/gps_attack_monitor.log"

  if [ "${ENABLE_GPS_ATTACK_MONITOR}" != "1" ]; then
    return
  fi

  log "monitor GPS/odom residuals -> ${log_file}"
  python3 "${SCRIPT_DIR}/px4_gazebo/gps_attack/gps_attack_monitor.py" 2>&1 |
    tee -a "${log_file}" &
  BG_PIDS+=("$!")
}

cleanup() {
  local pid
  for pid in "${BG_PIDS[@]:-}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

wait_for_topic() {
  local topic="$1"
  local timeout_s="${2:-60}"
  local start_ts="${SECONDS}"
  log "waiting for topic ${topic} (timeout ${timeout_s}s)"
  until rostopic list 2>/dev/null | grep -Fxq "${topic}"; do
    if (( SECONDS - start_ts >= timeout_s )); then
      log "ERROR: timed out waiting for topic ${topic}"
      return 1
    fi
    sleep 1
  done
}

wait_for_service() {
  local service="$1"
  local timeout_s="${2:-60}"
  local start_ts="${SECONDS}"
  log "waiting for service ${service} (timeout ${timeout_s}s)"
  until rosservice list 2>/dev/null | grep -Fxq "${service}"; do
    if (( SECONDS - start_ts >= timeout_s )); then
      log "ERROR: timed out waiting for service ${service}"
      return 1
    fi
    sleep 1
  done
}

call_until_success() {
  local label="$1"
  local pattern="$2"
  local attempts="${3:-5}"
  shift 3
  local attempt
  local out

  for attempt in $(seq 1 "${attempts}"); do
    log "${label} attempt ${attempt}/${attempts}"
    out="$("$@" 2>&1)" || true
    echo "${out}"
    if grep -q "${pattern}" <<<"${out}"; then
      return 0
    fi
    sleep 2
  done

  log "ERROR: ${label} failed"
  return 1
}

prepare_offboard_and_arm() {
  wait_for_service /mavros/set_mode 60
  wait_for_service /mavros/cmd/arming 60

  call_until_success "set OFFBOARD" "mode_sent: True" 5 \
    rosservice call /mavros/set_mode "{base_mode: 0, custom_mode: 'OFFBOARD'}"

  sleep 2

  call_until_success "arm" "success: True" 5 \
    rosservice call /mavros/cmd/arming "{value: true}"
}

publish_start_trigger() {
  log "publish /traj_start_trigger"
  rostopic pub -1 /traj_start_trigger geometry_msgs/PoseStamped "header:
  frame_id: 'map'
pose:
  position:
    x: 0.0
    y: 0.0
    z: 0.0
  orientation:
    w: 1.0"
}

ensure_gps_attack_plugin() {
  local install_log="${LAEA_SYS_LOG_DIR}/gps_attack_install.log"
  local build_log="${LAEA_SYS_LOG_DIR}/gps_attack_build.log"
  local build_gazebo_dir="${PX4_ROOT}/build/px4_sitl_default/build_gazebo"
  local plugin_so="${build_gazebo_dir}/libgazebo_gps_attack_plugin.so"
  local plugin_src="${PX4_ROOT}/Tools/sitl_gazebo/src/gazebo_gps_attack_plugin.cpp"

  if [ "${INSTALL_GPS_ATTACK}" = "1" ]; then
    log "install/update GPS attack plugin and models -> ${install_log}"
    "${SCRIPT_DIR}/px4_gazebo/gps_attack/install_gps_attack_px4.sh" >"${install_log}" 2>&1
  fi

  if [ "${BUILD_GPS_ATTACK_PLUGIN}" = "1" ] || [ ! -f "${plugin_so}" ] ||
    [ "${plugin_src}" -nt "${plugin_so}" ]; then
    log "build GPS attack plugin -> ${build_log}"
    if [ -d "${build_gazebo_dir}" ] &&
      cmake --build "${build_gazebo_dir}" --target help 2>/dev/null | grep -q "gazebo_gps_attack_plugin"; then
      cmake --build "${build_gazebo_dir}" --target gazebo_gps_attack_plugin -j"${BUILD_JOBS}" >"${build_log}" 2>&1
    else
      (
        cd "${PX4_ROOT}"
        DONT_RUN=1 make px4_sitl gazebo
      ) >"${build_log}" 2>&1
    fi
  fi

  if [ ! -f "${plugin_so}" ]; then
    log "ERROR: GPS attack plugin .so not found: ${plugin_so}"
    log "See build log: ${build_log}"
    exit 1
  fi
}

log "logs: ${LAEA_SYS_LOG_DIR}"
log "model: ${LAEA_PX4_SDF}"
log "attack: mode=${GPS_ATTACK_MODE}, start=${GPS_ATTACK_START_SEC}s, ramp=${GPS_ATTACK_RAMP_SEC}s, east=${GPS_ATTACK_EAST_BIAS_M}m, north=${GPS_ATTACK_NORTH_BIAS_M}m, up=${GPS_ATTACK_UP_BIAS_M}m, vel_east=${GPS_ATTACK_VELOCITY_EAST_BIAS_MPS}m/s"
log "this runner skips AIoTtalk/RTP and experiment_manager.py"

ensure_gps_attack_plugin

# ========= 1) Core PX4/Gazebo + controller =========
launch_bg "px4_gazebo" roslaunch px4_gazebo laea_gazebo_lidar.launch
start_gps_attack_log_monitor
sleep 5

launch_bg "controller" roslaunch px4_gazebo controller.launch
wait_for_topic /mavros/state 60
wait_for_topic /mavros/local_position/pose 60
wait_for_topic /mavros/local_position/odom 60
wait_for_topic /mavros/local_position/velocity_local 60
wait_for_topic /mavros/imu/data 60
wait_for_topic /mavros/global_position/raw/fix 60
wait_for_topic /mavros/global_position/raw/gps_vel 60
wait_for_topic /camera/depth/image_raw 90
start_gps_attack_residual_monitor
sleep 2

if [ "${ENABLE_DITTO_BRIDGE}" = "1" ]; then
  launch_bg "ditto_bridge" roslaunch laea_ditto_bridge ditto_bridge.launch enable_slam:="${DITTO_ENABLE_SLAM}"
  sleep 3
fi

# ========= 2) Mapping + No-RTP exploration =========
launch_bg "mapping" roslaunch octomap_server scan_mapping.launch
sleep 5

EXPLORE_LAUNCH="$(rospack find exploration_manager)/launch/poaozz/explore_test_NoRtp.launch"
launch_bg "explore" roslaunch "${EXPLORE_LAUNCH}"
sleep 5

if [ "${ENABLE_RVIZ}" = "1" ]; then
  RVIZ_LAUNCH="$(rospack find exploration_manager)/launch/poaozz/rviz_alg.launch"
  launch_bg "rviz" roslaunch "${RVIZ_LAUNCH}"
  sleep 3
fi

# ========= 3) OFFBOARD + ARM + start exploration =========
prepare_offboard_and_arm
sleep 2
publish_start_trigger

cat <<EOF
[run_gps_attack_slam] running.

Expected view:
  - Gazebo/RViz should show normal exploration first.
  - Around GPS_ATTACK_START_SEC=${GPS_ATTACK_START_SEC} seconds after the GPS attack plugin loads,
    the GPS bias starts ramping in before PX4 EKF2.
  - If EKF2 accepts the gradual GPS bias, /mavros/local_position/odom drifts and
    the controller/planner can make the vehicle move abnormally.

Useful checks in another terminal:
  tail -f ${LAEA_SYS_LOG_DIR}/px4_gazebo.log | grep -E "gps_attack|GPS attack"
  tail -f ${LAEA_SYS_LOG_DIR}/gps_attack_monitor.log
  rostopic echo /mavros/global_position/raw/fix
  rostopic echo /mavros/local_position/pose/pose/position

Stop with Ctrl+C.
EOF

if [ "${RUN_DURATION_S}" != "0" ]; then
  sleep "${RUN_DURATION_S}"
  exit 0
fi

while true; do
  sleep 5
done
