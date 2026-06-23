"""Constants and small shared helpers for the dashboard."""

import json
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from laea_twin_tools.msg import SupervisorCommand


PACKAGE_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = PACKAGE_DIR.parent
WEB_DIR = PACKAGE_DIR / "web" / "dashboard"
LOGS_ROOT = PACKAGE_DIR / "laea_logs"
RUN_SCRIPT = REPO_DIR / "run_aiottalk_rtp.sh"
BATCH_SCRIPT = REPO_DIR / "run_aiottalk_batches_restart.sh"
PROFILE_CONFIG = PACKAGE_DIR / "config" / "attack_profiles.yaml"
WORLD_CONFIG = PACKAGE_DIR / "config" / "world_profiles.yaml"
CONTROL_DIR = Path("/tmp/laea_dashboard")
PROCESS_STATE_PATH = CONTROL_DIR / "experiment_process.json"
DASHBOARD_RUN_ID_ENV = "LAEA_DASHBOARD_RUN_ID"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
STABLE_RUNTIME_PROFILE = "scan_mapping_explore_test"
STABLE_MAPPING_LAUNCH = "scan_mapping.launch"
STABLE_EXPLORE_LAUNCH = "explore_test.launch"
BASELINE_PX4_SDF = "iris_d435_lidar"
ATTACK_CAPABLE_PX4_SDF = "iris_d435_lidar_gps_attack"
LIVE_ATTACK_SOURCES = {"gps"}
COMPONENT_NODES = {
    "px4": "/mavros",
    "gazebo": "/gazebo",
    "planner": "/exploration_node",
    "mapping": "/octomap_server",
    "rtp": "/laea_aiottalk_rtp",
    "attack_scheduler": "/attack_scheduler",
    "attack_bridge": "/attack_gazebo_bridge",
    "mission_state": "/mission_state_node",
    "supervisor": "/mission_supervisor",
    "feedback_actuator": "/feedback_actuator",
}
EXPERIMENT_EXECUTABLE_NAMES = {
    "attack_gazebo_bridge",
    "depthimage_to_laserscan",
    "exploration_node",
    "gazebo",
    "geometric_controller_node",
    "gzclient",
    "gzserver",
    "laserscan_to_pointcloud_assembler",
    "mavros_node",
    "octomap_server_node",
    "px4",
    "topic2tf",
    "tf2topic_tf",
    "waypoint_generator",
}
EXPERIMENT_SCRIPT_NAMES = {
    "attack_scheduler.py",
    "experiment_manager.py",
    "feedback_actuator.py",
    "laea_aiottalk_rtp.py",
    "mission_state_node.py",
    "slam_kpi_logger.py",
    "supervisor_node.py",
    "trajectory_msg_converter.py",
}
EXPERIMENT_LAUNCH_FILES = {
    "controller.launch",
    "explore_test.launch",
    "laea_gazebo_lidar.launch",
    "mission_aware_runtime.launch",
    "rviz_alg.launch",
    "scan_mapping.launch",
}
EXPERIMENT_ROS_NAME_ARGS = {
    "__name:=base2depth_scan",
    "__name:=depthscan2pointcloud",
    "__name:=tf_base2camera",
    "__name:=tf_base2laser",
    "__name:=tf_map2world_link",
    "__name:=world2odom",
}
EXPERIMENT_ROS_NODE_NAMES = {
    "/attack_gazebo_bridge",
    "/attack_scheduler",
    "/base2depth_scan",
    "/depthimage_to_laserscan",
    "/depthscan2pointcloud",
    "/experiment_manager",
    "/exploration_node",
    "/feedback_actuator",
    "/gazebo",
    "/gazebo_gui",
    "/geometric_controller",
    "/laea_aiottalk_rtp",
    "/mavros",
    "/mission_state_node",
    "/mission_supervisor",
    "/octomap_server",
    "/rviz_map",
    "/sitl_0",
    "/slam_kpi_logger",
    "/tf2topic_tf",
    "/tf_base2camera",
    "/tf_base2laser",
    "/tf_map2world_link",
    "/topic2tf",
    "/traj_msg_converter",
    "/waypoint_generator",
    "/world2odom",
}
EXPERIMENT_ROS_NODE_PREFIXES = (
    "/laserscan_to_pointcloud_assembler_",
)


def level_name(value):
    return {0: "NORMAL", 1: "DEGRADED", 2: "CRITICAL"}.get(int(value), "UNKNOWN")


def feedback_name(value):
    return {
        SupervisorCommand.NONE: "NONE",
        SupervisorCommand.ALERT: "ALERT",
        SupervisorCommand.SLOW_DOWN: "SLOW_DOWN",
        SupervisorCommand.HOVER: "HOVER",
    }.get(int(value), "UNKNOWN")


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def tail_text(path, line_count=160):
    if not path or not os.path.isfile(path):
        return ""
    lines = deque(maxlen=max(1, min(int(line_count), 1000)))
    with open(path, "r", errors="replace") as source:
        for line in source:
            lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def read_json_file(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json_file(path, payload):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as target:
        json.dump(payload, target, indent=2, sort_keys=True)
        target.write("\n")
    os.replace(temp_path, path)
