#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import math
import os
import threading

import numpy as np
import rospy
from cv_bridge import CvBridge, CvBridgeError
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped, TwistStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import FluidPressure, Image, Imu, MagneticField, NavSatFix
from std_msgs.msg import UInt32


CSV_FIELDS = [
    "run_id", "scenario", "transport_mode", "world_name", "t",
    "pos_x", "pos_y", "pos_z",
    "vel_x", "vel_y", "vel_z",
    "roll", "pitch", "yaw",
    "odom_pose_covariance_summary", "odom_twist_covariance_summary",
    "gps_lat", "gps_lon", "gps_alt",
    "gps_vx", "gps_vy", "gps_vz",
    "gps_fix", "gps_sat", "gps_position_covariance",
    "imu_qx", "imu_qy", "imu_qz", "imu_qw",
    "ang_vel_x", "ang_vel_y", "ang_vel_z",
    "lin_acc_x", "lin_acc_y", "lin_acc_z",
    "mag_x", "mag_y", "mag_z",
    "static_pressure", "static_pressure_variance",
    "depth_dt", "depth_age_ms",
    "depth_valid_ratio", "depth_mean_m", "depth_std_m",
    "depth_near_ratio_1m", "rtp_depth_stale", "rtp_depth_repeat_score",
    "px_gt", "py_gt", "pz_gt", "e_pos", "mission_outcome",
]


def covariance_trace(covariance, dimension):
    """Return the diagonal sum used as one compact uncertainty feature."""
    diagonal = []
    for index in range(dimension):
        value = float(covariance[index * dimension + index])
        if math.isfinite(value) and value >= 0.0:
            diagonal.append(value)
    return sum(diagonal) if diagonal else float("nan")


def quaternion_to_rpy(x, y, z, w):
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


def depth_statistics(depth_m, previous_sample=None, repeat_epsilon=1.0e-6):
    """Calculate per-frame image quality and similarity features in meters."""
    array = np.asarray(depth_m, dtype=np.float32)
    finite = np.isfinite(array)
    clean = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
    valid = finite & (clean > 0.0)
    valid_values = array[valid]

    valid_ratio = float(valid.mean()) if array.size else float("nan")
    if valid_values.size:
        mean_m = float(valid_values.mean())
        std_m = float(valid_values.std())
        near_ratio_1m = float(np.count_nonzero(valid_values <= 1.0) / valid_values.size)
    else:
        mean_m = float("nan")
        std_m = float("nan")
        near_ratio_1m = float("nan")

    sample = np.nan_to_num(array[::8, ::8], nan=0.0, posinf=0.0, neginf=0.0)
    repeat_score = float("nan")
    if previous_sample is not None and previous_sample.shape == sample.shape and sample.size:
        repeat_score = float(np.mean(np.abs(sample - previous_sample) <= repeat_epsilon))

    return {
        "depth_valid_ratio": valid_ratio,
        "depth_mean_m": mean_m,
        "depth_std_m": std_m,
        "depth_near_ratio_1m": near_ratio_1m,
        "sample": sample,
        "rtp_depth_repeat_score": repeat_score,
    }


