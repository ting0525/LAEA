#!/usr/bin/env python3

import threading

import rospy
from geometry_msgs.msg import PoseStamped

from laea_twin_tools.msg import (
    MissionState,
    SupervisorCommand,
    SupervisorEvent,
)


class SupervisorNode:
    def __init__(self):
        rospy.init_node("mission_supervisor", anonymous=False)
        self.policy = str(rospy.get_param("~policy", "hybrid"))
        self.rate_hz = max(float(rospy.get_param("~rate_hz", 10.0)), 1.0)
        self.speed_scale = float(rospy.get_param("~slow_down_scale", 0.5))
        persistence = dict(rospy.get_param("~persistence", {}))
        self.degraded_s = float(
            rospy.get_param("~degraded_s", persistence.get("degraded_s", 1.0))
        )
        self.slow_down_s = float(
            rospy.get_param("~slow_down_s", persistence.get("slow_down_s", 2.0))
        )
        self.hover_s = float(
            rospy.get_param("~hover_s", persistence.get("hover_s", 3.0))
        )
        self.healthy_recovery_s = float(
            rospy.get_param(
                "~healthy_recovery_s",
                persistence.get("healthy_recovery_s", 5.0),
            )
        )

        self.lock = threading.Lock()
        self.latest_state = None
        self.latest_pose = None
        self.level = SupervisorCommand.NONE
        self.level_since = rospy.Time.now()
        self.degraded_since = None
        self.critical_since = None
        self.healthy_since = None
        self.hard_latched = False
        self.hold_pose = None
        self.manual_override = None
        self.manual_override_reason = ""
        self.manual_override_reason_bits = 0
        self.mission_active = False

        self.command_pub = rospy.Publisher(
            "/laea/supervisor/command", SupervisorCommand, queue_size=10, latch=True
        )
        self.event_pub = rospy.Publisher(
            "/laea/supervisor/event", SupervisorEvent, queue_size=20
        )
        rospy.Subscriber(
            "/laea/twin/mission_state", MissionState, self._state_cb, queue_size=20
        )
        rospy.Subscriber(
            "/mavros/local_position/pose", PoseStamped, self._pose_cb, queue_size=20
        )
        rospy.Subscriber(
            rospy.get_param(
                "~override_topic", "/laea/supervisor/override"
            ),
            SupervisorCommand,
            self._override_cb,
            queue_size=10,
        )
        rospy.Subscriber(
            rospy.get_param("~start_topic", "/traj_start_trigger"),
            PoseStamped,
            self._mission_start_cb,
            queue_size=1,
        )
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.rate_hz), self._timer_cb)

    def _state_cb(self, msg):
        with self.lock:
            self.latest_state = msg

    def _pose_cb(self, msg):
        with self.lock:
            self.latest_pose = msg

    def _mission_start_cb(self, _msg):
        now = rospy.Time.now()
        with self.lock:
            self.mission_active = True
            self.level = SupervisorCommand.NONE
            self.level_since = now
            self.degraded_since = None
            self.critical_since = None
            self.healthy_since = now
            self.hard_latched = False
            self.hold_pose = None
        rospy.loginfo(
            "[mission_supervisor] mission trigger received; automatic policy armed"
        )

    def _override_cb(self, msg):
        with self.lock:
            if msg.level == SupervisorCommand.NONE:
                had_override = self.manual_override is not None
                self.manual_override = None
                self.manual_override_reason = ""
                self.manual_override_reason_bits = 0
                state = self.latest_state
            elif msg.level in (
                SupervisorCommand.ALERT,
                SupervisorCommand.SLOW_DOWN,
                SupervisorCommand.HOVER,
            ):
                had_override = False
                self.manual_override = int(msg.level)
                self.manual_override_reason = msg.reason or "manual_override"
                self.manual_override_reason_bits = int(msg.reason_bits)
                state = self.latest_state
            else:
                return

        if msg.level == SupervisorCommand.NONE:
            if had_override:
                self._transition(
                    SupervisorCommand.NONE,
                    state,
                    "manual_override_cleared",
                    recovered=True,
                )
            rospy.logwarn("[mission_supervisor] manual override cleared")
            return

        self._transition(
            int(msg.level),
            state,
            self.manual_override_reason,
        )
        rospy.logwarn(
            "[mission_supervisor] manual override level=%d reason=%s",
            msg.level,
            self.manual_override_reason,
        )

    def _transition(self, new_level, state, reason, recovered=False):
        if new_level == self.level:
            return
        old_level = self.level
        self.level = new_level
        self.level_since = rospy.Time.now()
        if new_level == SupervisorCommand.HOVER and self.latest_pose is not None:
            self.hold_pose = self.latest_pose
        event = SupervisorEvent()
        event.header.stamp = self.level_since
        event.previous_level = old_level
        event.new_level = new_level
        event.recovered = recovered
        event.hard_latched = self.hard_latched
        event.reason_bits = state.reason_bits if state else 0
        event.reason = reason
        self.event_pub.publish(event)
        rospy.logwarn(
            "[mission_supervisor] level %d -> %d hard=%s reason=%s",
            old_level,
            new_level,
            self.hard_latched,
            reason,
        )

    def _timer_cb(self, _event):
        now = rospy.Time.now()
        with self.lock:
            state = self.latest_state
            pose = self.latest_pose
            manual_override = self.manual_override
            manual_override_reason = self.manual_override_reason
            manual_override_reason_bits = self.manual_override_reason_bits
            mission_active = self.mission_active

        if manual_override is None and (state is None or not mission_active):
            if self.level != SupervisorCommand.NONE:
                self._transition(
                    SupervisorCommand.NONE,
                    state,
                    "waiting_for_mission_trigger",
                    recovered=True,
                )
            self._publish_command(
                now,
                state,
                pose,
                manual_override,
                manual_override_reason,
                manual_override_reason_bits,
            )
            return
        if manual_override is not None:
            self._transition(
                manual_override,
                state,
                manual_override_reason or "manual_override",
            )
        elif self.policy == "none":
            self._transition(SupervisorCommand.NONE, state, "policy_none")
        else:
            domain_levels = (
                state.localization_level,
                state.perception_level,
                state.planner_level,
                state.flight_safety_level,
            )
            degraded_count = sum(level >= MissionState.DEGRADED for level in domain_levels)
            critical = (
                state.overall_level >= MissionState.CRITICAL
                or state.hard_safety_latched
            )
            healthy = state.overall_level == MissionState.NORMAL

            if degraded_count:
                self.degraded_since = self.degraded_since or now
            else:
                self.degraded_since = None
            if critical:
                self.critical_since = self.critical_since or now
            else:
                self.critical_since = None
            if healthy:
                self.healthy_since = self.healthy_since or now
            else:
                self.healthy_since = None

            if state.hard_safety_latched:
                self.hard_latched = True

            critical_age = (
                (now - self.critical_since).to_sec() if self.critical_since else 0.0
            )
            degraded_age = (
                (now - self.degraded_since).to_sec() if self.degraded_since else 0.0
            )
            healthy_age = (
                (now - self.healthy_since).to_sec() if self.healthy_since else 0.0
            )

            if self.hard_latched or critical_age >= self.hover_s:
                self._transition(
                    SupervisorCommand.HOVER,
                    state,
                    "hard_safety" if self.hard_latched else "critical_persisted",
                )
            elif self.level == SupervisorCommand.HOVER:
                if healthy_age >= self.healthy_recovery_s:
                    self._transition(
                        SupervisorCommand.SLOW_DOWN,
                        state,
                        "hover_recovery",
                        recovered=True,
                    )
                    self.healthy_since = now
            elif self.level == SupervisorCommand.SLOW_DOWN:
                if healthy_age >= self.healthy_recovery_s:
                    self._transition(
                        SupervisorCommand.NONE,
                        state,
                        "slow_down_recovery",
                        recovered=True,
                    )
                elif critical or (degraded_count >= 2 and degraded_age >= self.slow_down_s):
                    pass
            elif critical or (degraded_count >= 2 and degraded_age >= self.slow_down_s):
                self._transition(
                    SupervisorCommand.SLOW_DOWN, state, "multi_domain_or_critical"
                )
            elif degraded_count and degraded_age >= self.degraded_s:
                self._transition(SupervisorCommand.ALERT, state, "degraded_persisted")
            elif self.level == SupervisorCommand.ALERT and healthy_age >= self.healthy_recovery_s:
                self._transition(
                    SupervisorCommand.NONE, state, "alert_recovery", recovered=True
                )

        self._publish_command(
            now,
            state,
            pose,
            manual_override,
            manual_override_reason,
            manual_override_reason_bits,
        )

    def _publish_command(
        self,
        now,
        state,
        pose,
        manual_override,
        manual_override_reason,
        manual_override_reason_bits,
    ):
        command = SupervisorCommand()
        command.header.stamp = now
        command.level = self.level
        command.speed_scale = (
            self.speed_scale
            if self.level == SupervisorCommand.SLOW_DOWN
            else 0.0
            if self.level == SupervisorCommand.HOVER
            else 1.0
        )
        command.hold_position = self.level == SupervisorCommand.HOVER
        hold = self.hold_pose or pose
        if hold is not None:
            command.hold_point = hold.pose.position
        command.hold_yaw = 0.0
        command.hard_latched = self.hard_latched
        command.reason_bits = (
            manual_override_reason_bits
            if manual_override is not None
            else state.reason_bits
            if state is not None
            else 0
        )
        command.reason = (
            manual_override_reason
            if manual_override is not None
            else state.summary
            if state is not None
            else "waiting_for_mission_trigger"
        )
        self.command_pub.publish(command)


if __name__ == "__main__":
    SupervisorNode()
    rospy.spin()
