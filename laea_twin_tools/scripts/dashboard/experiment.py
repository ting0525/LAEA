"""The dashboard's experiment subprocess lifecycle and stop/cleanup."""

import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import rospy

from .common import *  # noqa: F401,F403
from .procutil import *  # noqa: F401,F403
from .roscleanup import *  # noqa: F401,F403


class ExperimentProcess:
    def __init__(self, monitor=None):
        self._monitor = monitor
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
        table = process_table() if table is None else table
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

    def _refresh_locked(self, table=None):
        table = process_table() if table is None else table
        if self.process is not None:
            code = self.process.poll()
            if code is not None and self.exit_code is None:
                self.exit_code = code
                self.ended_at = time.time()
        if not self._active_roots_locked(table):
            self.root_pid = None
            self._clear_control_state()
        return table

    def start(self, config):
        with self.lock:
            table = self._refresh_locked()
            if self._active_roots_locked(table):
                raise RuntimeError("An experiment is already running.")

            config = dict(config)
            attack_capable_model = config["attack_profile"] != "none"
            px4_sdf = (
                ATTACK_CAPABLE_PX4_SDF
                if attack_capable_model
                else BASELINE_PX4_SDF
            )
            config["px4_sdf"] = px4_sdf
            config["attack_capable_model"] = attack_capable_model

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
                    "EXP_MIN_FINISH_TIME_S": str(
                        config["world_profile"]["planner"]["min_finish_time_s"]
                    ),
                    "EXP_MIN_FINISH_DISTANCE_M": str(
                        config["world_profile"]["planner"][
                            "min_finish_distance_m"
                        ]
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
                    # The supervisory framework (mission_state / supervisor /
                    # feedback) runs for every mission, but the source-layer
                    # attack command plane (scheduler + Gazebo bridge) is wired
                    # only for attack runs, so baseline collection never carries
                    # injection infrastructure.
                    "ENABLE_ATTACK_PLANE": "true" if attack_capable_model else "false",
                    # Keep normal training data on PX4's stock GPS plugin.
                    # Load the attack-capable model only for an attack profile,
                    # so baseline and attack runs do not silently share a
                    # different sensor implementation.
                    "LAEA_PX4_SDF": px4_sdf,
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

            if not rospy.is_shutdown() and self._monitor is not None:
                try:
                    self._monitor.publish_override("NONE", "dashboard_start_reset")
                    # Clear any latched attack command from a prior session so a
                    # freshly started bridge cannot replay a stale enabled=True.
                    self._monitor.publish_attack({}, enabled=False)
                except (ValueError, rospy.ROSException) as exc:
                    rospy.logwarn("Dashboard start reset failed: %s", exc)
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
            process = self.process
            table = process_table()
            self._refresh_locked(table)
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
        table = process_table()
        self._refresh_locked(table)
        roots = self._active_roots_locked(table)
        running = bool(roots)
        if running:
            residual_pids = set()
            residual_ros_nodes = []
        else:
            residual_pids = live_pids(experiment_component_pids(table))
            residual_ros_nodes = registered_experiment_ros_nodes()
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
