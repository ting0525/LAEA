#!/usr/bin/env python3
"""Show live LAEA attack evidence in a terminal."""

import argparse
import math
import sys
import threading

import rospy
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import State

from laea_twin_tools.msg import AttackCommand, MissionState


LEVEL_NAMES = {
    MissionState.NORMAL: "NORMAL",
    MissionState.DEGRADED: "DEGRADED",
    MissionState.CRITICAL: "CRITICAL",
}


def level_name(value):
    return LEVEL_NAMES.get(int(value), "UNKNOWN")


def fmt_xyz(value):
    if value is None:
        return "waiting"
    return f"[{value[0]:7.2f}, {value[1]:7.2f}, {value[2]:7.2f}] m"


class AttackTerminalMonitor:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.gt_xyz = None
        self.ekf_xyz = None
        self.mavros = None
        self.mission = None
        self.command = None
        self.command_key = None
        self.latest_drift_m = None
        self.baseline_drift_m = None
        self.current_drift_m = None
        self.peak_drift_m = None
        self.impact_observed = False

        rospy.Subscriber(
            "/gazebo/model_states", ModelStates, self._ground_truth_cb, queue_size=5
        )
        rospy.Subscriber(
            "/mavros/local_position/pose", PoseStamped, self._ekf_cb, queue_size=20
        )
        rospy.Subscriber("/mavros/state", State, self._mavros_cb, queue_size=20)
        rospy.Subscriber(
            "/laea/attack/command", AttackCommand, self._command_cb, queue_size=10
        )
        rospy.Subscriber(
            "/laea/twin/mission_state",
            MissionState,
            self._mission_cb,
            queue_size=20,
        )

    def _ground_truth_cb(self, msg):
        try:
            index = msg.name.index(self.args.model)
        except ValueError:
            return
        point = msg.pose[index].position
        with self.lock:
            self.gt_xyz = (point.x, point.y, point.z)
            self._update_drift_locked()

    def _ekf_cb(self, msg):
        point = msg.pose.position
        with self.lock:
            self.ekf_xyz = (point.x, point.y, point.z)
            self._update_drift_locked()

    def _mavros_cb(self, msg):
        with self.lock:
            self.mavros = {
                "connected": bool(msg.connected),
                "armed": bool(msg.armed),
                "mode": msg.mode,
            }

    def _mission_cb(self, msg):
        with self.lock:
            self.mission = {
                "localization": level_name(msg.localization_level),
                "localization_score": msg.localization_score,
                "overall": level_name(msg.overall_level),
                "summary": msg.summary,
            }

    def _command_cb(self, msg):
        command = {
            "run_id": msg.run_id,
            "source": msg.source,
            "mode": msg.mode,
            "severity": msg.severity,
            "enabled": bool(msg.enabled),
            "scheduled_start_s": msg.scheduled_start.to_sec(),
            "ramp_s": msg.ramp.to_sec(),
            "duration_s": msg.duration.to_sec(),
            "recovery_s": msg.recovery.to_sec(),
            "vector": (
                msg.vector_value.x,
                msg.vector_value.y,
                msg.vector_value.z,
            ),
            "scalar": msg.scalar_value,
        }
        key = (
            command["source"],
            command["mode"],
            command["scheduled_start_s"],
            command["enabled"],
        )
        with self.lock:
            self.command = command
            if command["enabled"] and command["source"] != "none":
                if key != self.command_key:
                    self.command_key = key
                    self.baseline_drift_m = self.latest_drift_m
                    self.current_drift_m = self.latest_drift_m
                    self.peak_drift_m = self.latest_drift_m
                    self.impact_observed = False

    def _update_drift_locked(self):
        if self.gt_xyz is None or self.ekf_xyz is None:
            return
        # Match Dashboard evidence: horizontal PX4 EKF position error against
        # Gazebo model ground truth. Vertical frames have a fixed offset in the
        # current stack, so Z is displayed but excluded from this metric.
        dx = self.ekf_xyz[0] - self.gt_xyz[0]
        dy = self.ekf_xyz[1] - self.gt_xyz[1]
        self.latest_drift_m = math.hypot(dx, dy)

        if not self.command or not self.command["enabled"]:
            return
        if self.command["source"] == "none":
            return
        if self.baseline_drift_m is None:
            self.baseline_drift_m = self.latest_drift_m
        self.current_drift_m = self.latest_drift_m
        if self.peak_drift_m is None:
            self.peak_drift_m = self.latest_drift_m
        else:
            self.peak_drift_m = max(self.peak_drift_m, self.latest_drift_m)
        increase = max(self.peak_drift_m - self.baseline_drift_m, 0.0)
        self.impact_observed = increase >= self.args.threshold

    @staticmethod
    def _phase(command, now_s):
        if not command or not command["enabled"]:
            return "INACTIVE", 0.0
        start_s = command["scheduled_start_s"]
        if start_s <= 0.0:
            return "WAITING", 0.0
        elapsed_s = now_s - start_s
        if elapsed_s < 0.0:
            return "SCHEDULED", elapsed_s
        if command["ramp_s"] > 0.0 and elapsed_s < command["ramp_s"]:
            return "RAMP", elapsed_s
        if command["duration_s"] <= 0.0 or elapsed_s < command["duration_s"]:
            return "ACTIVE", elapsed_s
        if elapsed_s < command["duration_s"] + command["recovery_s"]:
            return "RECOVERY", elapsed_s
        return "COMPLETE", elapsed_s

    def _snapshot(self):
        with self.lock:
            command = dict(self.command) if self.command else None
            mission = dict(self.mission) if self.mission else None
            mavros = dict(self.mavros) if self.mavros else None
            baseline = self.baseline_drift_m
            current = self.current_drift_m
            peak = self.peak_drift_m
            return {
                "gt": self.gt_xyz,
                "ekf": self.ekf_xyz,
                "latest": self.latest_drift_m,
                "mavros": mavros,
                "mission": mission,
                "command": command,
                "baseline": baseline,
                "current": current,
                "peak": peak,
                "increase": (
                    max(peak - baseline, 0.0)
                    if peak is not None and baseline is not None
                    else None
                ),
                "impact_observed": self.impact_observed,
            }

    def _render(self):
        data = self._snapshot()
        command = data["command"]
        mission = data["mission"]
        mavros = data["mavros"]
        phase, elapsed_s = self._phase(command, rospy.Time.now().to_sec())

        if command and command["enabled"] and command["source"] != "none":
            attack_name = (
                f"{command['source']} / {command['mode']} / {command['severity']}"
            )
            unit = "m/s" if command["mode"] == "velocity_bias" else "m"
            vector = command["vector"]
            magnitude = (
                f"[{vector[0]:.2f}, {vector[1]:.2f}, {vector[2]:.2f}] {unit}"
            )
        else:
            attack_name = "none"
            magnitude = "—"

        ready = bool(
            mavros
            and mavros["connected"]
            and data["gt"] is not None
            and data["ekf"] is not None
        )
        if not ready:
            result = "WAITING FOR PX4 / GAZEBO DATA"
        elif data["impact_observed"]:
            result = "ATTACK IMPACT OBSERVED"
        elif command and command["enabled"]:
            result = "MEASURING"
        else:
            result = "READY — NO ATTACK"

        lines = [
            "LAEA ATTACK TERMINAL MONITOR",
            "=" * 72,
            (
                f"PX4          : {'ONLINE' if ready else 'WAITING'}"
                + (
                    f" | mode={mavros['mode']} | armed={mavros['armed']}"
                    if mavros
                    else ""
                )
            ),
            "Injection    : GPS sensor -> PX4 EKF2",
            f"Attack       : {attack_name}",
            f"Magnitude    : {magnitude}",
            f"Phase        : {phase} | elapsed={max(elapsed_s, 0.0):.1f} s",
            "",
            f"Gazebo GT    : {fmt_xyz(data['gt'])}",
            f"PX4 EKF      : {fmt_xyz(data['ekf'])}",
            (
                "Drift (XY)   : "
                f"baseline={data['baseline']:.2f} m | "
                f"current={data['current']:.2f} m | "
                f"peak={data['peak']:.2f} m | "
                f"increase=+{data['increase']:.2f} m"
                if data["increase"] is not None
                else (
                    f"Drift (XY)   : current={data['latest']:.2f} m "
                    "| attack baseline not set"
                    if data["latest"] is not None
                    else "Drift (XY)   : waiting"
                )
            ),
            "",
            (
                f"Mission      : localization={mission['localization']} "
                f"(score={mission['localization_score']:.3f}) | "
                f"overall={mission['overall']}"
                if mission
                else "Mission      : waiting"
            ),
            f"Result       : {result}",
            (
                f"Residuals    : {mission['summary']}"
                if mission and mission["summary"]
                else "Residuals    : waiting"
            ),
            "=" * 72,
            "Ctrl-C to exit",
        ]
        return "\n".join(lines), result

    def run(self):
        rate = rospy.Rate(1.0 / self.args.period)
        interactive = sys.stdout.isatty() and not self.args.plain
        last_plain_result = None

        while not rospy.is_shutdown():
            output, result = self._render()
            if interactive:
                print("\033[2J\033[H" + output, flush=True)
            elif result != last_plain_result or self.args.verbose:
                print(output, flush=True)
                last_plain_result = result
            rate.sleep()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="iris_0", help="Gazebo model name")
    parser.add_argument(
        "--period", type=float, default=0.5, help="Refresh period in seconds"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Drift increase required for ATTACK IMPACT OBSERVED",
    )
    parser.add_argument(
        "--plain", action="store_true", help="Disable terminal screen refresh"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="With --plain, print every refresh instead of state changes only",
    )
    return parser.parse_args(rospy.myargv()[1:])


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.period <= 0.0:
        raise SystemExit("--period must be greater than zero")
    if arguments.threshold < 0.0:
        raise SystemExit("--threshold cannot be negative")
    rospy.init_node("laea_attack_terminal_monitor", anonymous=True)
    try:
        AttackTerminalMonitor(arguments).run()
    except rospy.ROSInterruptException:
        pass
