#!/usr/bin/env python3

import json
import random
import threading

import rospy
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String

from laea_twin_tools.msg import AttackCommand, AttackStatus


class AttackScheduler:
    def __init__(self):
        rospy.init_node("attack_scheduler", anonymous=False)

        self.profile = rospy.get_param("~profile", "none")
        self.run_id = str(rospy.get_param("~run_id", ""))
        self.seed = int(rospy.get_param("~seed", 42))
        self.onset_min_s = float(rospy.get_param("~onset_min_s", 120.0))
        self.onset_max_s = float(rospy.get_param("~onset_max_s", 180.0))
        self.rate_hz = max(float(rospy.get_param("~rate_hz", 10.0)), 1.0)

        profiles = dict(
            rospy.get_param("~profiles", rospy.get_param("/profiles", {}))
        )
        selected = dict(profiles.get(self.profile, {}))
        self.source = str(rospy.get_param("~source", selected.get("source", "none")))
        self.mode = str(rospy.get_param("~mode", selected.get("mode", "none")))
        self.severity = str(
            rospy.get_param("~severity", selected.get("severity", "none"))
        )
        self.ramp_s = float(
            rospy.get_param("~ramp_s", selected.get("ramp_s", 0.0))
        )
        self.duration_s = float(
            rospy.get_param("~duration_s", selected.get("duration_s", 0.0))
        )
        self.recovery_s = float(
            rospy.get_param("~recovery_s", selected.get("recovery_s", 0.0))
        )
        self.vector = list(
            rospy.get_param("~vector", selected.get("vector", [0.0, 0.0, 0.0]))
        )
        self.scalar = float(
            rospy.get_param("~scalar", selected.get("scalar", 0.0))
        )
        self.enabled = self.profile not in ("", "none") and self.source != "none"

        self._rng = random.Random(self.seed)
        self._lock = threading.Lock()
        self._trigger_time = None
        self._scheduled_start = None
        self._actual_onset = None
        self._last_active = False

        self.command_pub = rospy.Publisher(
            "/laea/attack/command", AttackCommand, queue_size=1, latch=True
        )
        self.command_json_pub = rospy.Publisher(
            "/laea/attack/command_json", String, queue_size=1, latch=True
        )
        self.status_pub = rospy.Publisher(
            "/laea/attack/status", AttackStatus, queue_size=10, latch=True
        )
        rospy.Subscriber(
            "/traj_start_trigger", PoseStamped, self._trigger_cb, queue_size=1
        )
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.rate_hz), self._timer_cb)

        self._publish_command()
        rospy.loginfo(
            "[attack_scheduler] profile=%s source=%s mode=%s severity=%s seed=%d enabled=%s",
            self.profile,
            self.source,
            self.mode,
            self.severity,
            self.seed,
            self.enabled,
        )

    def _trigger_cb(self, _msg):
        with self._lock:
            if self._trigger_time is not None:
                return
            self._trigger_time = rospy.Time.now()
            delay = self._rng.uniform(self.onset_min_s, self.onset_max_s)
            self._scheduled_start = self._trigger_time + rospy.Duration(delay)
            self._actual_onset = None
            self._last_active = False
        self._publish_command()
        rospy.loginfo(
            "[attack_scheduler] mission triggered; attack starts in %.3fs at %.3f",
            delay,
            self._scheduled_start.to_sec(),
        )

    def _build_command(self):
        msg = AttackCommand()
        msg.header.stamp = rospy.Time.now()
        msg.run_id = self.run_id
        msg.source = self.source
        msg.mode = self.mode
        msg.severity = self.severity
        msg.enabled = self.enabled
        msg.scheduled_start = self._scheduled_start or rospy.Time(0)
        msg.ramp = rospy.Duration(max(self.ramp_s, 0.0))
        msg.duration = rospy.Duration(max(self.duration_s, 0.0))
        msg.recovery = rospy.Duration(max(self.recovery_s, 0.0))
        msg.vector_value.x = float(self.vector[0]) if len(self.vector) > 0 else 0.0
        msg.vector_value.y = float(self.vector[1]) if len(self.vector) > 1 else 0.0
        msg.vector_value.z = float(self.vector[2]) if len(self.vector) > 2 else 0.0
        msg.scalar_value = self.scalar
        msg.seed = self.seed
        return msg

    def _publish_command(self):
        msg = self._build_command()
        self.command_pub.publish(msg)
        payload = {
            "run_id": msg.run_id,
            "source": msg.source,
            "mode": msg.mode,
            "severity": msg.severity,
            "enabled": msg.enabled,
            "scheduled_start": msg.scheduled_start.to_sec(),
            "ramp_s": msg.ramp.to_sec(),
            "duration_s": msg.duration.to_sec(),
            "recovery_s": msg.recovery.to_sec(),
            "vector": [msg.vector_value.x, msg.vector_value.y, msg.vector_value.z],
            "scalar": msg.scalar_value,
            "seed": msg.seed,
        }
        self.command_json_pub.publish(String(data=json.dumps(payload, sort_keys=True)))

    def _timer_cb(self, _event):
        now = rospy.Time.now()
        with self._lock:
            scheduled = self._scheduled_start
            active = False
            elapsed = 0.0
            if self.enabled and scheduled is not None and now >= scheduled:
                elapsed = (now - scheduled).to_sec()
                active = self.duration_s <= 0.0 or elapsed <= self.duration_s
                if active and self._actual_onset is None:
                    self._actual_onset = now
                if active != self._last_active:
                    rospy.loginfo(
                        "[attack_scheduler] source=%s mode=%s active=%s elapsed=%.3f",
                        self.source,
                        self.mode,
                        active,
                        elapsed,
                    )
                self._last_active = active
            actual_onset = self._actual_onset

        status = AttackStatus()
        status.header.stamp = now
        status.run_id = self.run_id
        status.source = self.source
        status.mode = self.mode
        status.severity = self.severity
        status.armed = self.enabled and scheduled is not None
        status.active = active
        status.actual_onset = actual_onset or rospy.Time(0)
        status.elapsed = rospy.Duration(max(elapsed, 0.0))
        status.actual_vector.x = float(self.vector[0]) if len(self.vector) > 0 else 0.0
        status.actual_vector.y = float(self.vector[1]) if len(self.vector) > 1 else 0.0
        status.actual_vector.z = float(self.vector[2]) if len(self.vector) > 2 else 0.0
        status.actual_scalar = self.scalar
        if not self.enabled:
            status.detail = "disabled"
        elif scheduled is None:
            status.detail = "waiting_for_mission_trigger"
        elif active:
            status.detail = "active"
        elif now < scheduled:
            status.detail = "armed"
        else:
            status.detail = "complete"
        self.status_pub.publish(status)


if __name__ == "__main__":
    AttackScheduler()
    rospy.spin()
