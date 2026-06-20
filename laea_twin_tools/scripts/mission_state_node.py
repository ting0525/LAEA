#!/usr/bin/env python3

import math
import threading

import numpy as np
import rospy
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import PoseStamped, TwistStamped
from sensor_msgs.msg import FluidPressure, Image, Imu, NavSatFix
from std_msgs.msg import Float64

from laea_twin_tools.msg import MissionState, PlannerTelemetry


EARTH_RADIUS_M = 6378137.0


def quaternion_to_rpy(x, y, z, w):
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    return roll, pitch, math.atan2(siny, cosy)


def wrap_angle(value):
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


class MissionStateNode:
    def __init__(self):
        rospy.init_node("mission_state_node", anonymous=False)
        self.rate_hz = max(float(rospy.get_param("~rate_hz", 10.0)), 1.0)
        self.detector_name = str(rospy.get_param("~detector_name", "rule_mad"))
        self.model_score_topic = str(
            rospy.get_param("~model_score_topic", "/laea/detector/score")
        )
        self.thresholds = dict(rospy.get_param("~thresholds", {}))

        self.bridge = CvBridge()
        self.lock = threading.Lock()
        self.pose = None
        self.velocity = None
        self.gps_fix = None
        self.gps_velocity = None
        self.imu = None
        self.pressure = None
        self.depth = None
        self.planner = None
        self.model_score = 0.0

        self.origin_gps = None
        self.origin_odom = None
        self.origin_pressure = None
        self.origin_z = None
        self.previous_yaw = None
        self.previous_yaw_time = None
        self.yaw_rate_from_pose = 0.0
        self.previous_depth_sample = None
        self.previous_depth_stamp = None

        self.pub = rospy.Publisher(
            "/laea/twin/mission_state", MissionState, queue_size=10
        )
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
            "/mavros/global_position/raw/fix",
            NavSatFix,
            self._gps_fix_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            "/mavros/global_position/raw/gps_vel",
            TwistStamped,
            self._gps_velocity_cb,
            queue_size=20,
        )
        rospy.Subscriber("/mavros/imu/data", Imu, self._imu_cb, queue_size=50)
        rospy.Subscriber(
            "/mavros/imu/static_pressure",
            FluidPressure,
            self._pressure_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            rospy.get_param("~depth_topic", "/rtp/depth/image_raw"),
            Image,
            self._depth_cb,
            queue_size=1,
        )
        rospy.Subscriber(
            "/laea/planner/telemetry",
            PlannerTelemetry,
            self._planner_cb,
            queue_size=20,
        )
        rospy.Subscriber(
            self.model_score_topic, Float64, self._model_score_cb, queue_size=20
        )
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.rate_hz), self._timer_cb)

    def _threshold(self, name, fallback):
        return float(self.thresholds.get(name, fallback))

    def _pose_cb(self, msg):
        p = msg.pose.position
        q = msg.pose.orientation
        roll, pitch, yaw = quaternion_to_rpy(q.x, q.y, q.z, q.w)
        stamp = msg.header.stamp if msg.header.stamp.to_sec() > 0.0 else rospy.Time.now()
        with self.lock:
            if self.previous_yaw is not None and self.previous_yaw_time is not None:
                dt = (stamp - self.previous_yaw_time).to_sec()
                if dt > 1.0e-3:
                    self.yaw_rate_from_pose = wrap_angle(yaw - self.previous_yaw) / dt
            self.previous_yaw = yaw
            self.previous_yaw_time = stamp
            self.pose = (p.x, p.y, p.z, roll, pitch, yaw)
            if self.origin_odom is None:
                self.origin_odom = (p.x, p.y)
                self.origin_z = p.z

    def _velocity_cb(self, msg):
        v = msg.twist.linear
        with self.lock:
            self.velocity = (v.x, v.y, v.z)

    def _gps_fix_cb(self, msg):
        with self.lock:
            self.gps_fix = (msg.latitude, msg.longitude, msg.altitude)
            if self.origin_gps is None and math.isfinite(msg.latitude) and math.isfinite(msg.longitude):
                self.origin_gps = self.gps_fix

    def _gps_velocity_cb(self, msg):
        v = msg.twist.linear
        with self.lock:
            self.gps_velocity = (v.x, v.y, v.z)

    def _imu_cb(self, msg):
        q = msg.orientation
        av = msg.angular_velocity
        la = msg.linear_acceleration
        with self.lock:
            self.imu = (q.x, q.y, q.z, q.w, av.x, av.y, av.z, la.x, la.y, la.z)

    def _pressure_cb(self, msg):
        with self.lock:
            self.pressure = float(msg.fluid_pressure)
            if self.origin_pressure is None and self.pressure > 0.0:
                self.origin_pressure = self.pressure

    def _depth_cb(self, msg):
        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except CvBridgeError:
            return
        depth = np.asarray(image, dtype=np.float32)
        if image.dtype == np.uint16 or msg.encoding in ("16UC1", "mono16"):
            depth = depth / 1000.0
        sample = np.nan_to_num(depth[::8, ::8], nan=0.0, posinf=0.0, neginf=0.0)
        valid = np.isfinite(depth) & (depth > 0.0)
        valid_ratio = float(valid.mean()) if depth.size else 0.0
        repeat_score = 0.0
        with self.lock:
            if (
                self.previous_depth_sample is not None
                and self.previous_depth_sample.shape == sample.shape
                and sample.size
            ):
                repeat_score = float(
                    np.mean(np.abs(sample - self.previous_depth_sample) <= 1.0e-6)
                )
            self.previous_depth_sample = sample
            stamp = msg.header.stamp if msg.header.stamp.to_sec() > 0.0 else rospy.Time.now()
            self.previous_depth_stamp = stamp
            self.depth = (valid_ratio, repeat_score, stamp)

    def _planner_cb(self, msg):
        with self.lock:
            self.planner = msg

    def _model_score_cb(self, msg):
        with self.lock:
            self.model_score = max(float(msg.data), 0.0)

    @staticmethod
    def _level_high(value, degraded, critical):
        if value >= critical:
            return MissionState.CRITICAL
        if value >= degraded:
            return MissionState.DEGRADED
        return MissionState.NORMAL

    @staticmethod
    def _level_low(value, degraded, critical):
        if value <= critical:
            return MissionState.CRITICAL
        if value <= degraded:
            return MissionState.DEGRADED
        return MissionState.NORMAL

    @staticmethod
    def _max_level(*levels):
        return max(levels) if levels else MissionState.NORMAL

    def _timer_cb(self, _event):
        with self.lock:
            pose = self.pose
            velocity = self.velocity
            gps_fix = self.gps_fix
            gps_velocity = self.gps_velocity
            imu = self.imu
            pressure = self.pressure
            depth = self.depth
            planner = self.planner
            model_score = self.model_score
            origin_gps = self.origin_gps
            origin_odom = self.origin_odom
            origin_pressure = self.origin_pressure
            origin_z = self.origin_z
            yaw_rate_from_pose = self.yaw_rate_from_pose

        if pose is None or velocity is None or imu is None:
            return

        gps_pos_residual = 0.0
        if gps_fix and origin_gps and origin_odom:
            lat0 = math.radians(origin_gps[0])
            east = math.radians(gps_fix[1] - origin_gps[1]) * EARTH_RADIUS_M * math.cos(lat0)
            north = math.radians(gps_fix[0] - origin_gps[0]) * EARTH_RADIUS_M
            odom_east = pose[0] - origin_odom[0]
            odom_north = pose[1] - origin_odom[1]
            gps_pos_residual = math.hypot(east - odom_east, north - odom_north)

        gps_vel_residual = 0.0
        if gps_velocity:
            gps_vel_residual = math.sqrt(
                (gps_velocity[0] - velocity[0]) ** 2
                + (gps_velocity[1] - velocity[1]) ** 2
            )
        yaw_rate_residual = abs(imu[6] - yaw_rate_from_pose)

        baro_residual = 0.0
        if pressure and origin_pressure and origin_z is not None and pressure > 0.0:
            baro_delta = 44330.0 * (1.0 - (pressure / origin_pressure) ** 0.1903)
            baro_residual = abs(baro_delta - (pose[2] - origin_z))

        loc_level = self._max_level(
            self._level_high(
                gps_pos_residual,
                self._threshold("gps_position_residual_degraded", 2.0),
                self._threshold("gps_position_residual_critical", 5.0),
            ),
            self._level_high(
                gps_vel_residual,
                self._threshold("gps_velocity_residual_degraded", 0.8),
                self._threshold("gps_velocity_residual_critical", 1.8),
            ),
            self._level_high(
                yaw_rate_residual,
                self._threshold("yaw_rate_residual_degraded", 0.25),
                self._threshold("yaw_rate_residual_critical", 0.70),
            ),
            self._level_high(
                baro_residual,
                self._threshold("baro_altitude_residual_degraded", 0.8),
                self._threshold("baro_altitude_residual_critical", 2.0),
            ),
        )
        loc_score = max(
            gps_pos_residual / self._threshold("gps_position_residual_degraded", 2.0),
            gps_vel_residual / self._threshold("gps_velocity_residual_degraded", 0.8),
            yaw_rate_residual / self._threshold("yaw_rate_residual_degraded", 0.25),
            baro_residual / self._threshold("baro_altitude_residual_degraded", 0.8),
        )

        depth_age_ms = float("inf")
        valid_ratio = 0.0
        repeat_score = 1.0
        if depth:
            valid_ratio, repeat_score, depth_stamp = depth
            depth_age_ms = max((rospy.Time.now() - depth_stamp).to_sec() * 1000.0, 0.0)
        perception_level = self._max_level(
            self._level_high(
                depth_age_ms,
                self._threshold("depth_age_ms_degraded", 250.0),
                self._threshold("depth_age_ms_critical", 1000.0),
            ),
            self._level_low(
                valid_ratio,
                self._threshold("depth_valid_ratio_degraded", 0.35),
                self._threshold("depth_valid_ratio_critical", 0.10),
            ),
            self._level_high(
                repeat_score,
                self._threshold("depth_repeat_score_degraded", 0.98),
                self._threshold("depth_repeat_score_critical", 0.999),
            ),
        )
        perception_score = max(
            depth_age_ms / self._threshold("depth_age_ms_degraded", 250.0),
            self._threshold("depth_valid_ratio_degraded", 0.35) / max(valid_ratio, 1.0e-6),
            repeat_score / self._threshold("depth_repeat_score_degraded", 0.98),
        )

        planner_level = MissionState.NORMAL
        planner_score = 0.0
        if planner:
            planner_level = self._max_level(
                self._level_high(
                    planner.command_age_s,
                    self._threshold("command_age_s_degraded", 0.25),
                    self._threshold("command_age_s_critical", 1.0),
                ),
                self._level_high(
                    planner.tracking_error_m,
                    self._threshold("tracking_error_m_degraded", 1.0),
                    self._threshold("tracking_error_m_critical", 2.5),
                ),
                self._level_high(
                    planner.stall_duration_s,
                    self._threshold("stall_duration_s_degraded", 5.0),
                    self._threshold("stall_duration_s_critical", 15.0),
                ),
            )
            planner_score = max(
                planner.command_age_s / self._threshold("command_age_s_degraded", 0.25),
                planner.tracking_error_m / self._threshold("tracking_error_m_degraded", 1.0),
                planner.stall_duration_s / self._threshold("stall_duration_s_degraded", 5.0),
            )

        speed = math.sqrt(sum(component * component for component in velocity))
        tilt = max(abs(pose[3]), abs(pose[4]))
        flight_level = self._max_level(
            self._level_high(
                tilt,
                self._threshold("tilt_rad_degraded", 0.55),
                self._threshold("tilt_rad_critical", 0.90),
            ),
            self._level_high(
                speed,
                self._threshold("speed_mps_degraded", 2.0),
                self._threshold("speed_mps_critical", 3.5),
            ),
        )
        flight_score = max(
            tilt / self._threshold("tilt_rad_degraded", 0.55),
            speed / self._threshold("speed_mps_degraded", 2.0),
        )

        model_level = self._level_high(
            model_score,
            self._threshold("model_degraded", 1.0),
            self._threshold("model_critical", 2.0),
        )
        overall = self._max_level(
            loc_level, perception_level, planner_level, flight_level, model_level
        )
        degraded_count = sum(
            level >= MissionState.DEGRADED
            for level in (loc_level, perception_level, planner_level, flight_level)
        )
        if overall == MissionState.CRITICAL:
            feedback = MissionState.FEEDBACK_SLOW_DOWN
        elif degraded_count:
            feedback = MissionState.FEEDBACK_ALERT
        else:
            feedback = MissionState.FEEDBACK_NONE

        reason_bits = 0
        if loc_level:
            reason_bits |= MissionState.REASON_LOCALIZATION
        if perception_level:
            reason_bits |= MissionState.REASON_PERCEPTION
        if planner_level:
            reason_bits |= MissionState.REASON_PLANNER
        if flight_level:
            reason_bits |= MissionState.REASON_FLIGHT_SAFETY
        if model_level:
            reason_bits |= MissionState.REASON_MODEL

        msg = MissionState()
        msg.header.stamp = rospy.Time.now()
        msg.localization_level = loc_level
        msg.perception_level = perception_level
        msg.planner_level = planner_level
        msg.flight_safety_level = flight_level
        msg.overall_level = overall
        msg.localization_score = loc_score
        msg.perception_score = perception_score
        msg.planner_score = planner_score
        msg.flight_safety_score = flight_score
        msg.detector_name = self.detector_name
        msg.anomaly_score = model_score
        msg.reason_bits = reason_bits
        msg.recommended_feedback = feedback
        msg.hard_safety_latched = flight_level == MissionState.CRITICAL
        msg.summary = (
            "gps_pos_res=%.3f gps_vel_res=%.3f yaw_rate_res=%.3f "
            "baro_res=%.3f depth_age_ms=%.1f valid=%.3f repeat=%.3f"
            % (
                gps_pos_residual,
                gps_vel_residual,
                yaw_rate_residual,
                baro_residual,
                depth_age_ms,
                valid_ratio,
                repeat_score,
            )
        )
        self.pub.publish(msg)


if __name__ == "__main__":
    MissionStateNode()
    rospy.spin()
