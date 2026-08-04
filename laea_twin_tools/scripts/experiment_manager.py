#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import os
import math
import signal
import subprocess
import threading
import time
import rospy

from geometry_msgs.msg import PoseStamped
from gazebo_msgs.msg import ModelStates
from rosgraph_msgs.msg import Log as RosLog
from laea_twin_tools.msg import AttackCommand, AttackStatus, SupervisorCommand


MANIFEST_FIELDS = [
    "manifest_version",
    "run_id",
    "scenario",
    "transport_mode",
    "world_name",
    "started_at_s",
    "ended_at_s",
    "duration_s",
    "outcome",
    "log_retained",
    "log_deleted",
    "delete_reason",
    "attack_source",
    "attack_mode",
    "attack_severity",
    "attack_seed",
    "attack_scheduled_onset_s",
    "attack_actual_onset_s",
    "hover_reason_bits",
    "hover_hard_latched",
    "hover_reason",
]


def annotate_csv_outcome(path, outcome):
    """Rewrite a completed run with a stable outcome value on each sample."""
    temp_path = path + ".outcome.tmp"
    with open(path, "r", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        if "mission_outcome" not in fieldnames:
            fieldnames.append("mission_outcome")
        with open(temp_path, "w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                row["mission_outcome"] = outcome
                writer.writerow(row)
    os.replace(temp_path, path)


def append_manifest_row(path, row):
    """Append one low-volume run summary, creating a stable header if needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    needs_header = not os.path.isfile(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=MANIFEST_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
        target.flush()
        os.fsync(target.fileno())


def _finite_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _numeric_summary(values):
    clean = [value for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return {}
    ordered = sorted(clean)
    p95_index = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
    return {
        "count": len(clean),
        "min": min(clean),
        "mean": sum(clean) / len(clean),
        "p95": ordered[p95_index],
        "max": max(clean),
        "last": clean[-1],
    }


def summarize_kpi_csv_for_debug(path, tail_window_s=5.0):
    """Build a small diagnostic summary before failed-run CSV deletion."""
    if not path or not os.path.isfile(path):
        return {"available": False, "reason": "missing_csv", "path": path}

    rows = []
    with open(path, "r", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            rows.append(row)

    if not rows:
        return {"available": False, "reason": "empty_csv", "path": path}

    times = [_finite_float(row.get("t")) for row in rows]
    valid_times = [value for value in times if value is not None]
    t_first = valid_times[0] if valid_times else None
    t_last = valid_times[-1] if valid_times else None
    tail_start = (
        t_last - float(tail_window_s)
        if t_last is not None and tail_window_s > 0.0
        else None
    )
    tail_rows = [
        row
        for row in rows
        if tail_start is None
        or (
            _finite_float(row.get("t")) is not None
            and _finite_float(row.get("t")) >= tail_start
        )
    ]

    def values(source_rows, field):
        return [_finite_float(row.get(field)) for row in source_rows]

    def speed_values(source_rows):
        speeds = []
        for row in source_rows:
            vx = _finite_float(row.get("vel_x"))
            vy = _finite_float(row.get("vel_y"))
            vz = _finite_float(row.get("vel_z"))
            if vx is not None and vy is not None and vz is not None:
                speeds.append(math.sqrt(vx * vx + vy * vy + vz * vz))
        return speeds

    def stale_ratio(source_rows):
        parsed = []
        for row in source_rows:
            value = _finite_float(row.get("rtp_depth_stale"))
            if value is not None:
                parsed.append(1 if value >= 0.5 else 0)
        return sum(parsed) / len(parsed) if parsed else None

    def mission_outcome_counts(source_rows):
        counts = {}
        for row in source_rows:
            value = row.get("mission_outcome", "")
            counts[value] = counts.get(value, 0) + 1
        return counts

    def latest_sample(row):
        vx = _finite_float(row.get("vel_x"))
        vy = _finite_float(row.get("vel_y"))
        vz = _finite_float(row.get("vel_z"))
        speed = None
        if vx is not None and vy is not None and vz is not None:
            speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        return {
            "t": _finite_float(row.get("t")),
            "e_pos": _finite_float(row.get("e_pos")),
            "gt": {
                "x": _finite_float(row.get("px_gt")),
                "y": _finite_float(row.get("py_gt")),
                "z": _finite_float(row.get("pz_gt")),
            },
            "est": {
                "x": _finite_float(row.get("pos_x")),
                "y": _finite_float(row.get("pos_y")),
                "z": _finite_float(row.get("pos_z")),
            },
            "speed_mps": speed,
            "gps_sat": _finite_float(row.get("gps_sat")),
            "gps_fix": _finite_float(row.get("gps_fix")),
            "gps_position_covariance": _finite_float(
                row.get("gps_position_covariance")
            ),
            "depth_age_ms": _finite_float(row.get("depth_age_ms")),
            "depth_valid_ratio": _finite_float(row.get("depth_valid_ratio")),
            "rtp_depth_stale": _finite_float(row.get("rtp_depth_stale")),
            "rtp_depth_repeat_score": _finite_float(
                row.get("rtp_depth_repeat_score")
            ),
            "mission_outcome": row.get("mission_outcome", ""),
        }

    def field_block(source_rows):
        return {
            "e_pos": _numeric_summary(values(source_rows, "e_pos")),
            "speed_mps": _numeric_summary(speed_values(source_rows)),
            "gps_sat": _numeric_summary(values(source_rows, "gps_sat")),
            "gps_position_covariance": _numeric_summary(
                values(source_rows, "gps_position_covariance")
            ),
            "odom_pose_covariance_summary": _numeric_summary(
                values(source_rows, "odom_pose_covariance_summary")
            ),
            "odom_twist_covariance_summary": _numeric_summary(
                values(source_rows, "odom_twist_covariance_summary")
            ),
            "depth_age_ms": _numeric_summary(values(source_rows, "depth_age_ms")),
            "depth_valid_ratio": _numeric_summary(
                values(source_rows, "depth_valid_ratio")
            ),
            "depth_mean_m": _numeric_summary(values(source_rows, "depth_mean_m")),
            "depth_near_ratio_1m": _numeric_summary(
                values(source_rows, "depth_near_ratio_1m")
            ),
            "rtp_depth_repeat_score": _numeric_summary(
                values(source_rows, "rtp_depth_repeat_score")
            ),
            "depth_stale_ratio": stale_ratio(source_rows),
        }

    return {
        "available": True,
        "path": path,
        "row_count": len(rows),
        "tail_row_count": len(tail_rows),
        "tail_window_s": tail_window_s,
        "t_first": t_first,
        "t_last": t_last,
        "log_duration_s": (
            max(t_last - t_first, 0.0)
            if t_first is not None and t_last is not None
            else None
        ),
        "mission_outcome_counts": mission_outcome_counts(rows),
        "all": field_block(rows),
        "tail": field_block(tail_rows),
        "last_sample": latest_sample(rows[-1]),
    }


class ExperimentManager:
    @staticmethod
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def __init__(self):
        rospy.init_node("experiment_manager", anonymous=False)

        # ----------------------------
        # Orchestration params
        # ----------------------------
        self.num_runs = int(rospy.get_param("~num_runs", 1))
        self.sleep_between_runs_s = float(rospy.get_param("~sleep_between_runs_s", 2.0))

        # Trigger
        self.start_topic = rospy.get_param("~start_topic", "/traj_start_trigger")
        self.start_frame_id = rospy.get_param("~start_frame_id", "map")
        self.start_pub = rospy.Publisher(self.start_topic, PoseStamped, queue_size=1, latch=True)

        # ----------------------------
        # Planner finish candidate. It is accepted only after duration and
        # ground-truth travel-distance validation.
        # ----------------------------
        self._run_start_time = None
        self._finish_seen = False
        self._finish_time = None
        self._early_finish_first_time = None
        self._early_finish_last_time = None

        self.rosout_topic = rospy.get_param("~rosout_topic", "/rosout_agg")
        self.finish_token = rospy.get_param("~finish_token", "finish exploration.")
        self.early_finish_token = rospy.get_param(
            "~early_finish_token", "Reject early no-frontier finish"
        )
        self.early_finish_hold_s = float(
            rospy.get_param("~early_finish_hold_s", 5.0)
        )
        self.early_finish_max_gap_s = float(
            rospy.get_param("~early_finish_max_gap_s", 1.0)
        )
        
        self.finish_node_name = rospy.get_param("~finish_node_name", "")  # "" = 不限制
        rospy.Subscriber(self.rosout_topic, RosLog, self._rosout_cb, queue_size=200)

        # ----------------------------
        # Fail detection (GT vs EST)
        # ----------------------------
        self.model_name = rospy.get_param("~model_name", "iris_0")
        self.fail_error_m = float(rospy.get_param("~fail_error_m", 10.0))
        self.fail_hold_s = float(rospy.get_param("~fail_hold_s", 1.0))

        # Timeout: 沒 finish 一律視為非成功（刪檔）
        self.max_duration_s = float(rospy.get_param("~max_duration_s", 900.0))
        self.success_min_duration_s = float(
            rospy.get_param("~success_min_duration_s", 300.0)
        )
        self.success_min_distance_m = float(
            rospy.get_param("~success_min_distance_m", 200.0)
        )
        self.distance_sample_period_s = float(
            rospy.get_param("~distance_sample_period_s", 0.05)
        )

        # ----------------------------
        # Logger control
        # ----------------------------
        self.output_dir = rospy.get_param(
            "~output_dir",
            rospy.get_param(
                "/slam_kpi_logger/output_dir",
                "/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs"
            )
        )
        self.logger_script = rospy.get_param(
            "~logger_script",
            "/home/tim/laea/src/LAEA/laea_twin_tools/scripts/slam_kpi_logger.py"
        )
        # Optional fallback for legacy workflow
        self.use_roslaunch_logger = self._as_bool(
            rospy.get_param("~use_roslaunch_logger", False)
        )
        self.logger_launch = rospy.get_param(
            "~logger_launch",
            "/home/tim/laea/src/LAEA/laea_twin_tools/launch/slam_kpi_logger.launch"
        )
        self.scenario = str(rospy.get_param("~scenario", "normal"))
        self.transport_mode = str(rospy.get_param("~transport_mode", "unspecified"))
        self.world_name = str(rospy.get_param("~world_name", "unknown"))
        self.depth_topic = str(rospy.get_param("~depth_topic", "/rtp/depth/image_raw"))
        self.depth_stale_threshold_s = float(rospy.get_param("~depth_stale_threshold_s", 0.25))

        # Dataset governance
        self.delete_on_non_success = self._as_bool(rospy.get_param("~delete_on_non_success", True))
        self.manifest_path = str(
            rospy.get_param(
                "~manifest_path", os.path.join(self.output_dir, "run_manifest.csv")
            )
        )
        self.debug_on_non_success = self._as_bool(
            rospy.get_param("~debug_on_non_success", True)
        )
        self.debug_dir = str(
            rospy.get_param("~debug_dir", os.path.join(self.output_dir, "debug"))
        )
        self.debug_outcomes = set(
            item.strip()
            for item in str(rospy.get_param("~debug_outcomes", "")).split(",")
            if item.strip()
        )
        self.debug_tail_window_s = float(
            rospy.get_param("~debug_tail_window_s", 5.0)
        )

        # Mission-aware terminal handling. A Hover published before the mission
        # trigger is ignored so a stale latched command cannot terminate a run.
        self.terminate_on_hover = self._as_bool(
            rospy.get_param("~terminate_on_hover", True)
        )
        self.supervisor_command_topic = str(
            rospy.get_param(
                "~supervisor_command_topic", "/laea/supervisor/command"
            )
        )
        self.attack_command_topic = str(
            rospy.get_param("~attack_command_topic", "/laea/attack/command")
        )
        self.attack_status_topic = str(
            rospy.get_param("~attack_status_topic", "/laea/attack/status")
        )

        # ----------------------------
        # Persistent Run ID (解決覆蓋的關鍵)
        # ----------------------------
        # 序號檔：跨重啟唯一遞增，確保永不覆蓋
        self.run_seq_file = rospy.get_param("~run_seq_file", os.path.join(self.output_dir, "run_seq.txt"))

        # ----------------------------
        # Data inputs
        # ----------------------------
        self.gt_xyz = None
        self.est_xyz = None
        self.gt_time = None
        self.est_time = None
        self._travel_distance_m = 0.0
        self._last_gt_for_distance = None
        self._last_gt_distance_time = None

        # Callback-visible state must exist before subscribers are registered,
        # because latched ROS messages may invoke callbacks immediately.
        self._state_lock = threading.Lock()
        self._mission_trigger_time = None
        self._fail_start_time = None
        self._hover_seen = False
        self._hover_time = None
        self._hover_reason_bits = 0
        self._hover_hard_latched = False
        self._hover_reason = ""
        self._attack_info = {
            "source": "",
            "mode": "",
            "severity": "",
            "seed": "",
            "scheduled_start_s": 0.0,
            "actual_onset_s": 0.0,
        }

        rospy.Subscriber("/gazebo/model_states", ModelStates, self._gt_cb, queue_size=10)
        rospy.Subscriber("/mavros/local_position/pose", PoseStamped, self._est_cb, queue_size=50)
        rospy.Subscriber(
            self.supervisor_command_topic,
            SupervisorCommand,
            self._supervisor_command_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            self.attack_command_topic,
            AttackCommand,
            self._attack_command_cb,
            queue_size=10,
        )
        rospy.Subscriber(
            self.attack_status_topic,
            AttackStatus,
            self._attack_status_cb,
            queue_size=20,
        )

        self._logger_proc = None
        self._cached_log_path = ""

    # ----------------------------
    # Callbacks
    # ----------------------------
    def _rosout_cb(self, msg: RosLog):
        if self._run_start_time is None:
            return
        if msg.header.stamp < self._run_start_time:
            return
        if self.finish_node_name and (msg.name != self.finish_node_name):
            return
        if self.finish_token in (msg.msg or ""):
            self._finish_seen = True
            self._finish_time = msg.header.stamp
        if self.early_finish_token in (msg.msg or ""):
            event_time = (
                msg.header.stamp
                if msg.header.stamp.to_sec() > 0.0
                else rospy.Time.now()
            )
            if (
                self._early_finish_last_time is None
                or (event_time - self._early_finish_last_time).to_sec()
                > self.early_finish_max_gap_s
            ):
                self._early_finish_first_time = event_time
            self._early_finish_last_time = event_time

    def _gt_cb(self, msg: ModelStates):
        try:
            idx = msg.name.index(self.model_name)
        except ValueError:
            return
        p = msg.pose[idx].position
        current = (p.x, p.y, p.z)
        current_time = rospy.Time.now()
        with self._state_lock:
            self.gt_xyz = current
            self.gt_time = current_time
            if self._mission_trigger_time is not None:
                sample_due = (
                    self._last_gt_distance_time is None
                    or (current_time - self._last_gt_distance_time).to_sec()
                    >= self.distance_sample_period_s
                )
                if sample_due and self._last_gt_for_distance is not None:
                    dx = current[0] - self._last_gt_for_distance[0]
                    dy = current[1] - self._last_gt_for_distance[1]
                    dz = current[2] - self._last_gt_for_distance[2]
                    segment = math.sqrt(dx * dx + dy * dy + dz * dz)
                    # Ignore model reset/teleport discontinuities.
                    if segment <= 2.0:
                        self._travel_distance_m += segment
                if sample_due:
                    self._last_gt_for_distance = current
                    self._last_gt_distance_time = current_time

    def _est_cb(self, msg: PoseStamped):
        p = msg.pose.position
        with self._state_lock:
            self.est_xyz = (p.x, p.y, p.z)
            self.est_time = rospy.Time.now()

    def _supervisor_command_cb(self, msg: SupervisorCommand):
        if not self.terminate_on_hover or msg.level != SupervisorCommand.HOVER:
            return

        received_at = rospy.Time.now()
        event_time = (
            msg.header.stamp
            if msg.header.stamp and msg.header.stamp.to_sec() > 0.0
            else received_at
        )
        with self._state_lock:
            if self._mission_trigger_time is None:
                return
            if event_time < self._mission_trigger_time:
                return
            if self._hover_seen:
                return
            self._hover_seen = True
            self._hover_time = event_time
            self._hover_reason_bits = int(msg.reason_bits)
            self._hover_hard_latched = bool(msg.hard_latched)
            self._hover_reason = str(msg.reason)

    def _attack_command_cb(self, msg: AttackCommand):
        with self._state_lock:
            self._attack_info.update(
                {
                    "source": str(msg.source),
                    "mode": str(msg.mode),
                    "severity": str(msg.severity),
                    "seed": int(msg.seed),
                    "scheduled_start_s": msg.scheduled_start.to_sec(),
                }
            )

    def _attack_status_cb(self, msg: AttackStatus):
        with self._state_lock:
            self._attack_info.update(
                {
                    "source": str(msg.source),
                    "mode": str(msg.mode),
                    "severity": str(msg.severity),
                }
            )
            onset_s = msg.actual_onset.to_sec()
            if onset_s > 0.0:
                self._attack_info["actual_onset_s"] = onset_s

    # ----------------------------
    # Helpers
    # ----------------------------
    def _compute_e_pos(self):
        with self._state_lock:
            gt_xyz = self.gt_xyz
            est_xyz = self.est_xyz
        if gt_xyz is None or est_xyz is None:
            return None
        dx = gt_xyz[0] - est_xyz[0]
        dy = gt_xyz[1] - est_xyz[1]
        dz = gt_xyz[2] - est_xyz[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @staticmethod
    def _stamp_to_float(stamp):
        return stamp.to_sec() if stamp is not None else None

    def _run_debug_snapshot(self, outcome, ended_at):
        now = rospy.Time.now()
        with self._state_lock:
            gt_xyz = self.gt_xyz
            est_xyz = self.est_xyz
            gt_time = self.gt_time
            est_time = self.est_time
            trigger_time = self._mission_trigger_time
            fail_start_time = self._fail_start_time
            hover_seen = self._hover_seen
            hover_time = self._hover_time
            hover_reason_bits = self._hover_reason_bits
            hover_hard_latched = self._hover_hard_latched
            hover_reason = self._hover_reason
            travel_distance_m = self._travel_distance_m
            attack_info = dict(self._attack_info)

        e_pos = None
        if gt_xyz is not None and est_xyz is not None:
            dx = gt_xyz[0] - est_xyz[0]
            dy = gt_xyz[1] - est_xyz[1]
            dz = gt_xyz[2] - est_xyz[2]
            e_pos = math.sqrt(dx * dx + dy * dy + dz * dz)

        started_at = trigger_time or self._run_start_time
        return {
            "outcome": outcome,
            "created_wall_time_s": time.time(),
            "ros_now_s": now.to_sec(),
            "run_start_s": self._stamp_to_float(self._run_start_time),
            "mission_trigger_s": self._stamp_to_float(trigger_time),
            "ended_at_s": self._stamp_to_float(ended_at),
            "duration_s": (
                max((ended_at - started_at).to_sec(), 0.0)
                if started_at is not None and ended_at is not None
                else None
            ),
            "thresholds": {
                "fail_error_m": self.fail_error_m,
                "fail_hold_s": self.fail_hold_s,
                "success_min_duration_s": self.success_min_duration_s,
                "success_min_distance_m": self.success_min_distance_m,
            },
            "localization": {
                "e_pos_m": e_pos,
                "gt_xyz": gt_xyz,
                "est_xyz": est_xyz,
                "gt_time_s": self._stamp_to_float(gt_time),
                "est_time_s": self._stamp_to_float(est_time),
                "gt_age_s": (now - gt_time).to_sec() if gt_time is not None else None,
                "est_age_s": (
                    (now - est_time).to_sec() if est_time is not None else None
                ),
                "fail_started_s": self._stamp_to_float(fail_start_time),
                "fail_held_s": (
                    max((now - fail_start_time).to_sec(), 0.0)
                    if fail_start_time is not None
                    else None
                ),
            },
            "mission": {
                "travel_distance_m": travel_distance_m,
                "finish_seen": self._finish_seen,
                "finish_time_s": self._stamp_to_float(self._finish_time),
                "early_finish_first_s": self._stamp_to_float(
                    self._early_finish_first_time
                ),
                "early_finish_last_s": self._stamp_to_float(
                    self._early_finish_last_time
                ),
            },
            "hover": {
                "seen": hover_seen,
                "time_s": self._stamp_to_float(hover_time),
                "reason_bits": hover_reason_bits,
                "hard_latched": hover_hard_latched,
                "reason": hover_reason,
            },
            "attack": attack_info,
        }

    def _debug_diagnosis(self, snapshot, kpi_summary):
        diagnosis = []
        outcome = snapshot.get("outcome", "")
        localization = snapshot.get("localization", {})
        mission = snapshot.get("mission", {})
        thresholds = snapshot.get("thresholds", {})

        e_pos = localization.get("e_pos_m")
        fail_error_m = thresholds.get("fail_error_m")
        if outcome == "FAIL_SLAM" and e_pos is not None and fail_error_m is not None:
            diagnosis.append(
                "localization_error_exceeded: e_pos %.3fm > threshold %.3fm"
                % (e_pos, fail_error_m)
            )

        fail_held_s = localization.get("fail_held_s")
        fail_hold_s = thresholds.get("fail_hold_s")
        if fail_held_s is not None and fail_hold_s is not None:
            diagnosis.append(
                "localization_error_hold: held %.3fs / required %.3fs"
                % (fail_held_s, fail_hold_s)
            )

        for key in ("gt_age_s", "est_age_s"):
            value = localization.get(key)
            if value is not None and value > 1.0:
                diagnosis.append("%s_high: %.3fs" % (key, value))

        if outcome == "TIMEOUT_NO_FINISH":
            diagnosis.append(
                "timeout_without_finish: travel_distance %.3fm, finish_seen=%s"
                % (
                    mission.get("travel_distance_m") or 0.0,
                    mission.get("finish_seen"),
                )
            )

        if kpi_summary.get("available"):
            tail = kpi_summary.get("tail", {})
            depth_stale_ratio = tail.get("depth_stale_ratio")
            if depth_stale_ratio is not None and depth_stale_ratio > 0.5:
                diagnosis.append(
                    "depth_stream_stale_tail: %.1f%% stale"
                    % (depth_stale_ratio * 100.0)
                )

            tail_e_pos = tail.get("e_pos", {})
            if tail_e_pos.get("max") is not None and fail_error_m is not None:
                if tail_e_pos["max"] > fail_error_m:
                    diagnosis.append(
                        "tail_e_pos_max_high: %.3fm" % tail_e_pos["max"]
                    )
        else:
            diagnosis.append("kpi_csv_unavailable: %s" % kpi_summary.get("reason", ""))

        if not diagnosis:
            diagnosis.append("no_single_clear_cause_in_summary")
        return diagnosis

    def _wait_ready(self, timeout_s=60.0):
        """最小 readiness gate：確保 GT/EST 都有資料"""
        t0 = rospy.Time.now()
        rate = rospy.Rate(10)
        while not rospy.is_shutdown():
            if self.gt_xyz is not None and self.est_xyz is not None:
                return True
            if (rospy.Time.now() - t0).to_sec() > timeout_s:
                return False
            rate.sleep()
        return False

    def _publish_start_trigger(self):
        msg = PoseStamped()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = self.start_frame_id
        # 位置內容依你 waypoint_generator 行為；大多數情況 frame_id 正確即足夠
        msg.pose.position.x = 0.0
        msg.pose.position.y = 0.0
        msg.pose.position.z = 0.0
        msg.pose.orientation.w = 1.0
        with self._state_lock:
            self._mission_trigger_time = msg.header.stamp
            self._travel_distance_m = 0.0
            self._last_gt_for_distance = self.gt_xyz
            self._last_gt_distance_time = msg.header.stamp
        self.start_pub.publish(msg)

    def _next_global_run_id(self) -> str:
        """跨重啟的全域 run 序號：避免永遠 run_001 覆蓋"""
        os.makedirs(self.output_dir, exist_ok=True)

        n = 0
        if os.path.isfile(self.run_seq_file):
            try:
                with open(self.run_seq_file, "r") as f:
                    n = int((f.read() or "0").strip())
            except Exception:
                n = 0

        n += 1

        # 原子更新：避免寫到一半中斷造成 seq 壞掉
        tmp_path = self.run_seq_file + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(str(n))
        os.replace(tmp_path, self.run_seq_file)

        return f"run_{n:03d}"

    def _start_logger(self, run_id: str):
        """
        每個 run 啟動一次 logger，並把 run_id 帶進去
        讓 logger 輸出：kpi_log_<run_id>.csv
        """
        if self._logger_proc is not None and self._logger_proc.poll() is None:
            rospy.logwarn("Logger already running, terminating previous instance.")
            self._stop_logger()

        # Set params explicitly so direct python launch behaves like launch file.
        self._cached_log_path = os.path.join(self.output_dir, f"kpi_log_{run_id}.csv")
        rospy.set_param("/slam_kpi_logger/output_dir", self.output_dir)
        rospy.set_param("/slam_kpi_logger/output_name", f"kpi_log_{run_id}")
        rospy.set_param("/slam_kpi_logger/run_id", run_id)
        rospy.set_param("/slam_kpi_logger/scenario", self.scenario)
        rospy.set_param("/slam_kpi_logger/transport_mode", self.transport_mode)
        rospy.set_param("/slam_kpi_logger/world_name", self.world_name)
        rospy.set_param("/slam_kpi_logger/depth_topic", self.depth_topic)
        rospy.set_param("/slam_kpi_logger/depth_stale_threshold_s", self.depth_stale_threshold_s)

        if self.use_roslaunch_logger:
            cmd = ["roslaunch", self.logger_launch]
            rospy.loginfo(f"[RUN {run_id}] start logger (roslaunch): {' '.join(cmd)}")
        else:
            cmd = ["python3", self.logger_script]
            rospy.loginfo(f"[RUN {run_id}] start logger (python): {' '.join(cmd)}")

        self._logger_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )

        # 給 logger 時間 set /laea_twin/current_log_path
        rospy.sleep(1.0)

        # 可選：快速稽核 current_log_path
        try:
            path = rospy.get_param("/laea_twin/current_log_path", "")
            if not path:
                rospy.logwarn(f"[RUN {run_id}] current_log_path is empty after logger start.")
            else:
                rospy.loginfo(f"[RUN {run_id}] current_log_path={path}")
        except Exception:
            rospy.logwarn(f"[RUN {run_id}] unable to read /laea_twin/current_log_path after logger start.")

    def _stop_logger(self):
        if self._logger_proc is None:
            return
        if self._logger_proc.poll() is not None:
            self._logger_proc = None
            return
        try:
            os.killpg(os.getpgid(self._logger_proc.pid), signal.SIGINT)
        except Exception:
            pass
        try:
            self._logger_proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._logger_proc.pid), signal.SIGKILL)
            except Exception:
                pass
        self._logger_proc = None

    def _delete_current_log(self, reason: str):
        if not self.delete_on_non_success:
            return False

        path = self._current_log_path()
        if not path:
            rospy.logwarn(f"[DELETE] ({reason}) current_log_path param not set; skip delete.")
            return False

        if os.path.isfile(path):
            try:
                os.remove(path)
                rospy.logwarn(f"[DELETE] ({reason}) removed log: {path}")
                return True
            except Exception as e:
                rospy.logerr(f"[DELETE] ({reason}) failed to remove {path}: {e}")
        else:
            rospy.logwarn(f"[DELETE] ({reason}) file not found: {path}")
        return False

    def _current_log_path(self):
        if self._cached_log_path:
            return self._cached_log_path
        try:
            return rospy.get_param("/laea_twin/current_log_path", "")
        except Exception:
            return ""

    def _annotate_current_log(self, outcome):
        path = self._current_log_path()
        if not path or not os.path.isfile(path):
            rospy.logwarn(f"[RUN] cannot annotate outcome={outcome}; log file not found: {path}")
            return
        try:
            annotate_csv_outcome(path, outcome)
            rospy.loginfo(f"[RUN] annotated mission_outcome={outcome}: {path}")
        except Exception as error:
            rospy.logerr(f"[RUN] failed to annotate mission_outcome for {path}: {error}")

    def _write_failure_debug(self, run_id, outcome, ended_at):
        if not self.debug_on_non_success or outcome == "SUCCESS_FINISH":
            return ""
        if self.debug_outcomes and outcome not in self.debug_outcomes:
            return ""

        os.makedirs(self.debug_dir, exist_ok=True)
        log_path = self._current_log_path()
        snapshot = self._run_debug_snapshot(outcome, ended_at)
        kpi_summary = summarize_kpi_csv_for_debug(
            log_path, tail_window_s=self.debug_tail_window_s
        )
        diagnosis = self._debug_diagnosis(snapshot, kpi_summary)
        payload = {
            "debug_version": 1,
            "run_id": run_id,
            "scenario": self.scenario,
            "transport_mode": self.transport_mode,
            "world_name": self.world_name,
            "log_path": log_path,
            "log_exists_before_delete": bool(log_path and os.path.isfile(log_path)),
            "snapshot": snapshot,
            "kpi_csv_summary": kpi_summary,
            "diagnosis": diagnosis,
        }

        json_path = os.path.join(self.debug_dir, f"{run_id}_{outcome}.json")
        temp_path = json_path + ".tmp"
        with open(temp_path, "w") as target:
            json.dump(payload, target, indent=2, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp_path, json_path)

        latest_path = os.path.join(self.debug_dir, "latest_failure_debug.json")
        latest_temp = latest_path + ".tmp"
        with open(latest_temp, "w") as target:
            json.dump(payload, target, indent=2, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(latest_temp, latest_path)

        row_count = kpi_summary.get("row_count") if kpi_summary.get("available") else 0
        e_pos = snapshot.get("localization", {}).get("e_pos_m")
        rospy.logwarn(
            "[RUN %s] debug summary outcome=%s rows=%s e_pos=%s path=%s cause=%s",
            run_id,
            outcome,
            row_count,
            "%.3f" % e_pos if e_pos is not None else "NA",
            json_path,
            " | ".join(diagnosis[:3]),
        )
        return json_path

    # ----------------------------
    # Run lifecycle
    # ----------------------------
    def _reset_run_flags(self):
        self._run_start_time = rospy.Time.now()
        self._finish_seen = False
        self._finish_time = None
        self._early_finish_first_time = None
        self._early_finish_last_time = None
        self._fail_start_time = None
        with self._state_lock:
            self._mission_trigger_time = None
            self._travel_distance_m = 0.0
            self._last_gt_for_distance = None
            self._last_gt_distance_time = None
            self._hover_seen = False
            self._hover_time = None
            self._hover_reason_bits = 0
            self._hover_hard_latched = False
            self._hover_reason = ""
            self._attack_info["actual_onset_s"] = 0.0

    def _terminal_feedback_outcome(self):
        with self._state_lock:
            hover_seen = self._hover_seen
            hover_time = self._hover_time

        if not self._finish_seen and not hover_seen:
            return None
        if self._finish_seen and not hover_seen:
            return "SUCCESS_FINISH"
        if hover_seen and not self._finish_seen:
            return "SAFETY_HOVER"
        if hover_time is not None and self._finish_time is not None:
            return (
                "SAFETY_HOVER"
                if hover_time < self._finish_time
                else "SUCCESS_FINISH"
            )
        return "SAFETY_HOVER"

    def _completion_metrics(self, ended_at=None):
        ended_at = ended_at or rospy.Time.now()
        with self._state_lock:
            trigger_time = self._mission_trigger_time
            travel_distance_m = self._travel_distance_m
        started_at = trigger_time or self._run_start_time
        duration_s = (
            max((ended_at - started_at).to_sec(), 0.0)
            if started_at is not None
            else 0.0
        )
        return duration_s, travel_distance_m

    def _completion_is_valid(self):
        duration_s, travel_distance_m = self._completion_metrics(self._finish_time)
        valid = (
            duration_s >= self.success_min_duration_s
            and travel_distance_m >= self.success_min_distance_m
        )
        return valid, duration_s, travel_distance_m

    def _persistent_early_finish(self):
        first = self._early_finish_first_time
        last = self._early_finish_last_time
        if first is None or last is None:
            return False
        now = rospy.Time.now()
        return (
            (last - first).to_sec() >= self.early_finish_hold_s
            and (now - last).to_sec() <= self.early_finish_max_gap_s
        )

    @staticmethod
    def _relative_time_s(event_time_s, start_time_s):
        if event_time_s <= 0.0 or start_time_s <= 0.0 or event_time_s < start_time_s:
            return ""
        return round(event_time_s - start_time_s, 6)

    def _append_run_manifest(self, run_id, outcome, ended_at, log_deleted):
        with self._state_lock:
            trigger_time = self._mission_trigger_time
            attack_info = dict(self._attack_info)
            hover_reason_bits = self._hover_reason_bits
            hover_hard_latched = self._hover_hard_latched
            hover_reason = self._hover_reason

        started_at = trigger_time or self._run_start_time
        started_at_s = started_at.to_sec() if started_at is not None else 0.0
        ended_at_s = ended_at.to_sec()
        log_path = self._current_log_path()
        log_retained = bool(log_path and os.path.isfile(log_path))
        delete_reason = outcome if outcome != "SUCCESS_FINISH" else ""

        row = {
            "manifest_version": 1,
            "run_id": run_id,
            "scenario": self.scenario,
            "transport_mode": self.transport_mode,
            "world_name": self.world_name,
            "started_at_s": f"{started_at_s:.6f}",
            "ended_at_s": f"{ended_at_s:.6f}",
            "duration_s": f"{max(ended_at_s - started_at_s, 0.0):.6f}",
            "outcome": outcome,
            "log_retained": str(log_retained).lower(),
            "log_deleted": str(bool(log_deleted)).lower(),
            "delete_reason": delete_reason,
            "attack_source": attack_info["source"],
            "attack_mode": attack_info["mode"],
            "attack_severity": attack_info["severity"],
            "attack_seed": attack_info["seed"],
            "attack_scheduled_onset_s": self._relative_time_s(
                float(attack_info["scheduled_start_s"]), started_at_s
            ),
            "attack_actual_onset_s": self._relative_time_s(
                float(attack_info["actual_onset_s"]), started_at_s
            ),
            "hover_reason_bits": hover_reason_bits if outcome == "SAFETY_HOVER" else "",
            "hover_hard_latched": (
                str(hover_hard_latched).lower()
                if outcome == "SAFETY_HOVER"
                else ""
            ),
            "hover_reason": hover_reason if outcome == "SAFETY_HOVER" else "",
        }
        append_manifest_row(self.manifest_path, row)
        rospy.loginfo(
            "[RUN %s] appended outcome=%s to manifest: %s",
            run_id,
            outcome,
            self.manifest_path,
        )

    def _monitor_one_run(self, run_id: str):
        """
        Return outcome:
          - SUCCESS_FINISH
          - SAFETY_HOVER
          - FAIL_SLAM
          - FAIL_PREMATURE_FINISH
          - TIMEOUT_NO_FINISH
          - ABORTED
        """
        rate = rospy.Rate(20)
        while not rospy.is_shutdown():
            # 1) Finish/Hover: whichever happened first is the terminal outcome.
            terminal_outcome = self._terminal_feedback_outcome()
            if terminal_outcome == "SUCCESS_FINISH":
                valid, duration_s, travel_distance_m = self._completion_is_valid()
                if not valid:
                    rospy.logerr(
                        "[RUN %s] FAIL_PREMATURE_FINISH duration=%.1f/%.1fs "
                        "distance=%.1f/%.1fm",
                        run_id,
                        duration_s,
                        self.success_min_duration_s,
                        travel_distance_m,
                        self.success_min_distance_m,
                    )
                    return "FAIL_PREMATURE_FINISH"
                rospy.loginfo(f"[RUN {run_id}] SUCCESS_FINISH at {self._finish_time.to_sec():.3f}")
                return "SUCCESS_FINISH"
            if terminal_outcome == "SAFETY_HOVER":
                with self._state_lock:
                    hover_time = self._hover_time
                    hover_reason = self._hover_reason
                rospy.logwarn(
                    "[RUN %s] SAFETY_HOVER at %.3f reason=%s",
                    run_id,
                    hover_time.to_sec() if hover_time is not None else 0.0,
                    hover_reason,
                )
                return "SAFETY_HOVER"
            if self._persistent_early_finish():
                duration_s, travel_distance_m = self._completion_metrics()
                rospy.logerr(
                    "[RUN %s] FAIL_PREMATURE_FINISH persistent no-frontier "
                    "duration=%.1f/%.1fs distance=%.1f/%.1fm",
                    run_id,
                    duration_s,
                    self.success_min_duration_s,
                    travel_distance_m,
                    self.success_min_distance_m,
                )
                return "FAIL_PREMATURE_FINISH"

            # 2) fail: e_pos hold
            epos = self._compute_e_pos()
            if epos is not None and epos > self.fail_error_m:
                if self._fail_start_time is None:
                    self._fail_start_time = rospy.Time.now()
                else:
                    held = (rospy.Time.now() - self._fail_start_time).to_sec()
                    if held >= self.fail_hold_s:
                        rospy.logerr(f"[RUN {run_id}] FAIL_SLAM e_pos={epos:.2f}m held={held:.2f}s")
                        return "FAIL_SLAM"
            else:
                self._fail_start_time = None

            # 3) timeout: no finish
            elapsed = (rospy.Time.now() - self._run_start_time).to_sec()
            if elapsed >= self.max_duration_s:
                rospy.logwarn(f"[RUN {run_id}] TIMEOUT_NO_FINISH elapsed={elapsed:.1f}s")
                return "TIMEOUT_NO_FINISH"

            try:
                rate.sleep()
            except rospy.ROSInterruptException:
                return "ABORTED"

        return "ABORTED"

    def _finalize_run(self, run_id, outcome, ended_at):
        # Stop logger before annotating or deleting its output.
        self._stop_logger()
        try:
            self._annotate_current_log(outcome)
        except Exception as exc:
            rospy.logwarn(f"[RUN {run_id}] annotation failed: {exc}")

        try:
            self._write_failure_debug(run_id, outcome, ended_at)
        except Exception as exc:
            rospy.logwarn(f"[RUN {run_id}] failed to write debug summary: {exc}")

        # Dataset governance: only SUCCESS_FINISH keeps the high-frequency CSV.
        log_deleted = False
        if outcome != "SUCCESS_FINISH":
            log_deleted = self._delete_current_log(reason=outcome)
        else:
            rospy.loginfo(f"[RUN {run_id}] kept log (SUCCESS_FINISH).")

        try:
            self._append_run_manifest(run_id, outcome, ended_at, log_deleted)
        except Exception as exc:
            rospy.logerr(f"[RUN {run_id}] failed to append manifest: {exc}")
        self._cached_log_path = ""

    def run(self):
        rospy.loginfo(
            f"[experiment_manager] num_runs={self.num_runs}, output_dir={self.output_dir}, "
            f"scenario={self.scenario}, transport={self.transport_mode}, world={self.world_name}"
        )
        ok = self._wait_ready(timeout_s=60.0)
        if not ok:
            rospy.logerr("[experiment_manager] Inputs not ready: missing GT/EST. Abort.")
            return

        for _ in range(self.num_runs):
            run_id = self._next_global_run_id()
            rospy.loginfo(f"========== RUN {run_id} ==========")

            self._reset_run_flags()
            outcome = "ABORTED"
            interrupted = False
            try:
                # Start logger before the trigger to avoid losing early samples.
                self._start_logger(run_id)
                self._publish_start_trigger()
                outcome = self._monitor_one_run(run_id)
            except (rospy.ROSInterruptException, KeyboardInterrupt):
                interrupted = True
                outcome = "ABORTED"
                rospy.logwarn(f"[RUN {run_id}] interrupted; finalizing as ABORTED.")
            finally:
                self._finalize_run(run_id, outcome, rospy.Time.now())

            if interrupted or rospy.is_shutdown():
                break
            rospy.sleep(self.sleep_between_runs_s)

        rospy.loginfo("[experiment_manager] All runs completed.")


if __name__ == "__main__":
    try:
        mgr = ExperimentManager()
        mgr.run()
    except rospy.ROSInterruptException:
        pass
