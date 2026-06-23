#!/usr/bin/env python3

import csv
import json
import os
import re
import signal
import site
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# ROS environments often prepend Ubuntu's Python packages. Prefer the user's
# site packages when present so Flask and its Click dependency stay compatible.
USER_SITE = site.getusersitepackages()
if USER_SITE in sys.path:
    sys.path.remove(USER_SITE)
if os.path.isdir(USER_SITE):
    sys.path.insert(0, USER_SITE)

import rosgraph
import rosnode
import rospy
import yaml
from flask import Flask, jsonify, request, send_from_directory
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import State
from sensor_msgs.msg import Image
from std_msgs.msg import String, UInt32

from laea_twin_tools.msg import (
    AttackCommand,
    AttackStatus,
    MissionState,
    SupervisorCommand,
)


from dashboard.common import *  # noqa: F401,F403  constants, utils, file helpers
from dashboard.procutil import *  # noqa: F401,F403  process-tree cleanup
from dashboard.roscleanup import *  # noqa: F401,F403  ROS registration cleanup


def profile_catalog():
    definitions = load_profile_defs()
    catalog = [
        {
            "name": "none",
            "source": "none",
            "mode": "none",
            "severity": "none",
            "vector": [0.0, 0.0, 0.0],
            "scalar": 0.0,
            "live_supported": True,
            "note": "clean baseline",
        }
    ]
    for name in sorted(definitions):
        definition = dict(definitions[name] or {})
        source = str(definition.get("source", "none"))
        live_supported = source in LIVE_ATTACK_SOURCES
        catalog.append(
            {
                "name": name,
                "source": source,
                "mode": str(definition.get("mode", "none")),
                "severity": str(definition.get("severity", "none")),
                "ramp_s": float(definition.get("ramp_s", 0.0)),
                "duration_s": float(definition.get("duration_s", 0.0)),
                "recovery_s": float(definition.get("recovery_s", 0.0)),
                "vector": list(definition.get("vector", [0.0, 0.0, 0.0])),
                "scalar": float(definition.get("scalar", 0.0)),
                "live_supported": live_supported,
                "note": (
                    "source-layer injector connected"
                    if live_supported
                    else "profile only; injector not connected"
                ),
            }
        )
    return catalog


def load_world_defs():
    try:
        with open(WORLD_CONFIG, "r") as source:
            return dict(yaml.safe_load(source) or {}).get("worlds", {})
    except (OSError, yaml.YAMLError):
        return {}


