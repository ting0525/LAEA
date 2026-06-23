"""ROS telemetry monitor + live attack / supervisor command publishers."""

import json
import threading
import time

import rospy
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import State
from sensor_msgs.msg import CameraInfo
from std_msgs.msg import String, UInt32

from laea_twin_tools.msg import (
    AttackCommand,
    AttackStatus,
    MissionState,
    SupervisorCommand,
)

from .common import feedback_name, level_name


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
            "/rtp/depth/camera_info",
            CameraInfo,
            self._depth_info_cb,
            queue_size=2,
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

    def _depth_info_cb(self, msg):
        with self.lock:
            self.state["depth"] = {
                "width": int(msg.width),
                "height": int(msg.height),
                "encoding": "metadata",
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


