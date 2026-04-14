#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import math
import threading
import urllib.error
import urllib.parse
import urllib.request

import rospy
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import ExtendedState, State
from sensor_msgs.msg import FluidPressure, Imu, MagneticField, NavSatFix
from std_msgs.msg import UInt32


class DittoBridge:
    def __init__(self):
        rospy.init_node("ditto_bridge", anonymous=False)

        self.base_url = rospy.get_param("~base_url", "http://localhost:8080/api/2").rstrip("/")
        self.username = rospy.get_param("~username", "ditto")
        self.password = rospy.get_param("~password", "ditto")
        self.request_timeout_s = float(rospy.get_param("~request_timeout_s", 2.0))

        self.thing_id = rospy.get_param("~thing_id", "laea:iris_0")
        self.policy_id = rospy.get_param("~policy_id", "")
        self.auto_create_thing = self._as_bool(rospy.get_param("~auto_create_thing", True))

        self.enable_pose = self._as_bool(rospy.get_param("~enable_pose", True))
        self.enable_gps = self._as_bool(rospy.get_param("~enable_gps", True))
        self.enable_imu = self._as_bool(rospy.get_param("~enable_imu", True))
        self.enable_nav_aux = self._as_bool(rospy.get_param("~enable_nav_aux", True))
        self.enable_slam = self._as_bool(rospy.get_param("~enable_slam", False))

        self.pose_feature = rospy.get_param("~pose_feature", "pose_local")
        self.gps_feature = rospy.get_param("~gps_feature", "gps")
        self.imu_feature = rospy.get_param("~imu_feature", "imu")
        self.nav_aux_feature = rospy.get_param("~nav_aux_feature", "nav_aux")
        self.slam_feature = rospy.get_param("~slam_feature", "slam")

        self.model_name = rospy.get_param("~model_name", "iris_0")
        self.gt_topic = rospy.get_param("~gt_topic", "/gazebo/model_states")
        self.pose_topic = rospy.get_param("~pose_topic", "/mavros/local_position/pose")
        self.vel_topic = rospy.get_param("~vel_topic", "/mavros/local_position/velocity_local")
        self.gps_fix_topic = rospy.get_param("~gps_fix_topic", "/mavros/global_position/raw/fix")
        self.gps_vel_topic = rospy.get_param("~gps_vel_topic", "/mavros/global_position/raw/gps_vel")
        self.gps_sat_topic = rospy.get_param("~gps_sat_topic", "/mavros/global_position/raw/satellites")
        self.imu_topic = rospy.get_param("~imu_topic", "/mavros/imu/data")
        self.state_topic = rospy.get_param("~state_topic", "/mavros/state")
        self.extended_state_topic = rospy.get_param("~extended_state_topic", "/mavros/extended_state")
        self.mag_topic = rospy.get_param("~mag_topic", "/mavros/imu/mag")
        self.static_pressure_topic = rospy.get_param("~static_pressure_topic", "/mavros/imu/static_pressure")

        self.publish_rate_hz = max(float(rospy.get_param("~publish_rate_hz", 1.0)), 0.1)

        self._lock = threading.Lock()
        self.latest_gt = None
        self.latest_est = None
        self.latest_yaw = None
        self.latest_vel = None
        self.latest_gps_fix = None
        self.latest_gps_vel = None
        self.latest_gps_sat = None
        self.latest_imu = None
        self.latest_state = None
        self.latest_extended_state = None
        self.latest_mag = None
        self.latest_static_pressure = None

        self._thing_ready = False

        if self.enable_slam:
            rospy.Subscriber(self.gt_topic, ModelStates, self._cb_gt, queue_size=10)
        if self.enable_pose:
            rospy.Subscriber(self.pose_topic, PoseStamped, self._cb_pose, queue_size=50)
            rospy.Subscriber(self.vel_topic, TwistStamped, self._cb_vel, queue_size=50)
        if self.enable_gps:
            rospy.Subscriber(self.gps_fix_topic, NavSatFix, self._cb_gps_fix, queue_size=20)
            rospy.Subscriber(self.gps_vel_topic, TwistStamped, self._cb_gps_vel, queue_size=20)
            rospy.Subscriber(self.gps_sat_topic, UInt32, self._cb_gps_sat, queue_size=20)
        if self.enable_imu:
            rospy.Subscriber(self.imu_topic, Imu, self._cb_imu, queue_size=50)
        if self.enable_nav_aux:
            rospy.Subscriber(self.state_topic, State, self._cb_state, queue_size=20)
            rospy.Subscriber(self.extended_state_topic, ExtendedState, self._cb_extended_state, queue_size=20)
            rospy.Subscriber(self.mag_topic, MagneticField, self._cb_mag, queue_size=20)
            rospy.Subscriber(self.static_pressure_topic, FluidPressure, self._cb_static_pressure, queue_size=20)

        self._timer = rospy.Timer(rospy.Duration(1.0 / self.publish_rate_hz), self._on_timer)

        rospy.loginfo(
            "[ditto_bridge] started thing_id=%s rate=%.2fHz pose=%s gps=%s imu=%s nav_aux=%s slam=%s",
            self.thing_id,
            self.publish_rate_hz,
            self.enable_pose,
            self.enable_gps,
            self.enable_imu,
            self.enable_nav_aux,
            self.enable_slam,
        )

    @staticmethod
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _cb_gt(self, msg: ModelStates):
        try:
            idx = msg.name.index(self.model_name)
        except ValueError:
            return
        p = msg.pose[idx].position
        with self._lock:
            self.latest_gt = (p.x, p.y, p.z)

    def _cb_pose(self, msg: PoseStamped):
        p = msg.pose.position
        q = msg.pose.orientation
        yaw = self._yaw_from_quat(q.x, q.y, q.z, q.w)
        with self._lock:
            self.latest_est = (p.x, p.y, p.z)
            self.latest_yaw = yaw

    def _cb_vel(self, msg: TwistStamped):
        v = msg.twist.linear
        with self._lock:
            self.latest_vel = (v.x, v.y, v.z)

    def _cb_gps_fix(self, msg: NavSatFix):
        with self._lock:
            self.latest_gps_fix = (msg.latitude, msg.longitude, msg.altitude, msg.status.status)

    def _cb_gps_vel(self, msg: TwistStamped):
        v = msg.twist.linear
        with self._lock:
            self.latest_gps_vel = (v.x, v.y, v.z)

    def _cb_gps_sat(self, msg: UInt32):
        with self._lock:
            self.latest_gps_sat = float(msg.data)

    def _cb_imu(self, msg: Imu):
        q = msg.orientation
        av = msg.angular_velocity
        la = msg.linear_acceleration
        with self._lock:
            self.latest_imu = {
                "qx": q.x,
                "qy": q.y,
                "qz": q.z,
                "qw": q.w,
                "ang_vel_x": av.x,
                "ang_vel_y": av.y,
                "ang_vel_z": av.z,
                "lin_acc_x": la.x,
                "lin_acc_y": la.y,
                "lin_acc_z": la.z,
            }

    def _cb_state(self, msg: State):
        with self._lock:
            self.latest_state = {
                "connected": bool(msg.connected),
                "armed": bool(msg.armed),
                "guided": bool(msg.guided),
                "mode": msg.mode,
                "system_status": int(msg.system_status),
            }

    def _cb_extended_state(self, msg: ExtendedState):
        with self._lock:
            self.latest_extended_state = {
                "vtol_state": int(msg.vtol_state),
                "landed_state": int(msg.landed_state),
            }

    def _cb_mag(self, msg: MagneticField):
        m = msg.magnetic_field
        with self._lock:
            self.latest_mag = {
                "mag_x": m.x,
                "mag_y": m.y,
                "mag_z": m.z,
            }

    def _cb_static_pressure(self, msg: FluidPressure):
        with self._lock:
            self.latest_static_pressure = {
                "static_pressure": msg.fluid_pressure,
                "static_pressure_variance": msg.variance,
            }

    @staticmethod
    def _yaw_from_quat(x, y, z, w):
        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        return math.atan2(siny_cosp, cosy_cosp)

    @staticmethod
    def _finite_or_none(v):
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv

    def _sanitize_dict(self, data):
        if data is None:
            return None
        out = {}
        for key, value in data.items():
            sv = self._finite_or_none(value)
            if sv is not None:
                out[key] = sv
        return out if out else None

    def _auth_header(self):
        token = base64.b64encode((self.username + ":" + self.password).encode("utf-8")).decode("ascii")
        return "Basic " + token

    def _http_json(self, method, path, payload=None, expected_statuses=None):
        if expected_statuses is None:
            expected_statuses = (200, 201, 204)

        url = self.base_url + "/" + path.lstrip("/")
        body = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
        req = urllib.request.Request(url=url, data=body, method=method)
        req.add_header("Authorization", self._auth_header())
        req.add_header("Accept", "application/json")
        if payload is not None:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                status = resp.getcode()
                raw = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read()
        except urllib.error.URLError as e:
            return False, None, str(e)

        text = raw.decode("utf-8", errors="ignore") if raw else ""
        ok = status in expected_statuses
        return ok, status, text

    def _ensure_thing(self):
        if self._thing_ready:
            return True
        if not self.auto_create_thing:
            self._thing_ready = True
            return True

        thing_path = "things/" + urllib.parse.quote(self.thing_id, safe="")
        ok, status, text = self._http_json("GET", thing_path, expected_statuses=(200, 404))
        if not ok:
            rospy.logwarn_throttle(5.0, "[ditto_bridge] GET thing failed: status=%s body=%s", str(status), text)
            return False
        if status == 200:
            self._thing_ready = True
            return True

        payload = {
            "attributes": {
                "source": "laea_ditto_bridge/ditto_bridge.py",
                "model_name": self.model_name,
            }
        }
        if self.policy_id:
            payload["policyId"] = self.policy_id

        ok, status, text = self._http_json("PUT", thing_path, payload=payload, expected_statuses=(201, 204))
        if ok:
            self._thing_ready = True
            rospy.loginfo("[ditto_bridge] created thing: %s", self.thing_id)
            return True

        rospy.logerr_throttle(5.0, "[ditto_bridge] unable to create thing '%s': status=%s body=%s", self.thing_id, str(status), text)
        return False

    def _put_feature_properties(self, feature_name, props):
        if not props:
            return True

        thing_quoted = urllib.parse.quote(self.thing_id, safe="")
        feature_quoted = urllib.parse.quote(feature_name, safe="")
        path = f"things/{thing_quoted}/features/{feature_quoted}/properties"
        ok, status, text = self._http_json("PUT", path, payload=props, expected_statuses=(201, 204))
        if ok:
            return True

        if status == 404 and "feature.notfound" in (text or ""):
            create_path = f"things/{thing_quoted}/features/{feature_quoted}"
            create_payload = {"properties": props}
            c_ok, c_status, c_text = self._http_json("PUT", create_path, payload=create_payload, expected_statuses=(201, 204))
            if c_ok:
                rospy.loginfo_throttle(5.0, "[ditto_bridge] created missing feature '%s' on thing '%s'", feature_name, self.thing_id)
                return True
            rospy.logwarn_throttle(5.0, "[ditto_bridge] create feature '%s' failed: status=%s body=%s", feature_name, str(c_status), c_text)
            return False

        rospy.logwarn_throttle(5.0, "[ditto_bridge] update feature '%s' failed: status=%s body=%s", feature_name, str(status), text)
        return False

    def _build_payloads(self):
        with self._lock:
            gt = self.latest_gt
            est = self.latest_est
            yaw = self.latest_yaw
            vel = self.latest_vel
            gps_fix = self.latest_gps_fix
            gps_vel = self.latest_gps_vel
            gps_sat = self.latest_gps_sat
            imu = dict(self.latest_imu) if self.latest_imu is not None else None
            state = dict(self.latest_state) if self.latest_state is not None else None
            ext = dict(self.latest_extended_state) if self.latest_extended_state is not None else None
            mag = dict(self.latest_mag) if self.latest_mag is not None else None
            pressure = dict(self.latest_static_pressure) if self.latest_static_pressure is not None else None

        now_t = self._finite_or_none(rospy.get_time())
        payloads = {}

        if self.enable_pose and est is not None:
            vel_x = vel[0] if vel is not None else None
            vel_y = vel[1] if vel is not None else None
            vel_z = vel[2] if vel is not None else None
            pose_props = self._sanitize_dict({
                "t": now_t,
                "pos_x": est[0],
                "pos_y": est[1],
                "pos_z": est[2],
                "vel_x": vel_x,
                "vel_y": vel_y,
                "vel_z": vel_z,
                "yaw": yaw,
            })
            if pose_props is not None:
                payloads[self.pose_feature] = pose_props

        if self.enable_gps and (gps_fix is not None or gps_vel is not None or gps_sat is not None):
            lat, lon, alt, fix = gps_fix if gps_fix is not None else (None, None, None, None)
            gvx, gvy, gvz = gps_vel if gps_vel is not None else (None, None, None)
            gps_props = self._sanitize_dict({
                "t": now_t,
                "gps_lat": lat,
                "gps_lon": lon,
                "gps_alt": alt,
                "gps_vx": gvx,
                "gps_vy": gvy,
                "gps_vz": gvz,
                "gps_fix": fix,
                "gps_sat": gps_sat,
            })
            if gps_props is not None:
                payloads[self.gps_feature] = gps_props

        if self.enable_imu and imu is not None:
            imu_props = self._sanitize_dict({"t": now_t, **imu})
            if imu_props is not None:
                payloads[self.imu_feature] = imu_props

        if self.enable_nav_aux and any(item is not None for item in (state, ext, mag, pressure)):
            nav_aux_raw = {"t": now_t}
            if state is not None:
                nav_aux_raw.update({
                    "state_connected": state["connected"],
                    "state_armed": state["armed"],
                    "state_guided": state["guided"],
                    "state_mode": state["mode"],
                    "state_system_status": state["system_status"],
                })
            if ext is not None:
                nav_aux_raw.update({
                    "vtol_state": ext["vtol_state"],
                    "landed_state": ext["landed_state"],
                })
            if mag is not None:
                nav_aux_raw.update(mag)
            if pressure is not None:
                nav_aux_raw.update(pressure)
            nav_aux_props = self._sanitize_dict(nav_aux_raw)
            if nav_aux_props is not None:
                payloads[self.nav_aux_feature] = nav_aux_props

        if self.enable_slam and gt is not None and est is not None:
            dx = gt[0] - est[0]
            dy = gt[1] - est[1]
            dz = gt[2] - est[2]
            e_pos = math.sqrt(dx * dx + dy * dy + dz * dz)
            slam_props = self._sanitize_dict({
                "t": now_t,
                "px_gt": gt[0],
                "py_gt": gt[1],
                "pz_gt": gt[2],
                "px_est": est[0],
                "py_est": est[1],
                "pz_est": est[2],
                "e_pos": e_pos,
            })
            if slam_props is not None:
                payloads[self.slam_feature] = slam_props

        return payloads

    def _on_timer(self, _event):
        if not self._ensure_thing():
            return

        payloads = self._build_payloads()
        if self.enable_pose and self.pose_feature not in payloads:
            rospy.logwarn_throttle(5.0, "[ditto_bridge] waiting for local pose topic: %s", self.pose_topic)
        if self.enable_imu and self.imu_feature not in payloads:
            rospy.logwarn_throttle(5.0, "[ditto_bridge] waiting for imu topic: %s", self.imu_topic)
        if self.enable_nav_aux and self.nav_aux_feature not in payloads:
            rospy.logwarn_throttle(5.0, "[ditto_bridge] waiting for nav aux topics")

        any_sent = False
        for feature_name, props in payloads.items():
            any_sent = self._put_feature_properties(feature_name, props) or any_sent

        if any_sent:
            rospy.loginfo_throttle(10.0, "[ditto_bridge] synced thing=%s features=%s", self.thing_id, ",".join(sorted(payloads.keys())))


if __name__ == "__main__":
    try:
        DittoBridge()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
