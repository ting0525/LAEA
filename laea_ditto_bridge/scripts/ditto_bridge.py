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
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import UInt32


class DittoBridge:
    def __init__(self):
        rospy.init_node("ditto_bridge", anonymous=False)

        # Ditto connection
        self.base_url = rospy.get_param("~base_url", "http://localhost:8080/api/2").rstrip("/")
        self.username = rospy.get_param("~username", "ditto")
        self.password = rospy.get_param("~password", "ditto")
        self.request_timeout_s = float(rospy.get_param("~request_timeout_s", 2.0))

        # Thing configuration
        self.thing_id = rospy.get_param("~thing_id", "laea:iris_0")
        self.policy_id = rospy.get_param("~policy_id", "")
        self.auto_create_thing = bool(rospy.get_param("~auto_create_thing", True))

        # Feature names in Ditto
        self.pose_feature = rospy.get_param("~pose_feature", "pose_local")
        self.gps_feature = rospy.get_param("~gps_feature", "gps")
        self.slam_feature = rospy.get_param("~slam_feature", "slam")

        # ROS topics
        self.model_name = rospy.get_param("~model_name", "iris_0")
        self.gt_topic = rospy.get_param("~gt_topic", "/gazebo/model_states")
        self.pose_topic = rospy.get_param("~pose_topic", "/mavros/local_position/pose")
        self.vel_topic = rospy.get_param("~vel_topic", "/mavros/local_position/velocity_local")
        self.gps_fix_topic = rospy.get_param("~gps_fix_topic", "/mavros/global_position/raw/fix")
        self.gps_vel_topic = rospy.get_param("~gps_vel_topic", "/mavros/global_position/raw/gps_vel")
        self.gps_sat_topic = rospy.get_param("~gps_sat_topic", "/mavros/global_position/raw/satellites")

        self.publish_rate_hz = float(rospy.get_param("~publish_rate_hz", 1.0))
        self.publish_rate_hz = max(self.publish_rate_hz, 0.1)

        # Latest cached sensor values
        self._lock = threading.Lock()
        self.latest_gt = None
        self.latest_est = None
        self.latest_yaw = None
        self.latest_vel = None
        self.latest_gps_fix = None
        self.latest_gps_vel = None
        self.latest_gps_sat = None

        self._thing_ready = False

        rospy.Subscriber(self.gt_topic, ModelStates, self._cb_gt, queue_size=10)
        rospy.Subscriber(self.pose_topic, PoseStamped, self._cb_pose, queue_size=50)
        rospy.Subscriber(self.vel_topic, TwistStamped, self._cb_vel, queue_size=50)
        rospy.Subscriber(self.gps_fix_topic, NavSatFix, self._cb_gps_fix, queue_size=20)
        rospy.Subscriber(self.gps_vel_topic, TwistStamped, self._cb_gps_vel, queue_size=20)
        rospy.Subscriber(self.gps_sat_topic, UInt32, self._cb_gps_sat, queue_size=20)

        self._timer = rospy.Timer(rospy.Duration(1.0 / self.publish_rate_hz), self._on_timer)

        rospy.loginfo(
            "[ditto_bridge] started. base_url=%s thing_id=%s publish_rate=%.2fHz",
            self.base_url,
            self.thing_id,
            self.publish_rate_hz,
        )

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

    @staticmethod
    def _yaw_from_quat(x, y, z, w):
        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        return math.atan2(siny_cosp, cosy_cosp)

    @staticmethod
    def _finite_or_none(v):
        if v is None:
            return None
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv

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

        rospy.logerr_throttle(
            5.0,
            "[ditto_bridge] unable to create thing '%s': status=%s body=%s",
            self.thing_id,
            str(status),
            text,
        )
        return False

    def _put_feature_properties(self, feature_name, props):
        if not props:
            return True

        thing_quoted = urllib.parse.quote(self.thing_id, safe="")
        feature_quoted = urllib.parse.quote(feature_name, safe="")
        path = "things/{}/features/{}/properties".format(thing_quoted, feature_quoted)
        ok, status, text = self._http_json("PUT", path, payload=props, expected_statuses=(201, 204))
        if ok:
            return True

        # If feature does not exist yet, create it with full payload once.
        if status == 404 and "feature.notfound" in (text or ""):
            create_path = "things/{}/features/{}".format(thing_quoted, feature_quoted)
            create_payload = {"properties": props}
            c_ok, c_status, c_text = self._http_json(
                "PUT",
                create_path,
                payload=create_payload,
                expected_statuses=(201, 204),
            )
            if c_ok:
                rospy.loginfo_throttle(
                    5.0,
                    "[ditto_bridge] created missing feature '%s' on thing '%s'",
                    feature_name,
                    self.thing_id,
                )
                return True

            rospy.logwarn_throttle(
                5.0,
                "[ditto_bridge] create feature '%s' failed: status=%s body=%s",
                feature_name,
                str(c_status),
                c_text,
            )
            return False

        rospy.logwarn_throttle(
            5.0,
            "[ditto_bridge] update feature '%s' failed: status=%s body=%s",
            feature_name,
            str(status),
            text,
        )
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

        now_t = self._finite_or_none(rospy.get_time())

        pose_props = None
        if est is not None:
            vel_x = vel[0] if vel is not None else None
            vel_y = vel[1] if vel is not None else None
            vel_z = vel[2] if vel is not None else None
            pose_props = {
                "t": now_t,
                "pos_x": self._finite_or_none(est[0]),
                "pos_y": self._finite_or_none(est[1]),
                "pos_z": self._finite_or_none(est[2]),
                "vel_x": self._finite_or_none(vel_x),
                "vel_y": self._finite_or_none(vel_y),
                "vel_z": self._finite_or_none(vel_z),
                "yaw": self._finite_or_none(yaw),
            }

        gps_props = None
        if gps_fix is not None or gps_vel is not None or gps_sat is not None:
            lat, lon, alt, fix = (gps_fix if gps_fix is not None else (None, None, None, None))
            gvx, gvy, gvz = (gps_vel if gps_vel is not None else (None, None, None))
            gps_props = {
                "t": now_t,
                "gps_lat": self._finite_or_none(lat),
                "gps_lon": self._finite_or_none(lon),
                "gps_alt": self._finite_or_none(alt),
                "gps_vx": self._finite_or_none(gvx),
                "gps_vy": self._finite_or_none(gvy),
                "gps_vz": self._finite_or_none(gvz),
                "gps_fix": self._finite_or_none(fix),
                "gps_sat": self._finite_or_none(gps_sat),
            }

        slam_props = None
        if gt is not None and est is not None:
            dx = gt[0] - est[0]
            dy = gt[1] - est[1]
            dz = gt[2] - est[2]
            e_pos = math.sqrt(dx * dx + dy * dy + dz * dz)
            slam_props = {
                "t": now_t,
                "px_gt": self._finite_or_none(gt[0]),
                "py_gt": self._finite_or_none(gt[1]),
                "pz_gt": self._finite_or_none(gt[2]),
                "px_est": self._finite_or_none(est[0]),
                "py_est": self._finite_or_none(est[1]),
                "pz_est": self._finite_or_none(est[2]),
                "e_pos": self._finite_or_none(e_pos),
            }

        return pose_props, gps_props, slam_props

    def _on_timer(self, _event):
        if not self._ensure_thing():
            return

        pose_props, gps_props, slam_props = self._build_payloads()
        if pose_props is None:
            rospy.logwarn_throttle(5.0, "[ditto_bridge] waiting for local pose topic: %s", self.pose_topic)

        any_sent = False
        if pose_props is not None:
            any_sent = self._put_feature_properties(self.pose_feature, pose_props) or any_sent
        if gps_props is not None:
            any_sent = self._put_feature_properties(self.gps_feature, gps_props) or any_sent
        if slam_props is not None:
            any_sent = self._put_feature_properties(self.slam_feature, slam_props) or any_sent

        if any_sent:
            rospy.loginfo_throttle(10.0, "[ditto_bridge] synced thing=%s", self.thing_id)


if __name__ == "__main__":
    try:
        DittoBridge()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
