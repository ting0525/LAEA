#!/usr/bin/env python3
"""Print live GPS/odom residuals against Gazebo ground truth for attack runs."""

import math
import os

import rospy
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import NavSatFix


EARTH_RADIUS_M = 6353000.0
DEFAULT_HOME_LAT_DEG = 47.397742
DEFAULT_HOME_LON_DEG = 8.545594
DEFAULT_HOME_ALT_M = 488.0


class GpsAttackMonitor:
    def __init__(self):
        rospy.init_node("gps_attack_monitor", anonymous=False)

        self.model_name = rospy.get_param("~model_name", os.getenv("GPS_ATTACK_MODEL_NAME", "iris_0"))
        self.period_s = float(rospy.get_param("~period_s", os.getenv("GPS_ATTACK_MONITOR_PERIOD_S", "1.0")))
        self.warn_threshold_m = float(
            rospy.get_param("~warn_threshold_m", os.getenv("GPS_ATTACK_MONITOR_WARN_M", "2.0"))
        )

        self.home_lat_rad = math.radians(float(os.getenv("PX4_HOME_LAT", DEFAULT_HOME_LAT_DEG)))
        self.home_lon_rad = math.radians(float(os.getenv("PX4_HOME_LON", DEFAULT_HOME_LON_DEG)))
        self.home_alt_m = float(os.getenv("PX4_HOME_ALT", DEFAULT_HOME_ALT_M))

        self.gt_xyz = None
        self.odom_xyz = None
        self.gps_enu = None
        self.warned = False

        rospy.Subscriber("/gazebo/model_states", ModelStates, self._gt_cb, queue_size=5)
        rospy.Subscriber("/mavros/local_position/pose", PoseStamped, self._odom_cb, queue_size=20)
        rospy.Subscriber("/mavros/global_position/raw/fix", NavSatFix, self._gps_cb, queue_size=20)

    def _gt_cb(self, msg):
        try:
            idx = msg.name.index(self.model_name)
        except ValueError:
            return
        p = msg.pose[idx].position
        self.gt_xyz = (p.x, p.y, p.z)

    def _odom_cb(self, msg):
        p = msg.pose.position
        self.odom_xyz = (p.x, p.y, p.z)

    def _gps_cb(self, msg):
        lat = math.radians(msg.latitude)
        lon = math.radians(msg.longitude)
        north = (lat - self.home_lat_rad) * EARTH_RADIUS_M
        east = (lon - self.home_lon_rad) * EARTH_RADIUS_M * math.cos(self.home_lat_rad)
        up = msg.altitude - self.home_alt_m
        self.gps_enu = (east, north, up)

    @staticmethod
    def _diff(a, b):
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        dz = a[2] - b[2]
        return dx, dy, dz, math.hypot(dx, dy), math.sqrt(dx * dx + dy * dy + dz * dz)

    def run(self):
        rospy.loginfo(
            "[gps_attack_monitor] watching %s; warning threshold %.2fm",
            self.model_name,
            self.warn_threshold_m,
        )
        rate = rospy.Rate(1.0 / self.period_s)

        while not rospy.is_shutdown():
            if self.gt_xyz and self.odom_xyz and self.gps_enu:
                odx, ody, odz, od_h, od_3d = self._diff(self.odom_xyz, self.gt_xyz)
                gdx, gdy, gdz, gps_h, gps_3d = self._diff(self.gps_enu, self.gt_xyz)

                prefix = "[gps_attack_monitor]"
                if gps_h >= self.warn_threshold_m or od_h >= self.warn_threshold_m:
                    prefix = "[gps_attack_monitor][ATTACK_VISIBLE]"
                    self.warned = True

                rospy.loginfo(
                    "%s gps_minus_gt=(%.2f, %.2f, %.2f)m horiz=%.2fm  "
                    "odom_minus_gt=(%.2f, %.2f, %.2f)m horiz=%.2fm",
                    prefix,
                    gdx,
                    gdy,
                    gdz,
                    gps_h,
                    odx,
                    ody,
                    odz,
                    od_h,
                )
            else:
                rospy.loginfo(
                    "[gps_attack_monitor] waiting for gt=%s odom=%s gps=%s",
                    self.gt_xyz is not None,
                    self.odom_xyz is not None,
                    self.gps_enu is not None,
                )

            rate.sleep()


if __name__ == "__main__":
    try:
        GpsAttackMonitor().run()
    except rospy.ROSInterruptException:
        pass
