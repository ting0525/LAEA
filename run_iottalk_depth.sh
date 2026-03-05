#!/usr/bin/env bash

set -e

# Experiment manager controls (override with env vars when needed)
EXP_NUM_RUNS="${EXP_NUM_RUNS:-20}"
EXP_SLEEP_BETWEEN_RUNS="${EXP_SLEEP_BETWEEN_RUNS:-2.0}"
EXP_MAX_DURATION_S="${EXP_MAX_DURATION_S:-900.0}"
EXP_FAIL_ERROR_M="${EXP_FAIL_ERROR_M:-10.0}"
EXP_FAIL_HOLD_S="${EXP_FAIL_HOLD_S:-1.0}"
EXP_FINISH_TOKEN="${EXP_FINISH_TOKEN:-finish exploration.}"
EXP_FINISH_NODE_NAME="${EXP_FINISH_NODE_NAME:-}"
EXP_DELETE_ON_NON_SUCCESS="${EXP_DELETE_ON_NON_SUCCESS:-true}"
LAEA_LOG_DIR="${LAEA_LOG_DIR:-/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs}"
mkdir -p "${LAEA_LOG_DIR}"

# Load ROS/catkin environment first, then set package search path explicitly.
# Keep /home/tim/laea/src for the px4 symlinked package.
if [ -f /opt/ros/noetic/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/noetic/setup.bash
fi

if [ -f /home/tim/laea/devel/setup.bash ]; then
  # shellcheck disable=SC1091
  source /home/tim/laea/devel/setup.bash
fi

export ROS_PACKAGE_PATH="/home/tim/laea/src/LAEA:/home/tim/laea/src:/opt/ros/noetic/share"

gnome-terminal -- bash -c "
                            roslaunch px4_gazebo laea_gazebo_lidar.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch px4_gazebo controller.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch rtp_gazebo rtp_receiver.launch use_iottalk:=true use_sip:=false;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch rtp_gazebo rtp_sender.launch use_iottalk:=true use_sip:=false;
                            exec bash
                          "

sleep 5

# Avoid duplicate SIP bridge node name conflict.
if rosnode list 2>/dev/null | grep -qx "/SIP_SDP"; then
  rosnode kill /SIP_SDP >/dev/null 2>&1 || true
  sleep 1
fi

gnome-terminal -- bash -c "
                            python3 /home/tim/laea/src/LAEA/iottalk/sip.py;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch octomap_server scan_mapping.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch exploration_manager explore_test.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch exploration_manager rviz_alg.launch;
                            exec bash
                        "

sleep 5

gnome-terminal -- bash -c "
                            rosrun mavros mavsys mode -c OFFBOARD;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            rosrun mavros mavsafety arm;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            python3 /home/tim/laea/src/LAEA/laea_twin_tools/scripts/experiment_manager.py \
                              _num_runs:=${EXP_NUM_RUNS} \
                              _sleep_between_runs_s:=${EXP_SLEEP_BETWEEN_RUNS} \
                              _max_duration_s:=${EXP_MAX_DURATION_S} \
                              _fail_error_m:=${EXP_FAIL_ERROR_M} \
                              _fail_hold_s:=${EXP_FAIL_HOLD_S} \
                              _finish_token:=\"${EXP_FINISH_TOKEN}\" \
                              _finish_node_name:=${EXP_FINISH_NODE_NAME} \
                              _use_roslaunch_logger:=false \
                              _delete_on_non_success:=${EXP_DELETE_ON_NON_SUCCESS} \
                              _output_dir:=${LAEA_LOG_DIR};
                            exec bash
                          "