def normalized_world_profile(name, definitions=None):
    definitions = definitions if definitions is not None else load_world_defs()
    if name not in definitions:
        raise ValueError("Unknown world profile.")

    definition = dict(definitions[name] or {})
    world_file = Path(
        os.path.expandvars(os.path.expanduser(str(definition.get("world_file", ""))))
    )
    if not world_file.is_file():
        raise ValueError(f"World file is unavailable: {world_file}")

    spawn_source = dict(definition.get("spawn") or {})
    planner_source = dict(definition.get("planner") or {})

    def number(source, key, default):
        try:
            return float(source.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {name}.{key}.") from exc

    spawn = {
        "x": number(spawn_source, "x", 0.0),
        "y": number(spawn_source, "y", 0.0),
        "z": number(spawn_source, "z", 1.0),
        "roll": number(spawn_source, "roll", 0.0),
        "pitch": number(spawn_source, "pitch", 0.0),
        "yaw": number(spawn_source, "yaw", 0.0),
    }
    planner = {
        "map_size_x": number(planner_source, "map_size_x", 80.0),
        "map_size_y": number(planner_source, "map_size_y", 80.0),
        "map_size_z": number(planner_source, "map_size_z", 3.0),
        "box_x_min": number(planner_source, "box_x_min", -23.0),
        "box_y_min": number(planner_source, "box_y_min", -11.0),
        "box_z_min": number(planner_source, "box_z_min", -0.1),
        "box_x_max": number(planner_source, "box_x_max", 23.0),
        "box_y_max": number(planner_source, "box_y_max", 11.0),
        "box_z_max": number(planner_source, "box_z_max", 2.3),
    }
    for axis in ("x", "y", "z"):
        if planner[f"box_{axis}_min"] >= planner[f"box_{axis}_max"]:
            raise ValueError(f"Invalid {name} planner boundary for axis {axis}.")

    return {
        "name": name,
        "label": str(definition.get("label", name)),
        "description": str(definition.get("description", "")),
        "world_file": str(world_file.resolve()),
        "spawn": spawn,
        "planner": planner,
    }


def world_catalog():
    definitions = load_world_defs()
    catalog = []
    for name in definitions:
        try:
            profile = normalized_world_profile(name, definitions)
            profile["available"] = True
            profile["error"] = ""
        except ValueError as exc:
            definition = dict(definitions.get(name) or {})
            profile = {
                "name": name,
                "label": str(definition.get("label", name)),
                "description": str(definition.get("description", "")),
                "available": False,
                "error": str(exc),
            }
        catalog.append(profile)
    return catalog


def runtime_capabilities(process, components):
    running = bool(process.get("running"))

    def online(*keys):
        return all(components.get(key, {}).get("online", False) for key in keys)

    return [
        {
            "key": "experiment_control",
            "name": "單次實驗控制",
            "maturity": "ready",
            "runtime": "active" if running else "idle",
            "detail": STABLE_RUNTIME_PROFILE,
        },
        {
            "key": "batch_collection",
            "name": "自動訓練資料蒐集",
            "maturity": "ready",
            "runtime": (
                "active"
                if running and process.get("collection_mode") == "batch"
                else "idle"
            ),
            "detail": "restart each round; retain SUCCESS_FINISH only",
        },
        {
            "key": "gps_attack",
            "name": "GPS source-layer attack",
            "maturity": "ready",
            "runtime": (
                "online" if online("gazebo", "attack_bridge") else "offline"
            ),
            "detail": "position bias and velocity bias",
        },
        {
            "key": "mission_state",
            "name": "Mission State 評估",
            "maturity": "ready",
            "runtime": "online" if online("mission_state") else "offline",
            "detail": "localization / perception / planner / flight safety",
        },
        {
            "key": "supervisor",
            "name": "Supervisor Alert",
            "maturity": "ready",
            "runtime": "online" if online("supervisor") else "offline",
            "detail": "Alert and policy escalation",
        },
        {
            "key": "hover",
            "name": "HOVER feedback",
            "maturity": "ready",
            "runtime": (
                "online"
                if online("supervisor", "feedback_actuator", "planner")
                else "offline"
            ),
            "detail": "planner pause; experiment ends as SAFETY_HOVER",
        },
        {
            "key": "slow_down",
            "name": "SLOW_DOWN feedback",
            "maturity": "partial",
            "runtime": "command_only",
            "detail": "speed_scale is published; planner speed actuator pending",
        },
        {
            "key": "imu_baro_attack",
            "name": "IMU / Barometer attack",
            "maturity": "partial",
            "runtime": "profile_only",
            "detail": "profiles exist; Gazebo injectors pending",
        },
    ]

class ExperimentProcess:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.started_at = None
        self.ended_at = None
        self.exit_code = None
        self.log_path = ""
        self.dataset_dir = str(LOGS_ROOT / "dashboard")
        self.progress_path = ""
        self.config_path = ""
        self.config = {}
        self.root_pid = None
        self.run_id = ""
        self.last_stop_report = {}
        self._recover_control_state_locked()

    def _recover_control_state_locked(self):
        state = read_json_file(str(PROCESS_STATE_PATH))
        pid = int(state.get("pid") or 0)
        table = process_table()
        if pid in table and (
            process_run_id(pid) == state.get("run_id")
            or command_is_runner(table[pid]["argv"])
        ):
            self.root_pid = pid
            self.run_id = str(state.get("run_id", ""))
            self.started_at = state.get("started_at")
            self.log_path = str(state.get("log_path", ""))
            self.dataset_dir = str(state.get("dataset_dir", self.dataset_dir))
            self.progress_path = str(state.get("progress_path", ""))
            self.config_path = str(state.get("config_path", ""))
            self.config = dict(state.get("config") or {})
            return

        roots = discover_experiment_roots(table)
        if roots:
            self.root_pid = min(roots)
            environment = process_environment(self.root_pid)
            self.run_id = environment.get(DASHBOARD_RUN_ID_ENV, "")
            self.dataset_dir = environment.get("LAEA_LOG_DIR", self.dataset_dir)
            self.progress_path = environment.get(
                "BATCH_PROGRESS_FILE",
                str(Path(self.dataset_dir) / "batch_progress.json"),
            )
            argv = table[self.root_pid]["argv"]
            self.config = {
                "collection_mode": (
                    "batch" if str(BATCH_SCRIPT) in argv else "single"
                ),
                "world_name": environment.get("EXP_WORLD_NAME", ""),
                "scenario": environment.get("EXP_SCENARIO", ""),
            }

    def _active_roots_locked(self, table=None):
        table = table or process_table()
        roots = discover_experiment_roots(table)
        if self.process is not None and self.process.poll() is None:
            roots.add(self.process.pid)
        if self.root_pid in table:
            roots.add(self.root_pid)
        if roots:
            self.root_pid = min(roots)
        return roots

    def _write_control_state_locked(self):
        if not self.root_pid:
            return
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        write_json_file(
            str(PROCESS_STATE_PATH),
            {
                "pid": self.root_pid,
                "pgid": os.getpgid(self.root_pid),
                "run_id": self.run_id,
                "started_at": self.started_at,
                "log_path": self.log_path,
                "dataset_dir": self.dataset_dir,
                "progress_path": self.progress_path,
                "config_path": self.config_path,
                "config": self.config,
            },
        )

    @staticmethod
    def _clear_control_state():
        try:
            PROCESS_STATE_PATH.unlink()
        except FileNotFoundError:
            pass

    def _refresh_locked(self):
        if self.process is not None:
            code = self.process.poll()
            if code is not None and self.exit_code is None:
                self.exit_code = code
                self.ended_at = time.time()
        if not self._active_roots_locked():
            self.root_pid = None
            self._clear_control_state()

    def start(self, config):
        with self.lock:
            self._refresh_locked()
            if self._active_roots_locked():
                raise RuntimeError("An experiment is already running.")

            mode = config["collection_mode"]
            runner = BATCH_SCRIPT if mode == "batch" else RUN_SCRIPT
            if not runner.is_file() or not os.access(str(runner), os.X_OK):
                raise RuntimeError(f"Experiment runner is unavailable: {runner}")

            dataset_name = config["dataset_name"]
            dataset_dir = (LOGS_ROOT / dataset_name).resolve()
            logs_root = LOGS_ROOT.resolve()
            if logs_root not in dataset_dir.parents and dataset_dir != logs_root:
                raise ValueError("Invalid dataset name.")
            dataset_dir.mkdir(parents=True, exist_ok=True)

            system_log_dir = Path("/tmp/laea_dashboard") / utc_timestamp()
            system_log_dir.mkdir(parents=True, exist_ok=True)
            process_log = system_log_dir / (
                "collection.log" if mode == "batch" else "experiment.log"
            )
            progress_path = dataset_dir / "batch_progress.json"
            config_path = dataset_dir / f"collection_{utc_timestamp()}.json"
            if mode == "batch":
                try:
                    progress_path.unlink()
                except FileNotFoundError:
                    pass

            env = os.environ.copy()
            self.run_id = uuid.uuid4().hex
            env.update(
                {
                    DASHBOARD_RUN_ID_ENV: self.run_id,
                    "EXP_NUM_RUNS": "1",
                    "EXP_SCENARIO": config["scenario"],
                    "EXP_WORLD_NAME": config["world_name"],
                    "EXP_WORLD_FILE": config["world_profile"]["world_file"],
                    "EXP_SPAWN_X": str(config["world_profile"]["spawn"]["x"]),
                    "EXP_SPAWN_Y": str(config["world_profile"]["spawn"]["y"]),
                    "EXP_SPAWN_Z": str(config["world_profile"]["spawn"]["z"]),
                    "EXP_SPAWN_ROLL": str(
                        config["world_profile"]["spawn"]["roll"]
                    ),
                    "EXP_SPAWN_PITCH": str(
                        config["world_profile"]["spawn"]["pitch"]
                    ),
                    "EXP_SPAWN_YAW": str(
                        config["world_profile"]["spawn"]["yaw"]
                    ),
                    "EXP_MAP_SIZE_X": str(
                        config["world_profile"]["planner"]["map_size_x"]
                    ),
                    "EXP_MAP_SIZE_Y": str(
                        config["world_profile"]["planner"]["map_size_y"]
                    ),
                    "EXP_MAP_SIZE_Z": str(
                        config["world_profile"]["planner"]["map_size_z"]
                    ),
                    "EXP_BOX_X_MIN": str(
                        config["world_profile"]["planner"]["box_x_min"]
                    ),
                    "EXP_BOX_Y_MIN": str(
                        config["world_profile"]["planner"]["box_y_min"]
                    ),
                    "EXP_BOX_Z_MIN": str(
                        config["world_profile"]["planner"]["box_z_min"]
                    ),
                    "EXP_BOX_X_MAX": str(
                        config["world_profile"]["planner"]["box_x_max"]
                    ),
                    "EXP_BOX_Y_MAX": str(
                        config["world_profile"]["planner"]["box_y_max"]
                    ),
                    "EXP_BOX_Z_MAX": str(
                        config["world_profile"]["planner"]["box_z_max"]
                    ),
                    "EXP_MAX_DURATION_S": str(config["max_duration_s"]),
                    "EXP_DELETE_ON_NON_SUCCESS": "true",
                    "EXP_TERMINATE_ON_HOVER": "true",
                    "EXP_MANIFEST_PATH": str(dataset_dir / "run_manifest.csv"),
                    "LAEA_LOG_DIR": str(dataset_dir),
                    "LAEA_SYS_LOG_DIR": str(system_log_dir / "components"),
                    "ENABLE_RVIZ": "1" if config["enable_rviz"] else "0",
                    "ENABLE_GAZEBO_GUI": "0",
                    "ENABLE_DITTO_BRIDGE": "1" if config["enable_ditto"] else "0",
                    "ENABLE_AIOTTALK_RTP": "1" if config["enable_rtp"] else "0",
                    "ENABLE_MISSION_AWARE": "1",
                    # The standard iris_d435_lidar model has no subscriber for
                    # runtime attack commands. This drop-in variant behaves as
                    # a normal GPS sensor while attacks are disabled and lets
                    # the Dashboard activate source-layer GPS injection later.
                    "LAEA_PX4_SDF": ATTACK_CAPABLE_PX4_SDF,
                    "LAEA_RUNTIME_PROFILE": STABLE_RUNTIME_PROFILE,
                    "MAPPING_LAUNCH": STABLE_MAPPING_LAUNCH,
                    "EXPLORE_LAUNCH": STABLE_EXPLORE_LAUNCH,
                    "ATTACK_PROFILE": config["attack_profile"],
                    "ATTACK_SEED": str(config["attack_seed"]),
                    "DETECTOR_NAME": config["detector_name"],
                    "SUPERVISOR_POLICY": config["supervisor_policy"],
                    "TOTAL_ROUNDS": str(config["total_rounds"]),
                    "SLEEP_BETWEEN_ROUNDS": str(
                        config["sleep_between_rounds_s"]
                    ),
                    "BATCH_INCREMENT_SEED": (
                        "true" if config["increment_seed"] else "false"
                    ),
                    "BATCH_PROGRESS_FILE": str(progress_path),
                }
            )

            if not rospy.is_shutdown():
                try:
                    monitor.publish_override("NONE", "dashboard_start_reset")
                except rospy.ROSException as exc:
                    rospy.logwarn("Dashboard reset override failed: %s", exc)
            time.sleep(0.1)
            write_json_file(
                str(config_path),
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "runner": str(runner),
                    **config,
                },
            )
            log_handle = open(process_log, "a", buffering=1)
            try:
                self.process = subprocess.Popen(
                    [str(runner)],
                    cwd=str(REPO_DIR),
                    env=env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            finally:
                log_handle.close()

            self.started_at = time.time()
            self.ended_at = None
            self.exit_code = None
            self.log_path = str(process_log)
            self.dataset_dir = str(dataset_dir)
            self.progress_path = str(progress_path) if mode == "batch" else ""
            self.config_path = str(config_path)
            self.config = dict(config)
            self.root_pid = self.process.pid
            self.last_stop_report = {}
            self._write_control_state_locked()
            return self.snapshot_locked()

    def stop(self):
        with self.lock:
            self._refresh_locked()
            process = self.process
            table = process_table()
            roots = self._active_roots_locked(table)
            run_ids = {self.run_id}
            for root_pid in roots:
                run_ids.add(process_run_id(root_pid))
            target_pids = set(roots)
            target_pids.update(descendant_pids(roots, table))
            target_pids.update(experiment_component_pids(table, run_ids))
            target_groups = {
                table[pid]["pgid"]
                for pid in roots
                if pid in table and table[pid]["pgid"] == pid
            }

        escalation = ["SIGINT"]
        signal_process_tree(target_pids, target_groups, signal.SIGINT)
        remaining = wait_for_processes(target_pids, 8.0)
        remaining.update(
            live_pids(experiment_component_pids(process_table(), run_ids))
        )
        if remaining:
            escalation.append("SIGTERM")
            signal_process_tree(remaining, target_groups, signal.SIGTERM)
            remaining = wait_for_processes(remaining, 4.0)
            remaining.update(
                live_pids(experiment_component_pids(process_table(), run_ids))
            )
        if remaining:
            escalation.append("SIGKILL")
            signal_process_tree(remaining, target_groups, signal.SIGKILL)
            remaining = wait_for_processes(remaining, 2.0)
            remaining.update(
                live_pids(experiment_component_pids(process_table(), run_ids))
            )

        if process is not None:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

        # Processes can disappear without unregistering from the ROS master.
        # Purge only known experiment nodes; keep dashboard and /rosout alive.
        time.sleep(0.5)
        purged_ros_nodes, ros_cleanup_errors = purge_experiment_ros_nodes()
        remaining_ros_nodes = registered_experiment_ros_nodes()
        cleanup_complete = (
            not remaining and not remaining_ros_nodes and not ros_cleanup_errors
        )

        with self.lock:
            self._refresh_locked()
            self.ended_at = time.time()
            self.root_pid = None
            self._clear_control_state()
            update_stopped_progress(
                self.progress_path,
                cleanup_complete=cleanup_complete,
                remaining_pids=remaining,
                remaining_ros_nodes=remaining_ros_nodes,
            )
            self.last_stop_report = {
                "cleanup_complete": cleanup_complete,
                "target_count": len(target_pids),
                "remaining_pids": sorted(remaining),
                "purged_ros_nodes": purged_ros_nodes,
                "remaining_ros_nodes": remaining_ros_nodes,
                "errors": ros_cleanup_errors,
                "escalation": escalation,
            }
            snapshot = self.snapshot_locked()
            snapshot["stop_report"] = dict(self.last_stop_report)
            return snapshot

    def snapshot_locked(self):
        self._refresh_locked()
        table = process_table()
        roots = self._active_roots_locked(table)
        residual_pids = live_pids(experiment_component_pids(table))
        residual_ros_nodes = registered_experiment_ros_nodes()
        running = bool(roots)
        return {
            "running": running,
            "pid": min(roots) if roots else None,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "log_path": self.log_path,
            "dataset_dir": self.dataset_dir,
            "config_path": self.config_path,
            "collection_mode": self.config.get("collection_mode", "single"),
            "batch_progress": read_json_file(self.progress_path),
            "config": self.config,
            "cleanup_needed": (
                not running and bool(residual_pids or residual_ros_nodes)
            ),
            "residual_process_count": len(residual_pids) if not running else 0,
            "residual_ros_nodes": residual_ros_nodes if not running else [],
            "last_stop_report": self.last_stop_report,
        }

    def snapshot(self):
        with self.lock:
            return self.snapshot_locked()



class RosMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.received = {}
        self.state = {
            "mavros": {},
            "pose": {},
            "velocity": {},
            "satellites": None,
            "depth": {},
            "mission": {},
            "attack": {},
            "supervisor": {},
            "ground_truth": {},
            "active_command": {},
        }
        self.attack_evidence = {
            "command_start_s": 0.0,
            "source": "none",
            "mode": "none",
            "severity": "none",
            "baseline_drift_m": None,
            "current_drift_m": None,
            "peak_drift_m": None,
            "drift_increase_m": None,
            "impact_observed": False,
            "stopped": False,
        }
        self.model_name = rospy.get_param("~ground_truth_model", "iris_0")

        self.override_pub = rospy.Publisher(
            "/laea/supervisor/override",
            SupervisorCommand,
            queue_size=5,
            latch=True,
        )
        # Live attack control. command_json is what attack_gazebo_bridge forwards
        # to the source-layer plugins; command is what experiment_manager labels.
        self.attack_cmd_pub = rospy.Publisher(
            "/laea/attack/command", AttackCommand, queue_size=1, latch=True
        )
        self.attack_json_pub = rospy.Publisher(
            "/laea/attack/command_json", String, queue_size=1, latch=True
        )
        rospy.Subscriber("/mavros/state", State, self._mavros_cb, queue_size=20)
        rospy.Subscriber(
            "/mavros/local_position/pose", PoseStamped, self._pose_cb, queue_size=20
        )
        rospy.Subscriber(
            "/mavros/local_position/velocity_local",
            TwistStamped,
            self._velocity_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            "/mavros/global_position/raw/satellites",
            UInt32,
            self._satellites_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            "/rtp/depth/image_raw", Image, self._depth_cb, queue_size=2
        )
        rospy.Subscriber(
            "/laea/twin/mission_state",
            MissionState,
            self._mission_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            "/laea/attack/status", AttackStatus, self._attack_cb, queue_size=20
        )
        rospy.Subscriber(
            "/laea/supervisor/command",
            SupervisorCommand,
            self._supervisor_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            "/gazebo/model_states", ModelStates, self._model_states_cb, queue_size=5
        )
        rospy.Subscriber(
            "/laea/attack/command", AttackCommand, self._active_command_cb, queue_size=10
        )

    def _touch(self, name):
        self.received[name] = time.time()

    def _mavros_cb(self, msg):
        with self.lock:
            self.state["mavros"] = {
                "connected": bool(msg.connected),
                "armed": bool(msg.armed),
                "guided": bool(msg.guided),
                "mode": msg.mode,
                "system_status": int(msg.system_status),
            }
            self._touch("mavros")

    def _pose_cb(self, msg):
        p = msg.pose.position
        with self.lock:
            self.state["pose"] = {"x": p.x, "y": p.y, "z": p.z}
            self._touch("pose")

    def _velocity_cb(self, msg):
        v = msg.twist.linear
        speed = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5
        with self.lock:
            self.state["velocity"] = {
                "x": v.x,
                "y": v.y,
                "z": v.z,
                "speed": speed,
            }
            self._touch("velocity")

    def _satellites_cb(self, msg):
        with self.lock:
            self.state["satellites"] = int(msg.data)
            self._touch("satellites")

    def _depth_cb(self, msg):
        with self.lock:
            self.state["depth"] = {
                "width": int(msg.width),
                "height": int(msg.height),
                "encoding": msg.encoding,
            }
            self._touch("depth")

    def _mission_cb(self, msg):
        with self.lock:
            self.state["mission"] = {
                "localization": level_name(msg.localization_level),
                "perception": level_name(msg.perception_level),
                "planner": level_name(msg.planner_level),
                "flight_safety": level_name(msg.flight_safety_level),
                "overall": level_name(msg.overall_level),
                "localization_score": msg.localization_score,
                "perception_score": msg.perception_score,
                "planner_score": msg.planner_score,
                "flight_safety_score": msg.flight_safety_score,
                "detector_name": msg.detector_name,
                "anomaly_score": msg.anomaly_score,
                "reason_bits": int(msg.reason_bits),
                "recommended_feedback": feedback_name(msg.recommended_feedback),
                "hard_safety_latched": bool(msg.hard_safety_latched),
                "summary": msg.summary,
            }
            self._touch("mission")

    def _attack_cb(self, msg):
        with self.lock:
            self.state["attack"] = {
                "run_id": msg.run_id,
                "source": msg.source,
                "mode": msg.mode,
                "severity": msg.severity,
                "armed": bool(msg.armed),
                "active": bool(msg.active),
                "actual_onset_s": msg.actual_onset.to_sec(),
                "elapsed_s": msg.elapsed.to_sec(),
                "detail": msg.detail,
            }
            self._touch("attack")

    def _supervisor_cb(self, msg):
        with self.lock:
            self.state["supervisor"] = {
                "level": feedback_name(msg.level),
                "speed_scale": msg.speed_scale,
                "hold_position": bool(msg.hold_position),
                "hard_latched": bool(msg.hard_latched),
                "reason_bits": int(msg.reason_bits),
                "reason": msg.reason,
            }
            self._touch("supervisor")

    def _model_states_cb(self, msg):
        try:
            idx = msg.name.index(self.model_name)
        except ValueError:
            return
        p = msg.pose[idx].position
        with self.lock:
            self.state["ground_truth"] = {"x": p.x, "y": p.y, "z": p.z}
            self._touch("ground_truth")

    def _active_command_cb(self, msg):
        with self.lock:
            command_start_s = msg.scheduled_start.to_sec()
            self.state["active_command"] = {
                "source": msg.source,
                "mode": msg.mode,
                "severity": msg.severity,
                "enabled": bool(msg.enabled),
                "scheduled_start_s": command_start_s,
                "ramp_s": msg.ramp.to_sec(),
                "duration_s": msg.duration.to_sec(),
                "recovery_s": msg.recovery.to_sec(),
                "vector": [
                    msg.vector_value.x,
                    msg.vector_value.y,
                    msg.vector_value.z,
                ],
                "scalar": msg.scalar_value,
                "seed": int(msg.seed),
            }
            if msg.enabled and msg.source != "none":
                if self.attack_evidence["command_start_s"] != command_start_s:
                    self.attack_evidence = {
                        "command_start_s": command_start_s,
                        "source": msg.source,
                        "mode": msg.mode,
                        "severity": msg.severity,
                        "vector": [
                            msg.vector_value.x,
                            msg.vector_value.y,
                            msg.vector_value.z,
                        ],
                        "scalar": msg.scalar_value,
                        "baseline_drift_m": None,
                        "current_drift_m": None,
                        "peak_drift_m": None,
                        "drift_increase_m": None,
                        "impact_observed": False,
                        "stopped": False,
                    }
            elif self.attack_evidence["command_start_s"] > 0.0:
                self.attack_evidence["stopped"] = True
            self._touch("active_command")

    def publish_override(self, level, reason):
        levels = {
            "NONE": SupervisorCommand.NONE,
            "ALERT": SupervisorCommand.ALERT,
            "SLOW_DOWN": SupervisorCommand.SLOW_DOWN,
            "HOVER": SupervisorCommand.HOVER,
        }
        if level not in levels:
            raise ValueError("Unsupported supervisor level.")

        msg = SupervisorCommand()
        msg.header.stamp = rospy.Time.now()
        msg.level = levels[level]
        msg.speed_scale = 0.5 if level == "SLOW_DOWN" else 0.0 if level == "HOVER" else 1.0
        msg.hold_position = level == "HOVER"
        msg.hard_latched = False
        msg.reason = reason or "dashboard_override"
        self.override_pub.publish(msg)

    def publish_attack(self, defn, enabled):
        defn = dict(defn or {})
        vector = list(defn.get("vector", [0.0, 0.0, 0.0])) + [0.0, 0.0, 0.0]
        vx, vy, vz = float(vector[0]), float(vector[1]), float(vector[2])
        source = str(defn.get("source", "none"))
        mode = str(defn.get("mode", "none"))
        severity = str(defn.get("severity", "none"))
        ramp_s = float(defn.get("ramp_s", 0.0))
        duration_s = float(defn.get("duration_s", 0.0))
        recovery_s = float(defn.get("recovery_s", 0.0))
        scalar = float(defn.get("scalar", 0.0))

        now = rospy.Time.now()
        start = now if enabled else rospy.Time(0)

        msg = AttackCommand()
        msg.header.stamp = now
        msg.run_id = "dashboard"
        msg.source = source
        msg.mode = mode
        msg.severity = severity
        msg.enabled = bool(enabled)
        msg.scheduled_start = start
        msg.ramp = rospy.Duration(max(ramp_s, 0.0))
        msg.duration = rospy.Duration(max(duration_s, 0.0))
        msg.recovery = rospy.Duration(max(recovery_s, 0.0))
        msg.vector_value.x = vx
        msg.vector_value.y = vy
        msg.vector_value.z = vz
        msg.scalar_value = scalar
        msg.seed = 0
        self.attack_cmd_pub.publish(msg)

        payload = {
            "run_id": "dashboard",
            "source": source,
            "mode": mode,
            "severity": severity,
            "enabled": bool(enabled),
            "scheduled_start": start.to_sec(),
            "ramp_s": ramp_s,
            "duration_s": duration_s,
            "recovery_s": recovery_s,
            "vector": [vx, vy, vz],
            "scalar": scalar,
            "seed": 0,
        }
        self.attack_json_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def snapshot(self):
        now = time.time()
        ros_now = rospy.Time.now().to_sec()
        with self.lock:
            result = json.loads(json.dumps(self.state))
            result["ages_s"] = {
                name: round(now - stamp, 3) for name, stamp in self.received.items()
            }
        pose = result.get("pose") or {}
        gt = result.get("ground_truth") or {}
        if {"x", "y"} <= set(pose) and {"x", "y"} <= set(gt):
            result["localization_drift_m"] = (
                (pose["x"] - gt["x"]) ** 2 + (pose["y"] - gt["y"]) ** 2
            ) ** 0.5
        else:
            result["localization_drift_m"] = None

        command = result.get("active_command") or {}
        command_start = float(command.get("scheduled_start_s") or 0.0)
        command_enabled = bool(command.get("enabled"))
        command_age = ros_now - command_start if command_start > 0.0 else -1.0
        if not command_enabled or command_start <= 0.0:
            command_phase = "inactive"
            command_effect_active = False
        elif command_age < 0.0:
            command_phase = "scheduled"
            command_effect_active = False
        else:
            duration = float(command.get("duration_s") or 0.0)
            recovery = float(command.get("recovery_s") or 0.0)
            ramp = float(command.get("ramp_s") or 0.0)
            command_effect_active = duration <= 0.0 or command_age < duration + recovery
            if not command_effect_active:
                command_phase = "complete"
            elif ramp > 0.0 and command_age < ramp:
                command_phase = "ramp"
            elif duration > 0.0 and command_age >= duration:
                command_phase = "recovery"
            else:
                command_phase = "active"
        command["effect_active"] = command_effect_active
        command["phase"] = command_phase
        command["elapsed_s"] = max(command_age, 0.0) if command_start > 0.0 else 0.0
        result["active_command"] = command

        drift = result["localization_drift_m"]
        with self.lock:
            evidence = self.attack_evidence
            if evidence["command_start_s"] > 0.0 and drift is not None:
                if evidence["baseline_drift_m"] is None:
                    evidence["baseline_drift_m"] = drift
                    evidence["peak_drift_m"] = drift
                evidence["current_drift_m"] = drift
                evidence["peak_drift_m"] = max(evidence["peak_drift_m"], drift)
                evidence["drift_increase_m"] = max(
                    evidence["peak_drift_m"] - evidence["baseline_drift_m"],
                    0.0,
                )
                # This is an evidence aid, not plugin ACK. A 0.5 m increase over
                # the pre-command baseline is large enough to be visible in a
                # presentation while preserving the raw values for inspection.
                evidence["impact_observed"] = evidence["drift_increase_m"] >= 0.5
            evidence["phase"] = command_phase
            evidence["effect_active"] = command_effect_active
            result["attack_evidence"] = json.loads(json.dumps(evidence))
        return result



def load_profiles():
    try:
        with open(PROFILE_CONFIG, "r") as source:
            profiles = dict(yaml.safe_load(source) or {}).get("profiles", {})
    except (OSError, yaml.YAMLError):
        profiles = {}
    return ["none"] + sorted(profiles.keys())


def load_profile_defs():
    try:
        with open(PROFILE_CONFIG, "r") as source:
            return dict(yaml.safe_load(source) or {}).get("profiles", {})
    except (OSError, yaml.YAMLError):
        return {}


def normalize_start_config(payload, profiles):
    payload = dict(payload or {})

    def clean_name(key, default):
        value = str(payload.get(key, default)).strip()
        if not NAME_RE.match(value):
            raise ValueError(f"Invalid {key}.")
        return value

    profile = clean_name("attack_profile", "none")
    if profile not in profiles:
        raise ValueError("Unknown attack profile.")
    if profile != "none":
        definition = load_profile_defs().get(profile, {})
        if str(definition.get("source", "none")) not in LIVE_ATTACK_SOURCES:
            raise ValueError(
                "This attack profile is not connected to a source-layer injector yet."
            )

    seed = int(payload.get("attack_seed", 42))
    if seed < 0 or seed > 4294967295:
        raise ValueError("attack_seed must fit uint32.")
    max_duration = float(payload.get("max_duration_s", 900.0))
    if max_duration < 30.0 or max_duration > 7200.0:
        raise ValueError("max_duration_s must be between 30 and 7200.")
    collection_mode = str(payload.get("collection_mode", "single")).lower()
    if collection_mode not in ("single", "batch"):
        raise ValueError("collection_mode must be single or batch.")
    total_rounds = int(payload.get("total_rounds", 10))
    if total_rounds < 1 or total_rounds > 1000:
        raise ValueError("total_rounds must be between 1 and 1000.")
    sleep_between_rounds_s = float(payload.get("sleep_between_rounds_s", 5.0))
    if sleep_between_rounds_s < 0.0 or sleep_between_rounds_s > 600.0:
        raise ValueError("sleep_between_rounds_s must be between 0 and 600.")
    increment_seed = bool(payload.get("increment_seed", True))
    if increment_seed and seed + total_rounds - 1 > 4294967295:
        raise ValueError("The final incremented attack seed would exceed uint32.")

    world_name = clean_name("world_name", "indoor_01")
    world_profile = normalized_world_profile(world_name)

    return {
        "runtime_profile": STABLE_RUNTIME_PROFILE,
        "collection_mode": collection_mode,
        "dataset_name": clean_name("dataset_name", "dashboard"),
        "scenario": clean_name("scenario", "normal"),
        "world_name": world_name,
        "world_profile": world_profile,
        "attack_profile": profile,
        "attack_seed": seed,
        "max_duration_s": max_duration,
        "detector_name": clean_name("detector_name", "rule_mad"),
        "supervisor_policy": clean_name("supervisor_policy", "none"),
        "total_rounds": total_rounds,
        "sleep_between_rounds_s": sleep_between_rounds_s,
        "increment_seed": increment_seed,
        "enable_rviz": bool(payload.get("enable_rviz", False)),
        "enable_ditto": bool(payload.get("enable_ditto", False)),
        "enable_rtp": bool(payload.get("enable_rtp", True)),
    }


def read_recent_runs(dataset_dir, limit=12):
    path = os.path.join(dataset_dir, "run_manifest.csv")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", newline="") as source:
            rows = list(csv.DictReader(source))
    except (OSError, csv.Error):
        return []
    return rows[-max(1, min(int(limit), 100)) :][::-1]


def ros_master_online():
    try:
        rosgraph.Master("/laea_dashboard").getPid()
        return True
    except Exception:
        return False


# An anonymous ROS node name prevents a newly launched dashboard from shutting
# down another Flask process that is still exiting with the same node name.
rospy.init_node("laea_dashboard", anonymous=True, disable_signals=True)
monitor = RosMonitor()
experiment = ExperimentProcess()
profiles = load_profiles()
app = Flask(__name__, static_folder=None)


@app.get("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


@app.get("/assets/<path:name>")
def assets(name):
    return send_from_directory(str(WEB_DIR), name)


@app.get("/api/state")
def api_state():
    process = experiment.snapshot()
    online_nodes = ros_nodes_online()
    components = {
        key: {
            "node": node,
            "online": node in online_nodes,
        }
        for key, node in COMPONENT_NODES.items()
    }
    return jsonify(
        {
            "ros_master_online": ros_master_online(),
            "process": process,
            "telemetry": monitor.snapshot(),
            "recent_runs": read_recent_runs(process["dataset_dir"]),
            "profiles": profiles,
            "profile_catalog": profile_catalog(),
            "world_catalog": world_catalog(),
            "components": components,
            "capabilities": runtime_capabilities(process, components),
            "server_time": time.time(),
        }
    )


@app.get("/api/logs")
def api_logs():
    process = experiment.snapshot()
    return jsonify({"text": tail_text(process["log_path"], request.args.get("lines", 160))})


@app.post("/api/experiment/start")
def api_experiment_start():
    try:
        config = normalize_start_config(request.get_json(silent=True), profiles)
        return jsonify({"ok": True, "process": experiment.start(config)})
    except (ValueError, RuntimeError, OSError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/experiment/stop")
def api_experiment_stop():
    try:
        return jsonify({"ok": True, "process": experiment.stop()})
    except (OSError, subprocess.SubprocessError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/supervisor")
def api_supervisor():
    payload = request.get_json(silent=True) or {}
    try:
        level = str(payload.get("level", "")).upper()
        monitor.publish_override(level, str(payload.get("reason", "dashboard_override")))
        return jsonify({"ok": True, "level": level})
    except (ValueError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/attack/trigger")
def api_attack_trigger():
    payload = request.get_json(silent=True) or {}
    profile = str(payload.get("profile", "")).strip()
    defs = load_profile_defs()
    if profile not in defs:
        return jsonify({"ok": False, "error": "Unknown attack profile."}), 400
    if str(defs[profile].get("source", "none")) not in LIVE_ATTACK_SOURCES:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "This profile has no connected Gazebo injector yet.",
                }
            ),
            400,
        )
    try:
        monitor.publish_attack(defs[profile], enabled=True)
        return jsonify({"ok": True, "profile": profile})
    except (ValueError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/attack/stop")
def api_attack_stop():
    try:
        monitor.publish_attack({}, enabled=False)
        return jsonify({"ok": True})
    except (ValueError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


if __name__ == "__main__":
    host = os.environ.get("LAEA_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("LAEA_DASHBOARD_PORT", "12346"))
    app.run(host=host, port=port, threaded=True, use_reloader=False)