class SlamKpiLogger(object):
    def __init__(self):
        self.model_name = rospy.get_param(
            "/slam_kpi_logger/model_name", rospy.get_param("~model_name", "iris_0")
        )
        self.output_dir = rospy.get_param(
            "/slam_kpi_logger/output_dir",
            "/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs",
        )
        raw_output_name = rospy.get_param("/slam_kpi_logger/output_name", "kpi_log")
        if not raw_output_name or str(raw_output_name).endswith("_"):
            self.output_name = "kpi_log_%d" % int(rospy.get_time())
        else:
            self.output_name = str(raw_output_name)

        self.run_id = str(rospy.get_param("/slam_kpi_logger/run_id", self.output_name))
        self.scenario = str(rospy.get_param("/slam_kpi_logger/scenario", "normal"))
        self.transport_mode = str(rospy.get_param("/slam_kpi_logger/transport_mode", "unspecified"))
        self.world_name = str(rospy.get_param("/slam_kpi_logger/world_name", "unknown"))
        self.depth_topic = str(rospy.get_param("/slam_kpi_logger/depth_topic", "/rtp/depth/image_raw"))
        self.depth_stale_threshold_s = float(
            rospy.get_param("/slam_kpi_logger/depth_stale_threshold_s", 0.25)
        )
        self.depth_repeat_epsilon = float(
            rospy.get_param("/slam_kpi_logger/depth_repeat_epsilon", 1.0e-6)
        )
        self.rate_hz = float(
            rospy.get_param("/slam_kpi_logger/log_rate", rospy.get_param("~log_rate", 20.0))
        )

        os.makedirs(self.output_dir, exist_ok=True)
        self.file_path = os.path.join(self.output_dir, "%s.csv" % self.output_name)
        rospy.set_param("/laea_twin/current_log_path", self.file_path)
        rospy.set_param("/laea_twin/current_output_name", self.output_name)

        rospy.loginfo("[slam_kpi_logger] run_id=%s scenario=%s transport=%s", self.run_id, self.scenario, self.transport_mode)
        rospy.loginfo("[slam_kpi_logger] world=%s depth_topic=%s log_rate=%.2fHz", self.world_name, self.depth_topic, self.rate_hz)
        rospy.loginfo("[slam_kpi_logger] log file: %s", self.file_path)

        self.csv_file = open(self.file_path, "w", newline="")
        self.writer = csv.DictWriter(self.csv_file, fieldnames=CSV_FIELDS)
        self.writer.writeheader()
        self.csv_file.flush()

        self.lock = threading.Lock()
        self.bridge = CvBridge()
        self.latest_gt = None
        self.latest_est = None
        self.latest_attitude = (float("nan"), float("nan"), float("nan"))
        self.latest_local_vel = None
        self.latest_odom_covariance = (float("nan"), float("nan"))
        self.latest_gps_fix = None
        self.latest_gps_vel = None
        self.latest_gps_sat = float("nan")
        self.latest_imu = None
        self.latest_mag = None
        self.latest_pressure = None
        self.latest_depth = None
        self.previous_depth_stamp = None
        self.previous_depth_sample = None

        self.sub_states = rospy.Subscriber("/gazebo/model_states", ModelStates, self.cb_model_states, queue_size=10)
        self.sub_pose = rospy.Subscriber("/mavros/local_position/pose", PoseStamped, self.cb_pose, queue_size=50)
        self.sub_vel_local = rospy.Subscriber("/mavros/local_position/velocity_local", TwistStamped, self.cb_vel_local, queue_size=50)
        self.sub_odom = rospy.Subscriber("/mavros/local_position/odom", Odometry, self.cb_odom, queue_size=50)
        self.sub_gps_fix = rospy.Subscriber("/mavros/global_position/raw/fix", NavSatFix, self.cb_gps_fix, queue_size=20)
        self.sub_gps_vel = rospy.Subscriber("/mavros/global_position/raw/gps_vel", TwistStamped, self.cb_gps_vel, queue_size=20)
        self.sub_gps_sat = rospy.Subscriber("/mavros/global_position/raw/satellites", UInt32, self.cb_gps_sat, queue_size=20)
        self.sub_imu = rospy.Subscriber("/mavros/imu/data", Imu, self.cb_imu, queue_size=50)
        self.sub_mag = rospy.Subscriber("/mavros/imu/mag", MagneticField, self.cb_mag, queue_size=20)
        self.sub_pressure = rospy.Subscriber("/mavros/imu/static_pressure", FluidPressure, self.cb_pressure, queue_size=20)
        self.sub_depth = rospy.Subscriber(self.depth_topic, Image, self.cb_depth, queue_size=2)
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.rate_hz), self.cb_timer)

    def cb_model_states(self, msg):
        try:
            idx = msg.name.index(self.model_name)
        except ValueError:
            rospy.logwarn_throttle(5.0, "[slam_kpi_logger] model '%s' not found in /gazebo/model_states", self.model_name)
            return
        p = msg.pose[idx].position
        with self.lock:
            self.latest_gt = (p.x, p.y, p.z)

    def cb_pose(self, msg):
        p = msg.pose.position
        q = msg.pose.orientation
        with self.lock:
            self.latest_est = (p.x, p.y, p.z)
            self.latest_attitude = quaternion_to_rpy(q.x, q.y, q.z, q.w)

    def cb_vel_local(self, msg):
        v = msg.twist.linear
        with self.lock:
            self.latest_local_vel = (v.x, v.y, v.z)

    def cb_odom(self, msg):
        pose_trace = covariance_trace(msg.pose.covariance, 6)
        twist_trace = covariance_trace(msg.twist.covariance, 6)
        with self.lock:
            self.latest_odom_covariance = (pose_trace, twist_trace)

    def cb_gps_fix(self, msg):
        covariance = float("nan")
        if msg.position_covariance_type != NavSatFix.COVARIANCE_TYPE_UNKNOWN:
            covariance = covariance_trace(msg.position_covariance, 3)
        with self.lock:
            self.latest_gps_fix = (msg.latitude, msg.longitude, msg.altitude, msg.status.status, covariance)

    def cb_gps_vel(self, msg):
        v = msg.twist.linear
        with self.lock:
            self.latest_gps_vel = (v.x, v.y, v.z)

    def cb_gps_sat(self, msg):
        with self.lock:
            self.latest_gps_sat = float(msg.data)

    def cb_imu(self, msg):
        q = msg.orientation
        av = msg.angular_velocity
        la = msg.linear_acceleration
        with self.lock:
            self.latest_imu = (q.x, q.y, q.z, q.w, av.x, av.y, av.z, la.x, la.y, la.z)

    def cb_mag(self, msg):
        m = msg.magnetic_field
        with self.lock:
            self.latest_mag = (m.x, m.y, m.z)

    def cb_pressure(self, msg):
        with self.lock:
            self.latest_pressure = (msg.fluid_pressure, msg.variance)

    def cb_depth(self, msg):
        receive_t = rospy.get_time()
        stamp = msg.header.stamp.to_sec()
        measurement_t = stamp if stamp > 0.0 else receive_t
        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            depth_m = np.asarray(image, dtype=np.float32)
            if msg.encoding in ("16UC1", "mono16") or image.dtype == np.uint16:
                depth_m = depth_m / 1000.0
            with self.lock:
                stats = depth_statistics(depth_m, self.previous_depth_sample, self.depth_repeat_epsilon)
                depth_dt = float("nan")
                if self.previous_depth_stamp is not None:
                    depth_dt = measurement_t - self.previous_depth_stamp
                self.previous_depth_stamp = measurement_t
                self.previous_depth_sample = stats.pop("sample")
                stats["depth_dt"] = depth_dt
                stats["measurement_t"] = measurement_t
                stats["receive_t"] = receive_t
                self.latest_depth = stats
        except CvBridgeError as error:
            rospy.logwarn_throttle(5.0, "[slam_kpi_logger] cannot decode depth image: %s", str(error))

    @staticmethod
    def _values_or_nan(values, length):
        return values if values is not None else (float("nan"),) * length

    def cb_timer(self, _event):
        with self.lock:
            gt = self.latest_gt
            est = self.latest_est
            attitude = self.latest_attitude
            local_vel = self.latest_local_vel
            odom_covariance = self.latest_odom_covariance
            gps_fix = self.latest_gps_fix
            gps_vel = self.latest_gps_vel
            gps_sat = self.latest_gps_sat
            imu = self.latest_imu
            mag = self.latest_mag
            pressure = self.latest_pressure
            depth = dict(self.latest_depth) if self.latest_depth is not None else None

        if gt is None or est is None:
            return

        t = rospy.get_time()
        x_gt, y_gt, z_gt = gt
        x_est, y_est, z_est = est
        vx, vy, vz = self._values_or_nan(local_vel, 3)
        roll, pitch, yaw = attitude
        pose_covariance, twist_covariance = odom_covariance
        gps_lat, gps_lon, gps_alt, gps_status, gps_covariance = self._values_or_nan(gps_fix, 5)
        gps_vx, gps_vy, gps_vz = self._values_or_nan(gps_vel, 3)
        imu_qx, imu_qy, imu_qz, imu_qw, ang_x, ang_y, ang_z, acc_x, acc_y, acc_z = self._values_or_nan(imu, 10)
        mag_x, mag_y, mag_z = self._values_or_nan(mag, 3)
        pressure_value, pressure_variance = self._values_or_nan(pressure, 2)
        e_pos = math.sqrt((x_gt - x_est) ** 2 + (y_gt - y_est) ** 2 + (z_gt - z_est) ** 2)

        depth_values = {
            "depth_dt": float("nan"),
            "depth_age_ms": float("nan"),
            "depth_valid_ratio": float("nan"),
            "depth_mean_m": float("nan"),
            "depth_std_m": float("nan"),
            "depth_near_ratio_1m": float("nan"),
            "rtp_depth_stale": 1,
            "rtp_depth_repeat_score": float("nan"),
        }
        if depth is not None:
            depth_values.update({
                "depth_dt": depth["depth_dt"],
                "depth_age_ms": max(0.0, (t - depth["measurement_t"]) * 1000.0),
                "depth_valid_ratio": depth["depth_valid_ratio"],
                "depth_mean_m": depth["depth_mean_m"],
                "depth_std_m": depth["depth_std_m"],
                "depth_near_ratio_1m": depth["depth_near_ratio_1m"],
                "rtp_depth_stale": int((t - depth["receive_t"]) > self.depth_stale_threshold_s),
                "rtp_depth_repeat_score": depth["rtp_depth_repeat_score"],
            })

        row = {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "transport_mode": self.transport_mode,
            "world_name": self.world_name,
            "t": t,
            "pos_x": x_est, "pos_y": y_est, "pos_z": z_est,
            "vel_x": vx, "vel_y": vy, "vel_z": vz,
            "roll": roll, "pitch": pitch, "yaw": yaw,
            "odom_pose_covariance_summary": pose_covariance,
            "odom_twist_covariance_summary": twist_covariance,
            "gps_lat": gps_lat, "gps_lon": gps_lon, "gps_alt": gps_alt,
            "gps_vx": gps_vx, "gps_vy": gps_vy, "gps_vz": gps_vz,
            "gps_fix": gps_status, "gps_sat": gps_sat,
            "gps_position_covariance": gps_covariance,
            "imu_qx": imu_qx, "imu_qy": imu_qy, "imu_qz": imu_qz, "imu_qw": imu_qw,
            "ang_vel_x": ang_x, "ang_vel_y": ang_y, "ang_vel_z": ang_z,
            "lin_acc_x": acc_x, "lin_acc_y": acc_y, "lin_acc_z": acc_z,
            "mag_x": mag_x, "mag_y": mag_y, "mag_z": mag_z,
            "static_pressure": pressure_value,
            "static_pressure_variance": pressure_variance,
            "px_gt": x_gt, "py_gt": y_gt, "pz_gt": z_gt,
            "e_pos": e_pos,
            "mission_outcome": "RUNNING",
        }
        row.update(depth_values)
        self.writer.writerow(row)
        self.csv_file.flush()

    def shutdown(self):
        rospy.loginfo("[slam_kpi_logger] shutting down")
        try:
            self.timer.shutdown()
        except Exception:
            pass
        try:
            self.csv_file.close()
        except Exception:
            pass


if __name__ == "__main__":
    rospy.init_node("slam_kpi_logger")
    node = SlamKpiLogger()
    rospy.on_shutdown(node.shutdown)
    rospy.spin()
