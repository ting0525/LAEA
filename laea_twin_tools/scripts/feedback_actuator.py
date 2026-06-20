#!/usr/bin/env python3

"""Turns supervisor feedback into concrete actuation.

v1 actuates only HOVER: it publishes /laea/feedback/pause_exploration, which the
exploration FSM honours by holding position (it stops planning new tours and the
command thread drains the trajectory to a static hover). Either the automatic
supervisor command or a manual dashboard override can request hover; a manual
override cannot release an automatic hover (fail safe). SLOW_DOWN / LAND are
intentionally left as no-ops here until later phases."""

import rospy
from std_msgs.msg import Bool

from laea_twin_tools.msg import SupervisorCommand


class FeedbackActuator:
    def __init__(self):
        rospy.init_node("feedback_actuator", anonymous=False)
        self.rate_hz = max(float(rospy.get_param("~rate_hz", 10.0)), 1.0)
        self.command_level = SupervisorCommand.NONE
        self.override_level = SupervisorCommand.NONE
        self.last_pause = None

        self.pause_pub = rospy.Publisher(
            "/laea/feedback/pause_exploration", Bool, queue_size=1, latch=True
        )
        rospy.Subscriber(
            "/laea/supervisor/command",
            SupervisorCommand,
            self._command_cb,
            queue_size=10,
        )
        rospy.Subscriber(
            "/laea/supervisor/override",
            SupervisorCommand,
            self._override_cb,
            queue_size=10,
        )
        self._publish(False)
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.rate_hz), self._tick)

    def _command_cb(self, msg):
        self.command_level = int(msg.level)

    def _override_cb(self, msg):
        self.override_level = int(msg.level)

    def _hover_requested(self):
        return (
            self.command_level == SupervisorCommand.HOVER
            or self.override_level == SupervisorCommand.HOVER
        )

    def _publish(self, pause):
        if pause != self.last_pause:
            rospy.logwarn(
                "[feedback_actuator] pause_exploration=%s (command=%d override=%d)",
                pause,
                self.command_level,
                self.override_level,
            )
            self.last_pause = pause
        self.pause_pub.publish(Bool(data=bool(pause)))

    def _tick(self, _event):
        self._publish(self._hover_requested())


if __name__ == "__main__":
    FeedbackActuator()
    rospy.spin()
