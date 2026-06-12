#!/usr/bin/env python3
"""
LAEA AIoTtalk_plus RTP bridge.

Replaces:
  - roslaunch rtp_gazebo rtp_sender.launch   use_iottalk:=true use_sip:=false
  - roslaunch rtp_gazebo rtp_receiver.launch use_iottalk:=true use_sip:=false
  - python3 iottalk/sip.py

Flow:
  1. Register SIP_SDP device on IoTtalk (same as iottalk/sip.py).
  2. Push SDP offer for image + raw ROS message streams through IoTtalk and wait for OK.
  3. After SDP negotiation, open pybind11 RTPSession:
       RGB   : /camera/depth/rgb_image_raw → H264   → /rtp/depth/rgb_image_raw
       Depth : /camera/depth/image_raw     → Zdepth → /rtp/depth/image_raw
       Other ROS messages use raw_bytes RTP streams and ROS serialization.
"""

import os
import sys
import json
import re
import socket
import threading
import time
import io
import math

import numpy as np

# ── ROS ──────────────────────────────────────────────────────────────────────
import rospy
from geometry_msgs.msg import PoseStamped, TwistStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, Image, Imu, NavSatFix, PointCloud2
from std_msgs.msg import UInt32
from cv_bridge import CvBridge

# ── pybind11 RTPSession ───────────────────────────────────────────────────────
_LAEA_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_LAEA_DIR,
    "AIoTtalk_plus/AIoTtalk_plus_Lib/RTP/build"))
from MyTool_pybind11 import RTPSession, Data_Wrapper, CodecParam  # noqa: E402

# ── IoTtalk DAN ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(_LAEA_DIR, "iottalk"))
import DAN  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
IOTTALK_SERVER = "http://140.114.77.93:9999"

# SDP media is descriptive only for SIP_SDP. rtp_media_type selects the actual
# pybind codec/media implementation.
STREAMS = [
    {
        "key": "rgb",
        "stream_id": 0,
        "stream_name": "rgb_stream",
        "sdp_media": "video",
        "transport": "image",
        "rtp_media_type": "video",
        "codec": "H264",
        "codec_params": {"resolution": "640*480"},
        "payload_type": 96,
        "sender_port": 10000,
        "receiver_port": 11000,
        "input_topic": "/camera/depth/rgb_image_raw",
        "output_topic": "/rtp/depth/rgb_image_raw",
        "input_encoding": "bgr8",
        "output_encoding": "bgr8",
        "output_frame_id": "depth_camera_link",
        "msg_type": Image,
    },
    {
        "key": "depth",
        "stream_id": 1,
        "stream_name": "depth_stream",
        "sdp_media": "video",
        "transport": "depth_image",
        "rtp_media_type": "depth_image",
        "codec": "Zdepth",
        "codec_params": {"resolution": "640*480"},
        "payload_type": 97,
        "sender_port": 12000,
        "receiver_port": 13000,
        "input_topic": "/camera/depth/image_raw",
        "output_topic": "/rtp/depth/image_raw",
        "input_encoding": "passthrough",
        "output_encoding": "32FC1",
        "output_frame_id": "depth_camera_link",
        "msg_type": Image,
    },
    {
        "key": "pointcloud_depth",
        "stream_id": 2,
        "stream_name": "pointcloud_depth_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 98,
        "sender_port": 14000,
        "receiver_port": 15000,
        "input_topic": "/camera/depth/color/points",
        "output_topic": "/rtp/pointcloud/depth",
        "msg_type": PointCloud2,
        "max_hz": 2.0,
        "max_raw_bytes": 262144,
        "downsample_pointcloud": True,
    },
    {
        "key": "camera_info",
        "stream_id": 3,
        "stream_name": "camera_info_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 99,
        "sender_port": 16000,
        "receiver_port": 17000,
        "input_topic": "/camera/depth/camera_info",
        "output_topic": "/rtp/depth/camera_info",
        "msg_type": CameraInfo,
        "max_hz": 5.0,
        "max_raw_bytes": 65536,
    },
    {
        "key": "imu",
        "stream_id": 4,
        "stream_name": "imu_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 100,
        "sender_port": 18000,
        "receiver_port": 19000,
        "input_topic": "/mavros/imu/data",
        "output_topic": "/rtp/imu/data",
        "msg_type": Imu,
        "max_hz": 50.0,
        "max_raw_bytes": 65536,
    },
    {
        "key": "gps_fix",
        "stream_id": 5,
        "stream_name": "gps_fix_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 101,
        "sender_port": 20000,
        "receiver_port": 21000,
        "input_topic": "/mavros/global_position/raw/fix",
        "output_topic": "/rtp/gps/fix",
        "msg_type": NavSatFix,
        "max_hz": 10.0,
        "max_raw_bytes": 65536,
    },
    {
        "key": "gps_vel",
        "stream_id": 6,
        "stream_name": "gps_vel_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 102,
        "sender_port": 22000,
        "receiver_port": 23000,
        "input_topic": "/mavros/global_position/raw/gps_vel",
        "output_topic": "/rtp/gps/vel",
        "msg_type": TwistStamped,
        "max_hz": 10.0,
        "max_raw_bytes": 65536,
    },
    {
        "key": "gps_satellites",
        "stream_id": 7,
        "stream_name": "gps_satellites_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 103,
        "sender_port": 24000,
        "receiver_port": 25000,
        "input_topic": "/mavros/global_position/raw/satellites",
        "output_topic": "/rtp/gps/satellites",
        "msg_type": UInt32,
        "max_hz": 10.0,
        "max_raw_bytes": 65536,
    },
    {
        "key": "odom",
        "stream_id": 8,
        "stream_name": "odom_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 104,
        "sender_port": 26000,
        "receiver_port": 27000,
        "input_topic": "/mavros/local_position/odom",
        "output_topic": "/rtp/local_odom",
        "msg_type": Odometry,
        "max_hz": 30.0,
        "max_raw_bytes": 65536,
    },
    {
        "key": "pose",
        "stream_id": 9,
        "stream_name": "pose_stream",
        "sdp_media": "application",
        "transport": "raw_ros",
        "rtp_media_type": "raw_bytes",
        "codec": "raw_bytes",
        "codec_params": {},
        "payload_type": 105,
        "sender_port": 28000,
        "receiver_port": 29000,
        "input_topic": "/mavros/camera/pose",
        "output_topic": "/rtp/pose",
        "msg_type": PoseStamped,
        "max_hz": 30.0,
        "max_raw_bytes": 65536,
    },
]

STREAMS_BY_ID = {stream["stream_id"]: stream for stream in STREAMS}
STREAMS_BY_KEY = {stream["key"]: stream for stream in STREAMS}
SDP_LINE_RE = re.compile(r"^a=(\d+)\s+(\d+)\s+(\w+)\s+(\w+)\s+(\d+)\s+(\w+)\s*$")
# ─────────────────────────────────────────────────────────────────────────────

_bridge       = CvBridge()
_send_session = None
_recv_session = None
_sessions_ready = threading.Event()
_send_lock = threading.Lock()
_last_send_time = {}
_image_seq = {"rgb": 0, "depth": 0}


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def _make_sdp(direction: str, port_field: str) -> str:
    lines = []
    for stream in STREAMS:
        lines.append(
            "a={stream_id} {port} {name} {media} {payload} {direction}".format(
                stream_id=stream["stream_id"],
                port=stream[port_field],
                name=stream["stream_name"],
                media=stream["sdp_media"],
                payload=stream["payload_type"],
                direction=direction,
            )
        )
    return "\n".join(lines) + "\n"


def _parse_sdp_ports(sdp_data: str, expected_direction: str) -> dict:
    ports = {}
    for raw_line in sdp_data.strip().splitlines():
        match = SDP_LINE_RE.match(raw_line.strip())
        if not match:
            rospy.logwarn("[laea_aiottalk_rtp] Ignoring unsupported SDP line: %s", raw_line)
            continue
        stream_id = int(match.group(1))
        port = int(match.group(2))
        payload_type = int(match.group(5))
        direction = match.group(6)
        stream = STREAMS_BY_ID.get(stream_id)
        if stream is None:
            rospy.logwarn("[laea_aiottalk_rtp] Ignoring unknown SDP stream id=%d", stream_id)
            continue
        if payload_type != stream["payload_type"]:
            rospy.logwarn(
                "[laea_aiottalk_rtp] SDP payload mismatch for %s: got=%d expected=%d",
                stream["key"], payload_type, stream["payload_type"],
            )
            continue
        if direction != expected_direction:
            rospy.logwarn(
                "[laea_aiottalk_rtp] SDP direction mismatch for %s: got=%s expected=%s",
                stream["key"], direction, expected_direction,
            )
            continue
        ports[stream_id] = port
    return ports


def _depth_to_uint16_mm(img: np.ndarray) -> np.ndarray:
    depth_m = np.asarray(img, dtype=np.float32)
    with np.errstate(invalid="ignore", over="ignore"):
        depth_mm = depth_m * 1000.0
        valid = np.isfinite(depth_mm) & (depth_mm >= 0.0) & (depth_mm <= 65535.0)

    out = np.zeros(depth_mm.shape, dtype=np.uint16)
    out[valid] = depth_mm[valid].astype(np.uint16)
    return np.ascontiguousarray(out)


def _send_stream(stream: dict, img: np.ndarray):
    if not _sessions_ready.is_set():
        return
    data = np.ascontiguousarray(img)
    try:
        with _send_lock:
            _send_session.send_data(stream["stream_id"], Data_Wrapper(data), True)
    except Exception as exc:
        rospy.logerr("[laea_aiottalk_rtp] %s send error: %s", stream["key"], exc)


def _serialize_ros_msg(msg) -> bytes:
    buff = io.BytesIO()
    msg.serialize(buff)
    return buff.getvalue()


def _logwarn_throttle(period: float, msg: str, *args):
    if rospy.core.is_initialized():
        rospy.logwarn_throttle(period, msg, *args)
    else:
        print(msg % args if args else msg)


def _should_send(stream: dict) -> bool:
    max_hz = stream.get("max_hz")
    if not max_hz:
        return True

    now = time.monotonic()
    last = _last_send_time.get(stream["key"])
    if last is not None and now - last < 1.0 / max_hz:
        return False
    _last_send_time[stream["key"]] = now
    return True


def _downsample_pointcloud2(msg: PointCloud2, max_raw_bytes: int) -> PointCloud2:
    point_step = int(msg.point_step or 0)
    max_data_bytes = max(1, max_raw_bytes - 4096)
    if point_step <= 0 or len(msg.data) <= max_data_bytes:
        return msg

    total_points = len(msg.data) // point_step
    max_points = max(1, max_data_bytes // point_step)
    if total_points <= max_points:
        return msg

    stride = max(1, int(math.ceil(total_points / max_points)))
    data = bytes(msg.data)
    sampled = bytearray()
    kept = 0
    for point_index in range(0, total_points, stride):
        if kept >= max_points:
            break
        start = point_index * point_step
        sampled.extend(data[start:start + point_step])
        kept += 1

    out = PointCloud2()
    out.header = msg.header
    out.height = 1
    out.width = kept
    out.fields = msg.fields
    out.is_bigendian = msg.is_bigendian
    out.point_step = point_step
    out.row_step = point_step * kept
    out.data = bytes(sampled)
    out.is_dense = msg.is_dense
    _logwarn_throttle(
        10.0,
        "[laea_aiottalk_rtp] Downsampled %s PointCloud2 from %d to %d points for raw RTP",
        "depth", total_points, kept,
    )
    return out


def _prepare_raw_ros_msg(stream: dict, msg):
    if stream.get("downsample_pointcloud") and isinstance(msg, PointCloud2):
        return _downsample_pointcloud2(msg, stream.get("max_raw_bytes", 262144))
    return msg


def _send_raw_ros(stream: dict, msg):
    if not _sessions_ready.is_set():
        return
    if not _should_send(stream):
        return
    try:
        raw = _serialize_ros_msg(_prepare_raw_ros_msg(stream, msg))
        max_raw_bytes = stream.get("max_raw_bytes")
        if max_raw_bytes and len(raw) > max_raw_bytes:
            _logwarn_throttle(
                10.0,
                "[laea_aiottalk_rtp] Skipping %s raw frame: %d bytes exceeds limit %d",
                stream["key"], len(raw), max_raw_bytes,
            )
            return
        with _send_lock:
            ret = _send_session.send_data(stream["stream_id"], Data_Wrapper(raw), False)
        if ret != 0:
            rospy.logwarn("[laea_aiottalk_rtp] %s raw send returned %s", stream["key"], ret)
    except Exception as exc:
        rospy.logerr("[laea_aiottalk_rtp] %s raw send error: %s", stream["key"], exc)


def _raw_ros_callback_factory(stream: dict):
    def _callback(msg):
        _send_raw_ros(stream, msg)

    return _callback


def _ensure_ok(action: str, ret: int):
    if ret != 0:
        raise RuntimeError(f"{action} failed with code {ret}")


# ── Sender callbacks: ROS Image → pybind11 ───────────────────────────────────
def _rgb_callback(msg: Image):
    try:
        img = _bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        _send_stream(STREAMS_BY_KEY["rgb"], img)
    except Exception as exc:
        rospy.logerr("[laea_aiottalk_rtp] rgb callback error: %s", exc)


def _depth_callback(msg: Image):
    try:
        img = _bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        _send_stream(STREAMS_BY_KEY["depth"], _depth_to_uint16_mm(img))
    except Exception as exc:
        rospy.logerr("[laea_aiottalk_rtp] depth callback error: %s", exc)


# ── Receiver: pybind11 → ROS Image ───────────────────────────────────────────
def _recv_loop(stream: dict, pub: rospy.Publisher):
    while not rospy.is_shutdown():
        if not _sessions_ready.is_set():
            time.sleep(0.05)
            continue
        try:
            decode = stream["transport"] != "raw_ros"
            frames = _recv_session.get_data(stream["stream_id"], decode)
            for f in frames:
                if stream["transport"] == "raw_ros":
                    raw = f.convert_raw_bytes()
                    msg = stream["msg_type"]()
                    msg.deserialize(raw)
                    pub.publish(msg)
                    continue

                mat = f.convert_cv_mat()
                if mat is None:
                    continue
                if stream["key"] == "depth":
                    out = np.ascontiguousarray(mat.astype(np.float32))
                else:
                    out = np.ascontiguousarray(mat.astype(np.uint8))
                msg = _bridge.cv2_to_imgmsg(out, encoding=stream["output_encoding"])
                msg.header.stamp = rospy.Time.now()
                msg.header.frame_id = stream["output_frame_id"]
                msg.header.seq = _image_seq[stream["key"]]
                _image_seq[stream["key"]] += 1
                pub.publish(msg)
        except Exception as exc:
            rospy.logerr("[laea_aiottalk_rtp] %s recv error: %s", stream["key"], exc)


# ── IoTtalk SDP negotiation ───────────────────────────────────────────────────
def _sdp_dialog():
    """Mirror of iottalk/sip.py: push invite, wait for OK, then start RTP."""
    global _send_session, _recv_session

    local_ip = _local_ip()

    # SDP format: "a=<stream_id> <port> <name> <media> <payload_type> <dir>"
    sdp_offer = _make_sdp("sendonly", "sender_port")
    sdp_answer = _make_sdp("recvonly", "receiver_port")

    # ── Sender thread: push invite, wait for OK ──────────────────────────────
    def sender_thread():
        packet = {
            "type": "Invite",
            "source": "CD8600D38000",
            "target": "CD8600D38001",
            "sdp_data": sdp_offer,
        }
        while True:
            result = DAN.push("SIP_Sender", json.dumps(packet))
            if result is not None:
                rospy.loginfo("[laea_aiottalk_rtp] Invite sent via IoTtalk")
                break
            rospy.logwarn("[laea_aiottalk_rtp] Invite failed, retrying…")
            time.sleep(2)

        # Wait for OK with remote recv port
        while True:
            result = DAN.pull("SIP_Receiver")
            if result is not None:
                pkt = json.loads(result[0])
                if pkt.get("type") == "OK":
                    remote_recv_ports = _parse_sdp_ports(pkt["sdp_data"], "recvonly")
                    missing = [
                        s["stream_name"]
                        for s in STREAMS
                        if s["stream_id"] not in remote_recv_ports
                    ]
                    if missing:
                        rospy.logwarn(
                            "[laea_aiottalk_rtp] SDP answer missing streams: %s",
                            ", ".join(missing),
                        )
                        time.sleep(0.5)
                        continue
                    rospy.loginfo("[laea_aiottalk_rtp] Got SDP answer for %d streams", len(remote_recv_ports))
                    try:
                        _start_rtp(local_ip, remote_recv_ports)
                    except Exception as exc:
                        rospy.logerr("[laea_aiottalk_rtp] RTP startup failed: %s", exc)
                        return
                    return
            time.sleep(0.5)

    # ── Receiver thread: wait for invite, push OK ────────────────────────────
    def receiver_thread():
        while True:
            result = DAN.pull("SIP_Sender")
            if result is not None:
                pkt = json.loads(result[0])
                if pkt.get("type") == "Invite":
                    rospy.loginfo("[laea_aiottalk_rtp] Received SDP invite")
                    ok_pkt = {
                        "type": "OK",
                        "source": "CD8600D38001",
                        "target": "CD8600D38000",
                        "sdp_data": sdp_answer,
                    }
                    while DAN.push("SIP_Receiver", json.dumps(ok_pkt)) is None:
                        time.sleep(1)
                    rospy.loginfo("[laea_aiottalk_rtp] SDP answer (OK) sent")
                    return
            time.sleep(0.5)

    t_sender   = threading.Thread(target=sender_thread,   daemon=True)
    t_receiver = threading.Thread(target=receiver_thread, daemon=True)
    t_sender.start()
    t_receiver.start()
    t_sender.join()
    t_receiver.join()


def _start_rtp(local_ip: str, remote_recv_ports: dict):
    """Create pybind11 RTPSession sender + receiver and signal readiness."""
    global _send_session, _recv_session

    _send_session = RTPSession()
    _ensure_ok("sender create_session", _send_session.create_session(local_ip, local_ip))
    _recv_session = RTPSession()
    _ensure_ok("receiver create_session", _recv_session.create_session(local_ip, local_ip))

    for stream in STREAMS:
        codec = CodecParam(
            stream["payload_type"],
            stream["codec"],
            stream["codec_params"],
        )
        remote_recv_port = remote_recv_ports[stream["stream_id"]]

        _ensure_ok(
            f"{stream['key']} sender create_stream",
            _send_session.create_stream(
                stream["stream_id"],
                stream["sender_port"],
                remote_recv_port,
                stream["stream_name"],
                "sendonly",
                stream["rtp_media_type"],
                [codec],
            ),
        )
        rospy.loginfo(
            "[laea_aiottalk_rtp] %s sender ready: %s:%d -> %s:%d",
            stream["key"], local_ip, stream["sender_port"], local_ip, remote_recv_port,
        )

        _ensure_ok(
            f"{stream['key']} receiver create_stream",
            _recv_session.create_stream(
                stream["stream_id"],
                stream["receiver_port"],
                stream["sender_port"],
                stream["stream_name"],
                "recvonly",
                stream["rtp_media_type"],
                [codec],
            ),
        )
        rospy.loginfo(
            "[laea_aiottalk_rtp] %s receiver ready on port %d",
            stream["key"], stream["receiver_port"],
        )

    _sessions_ready.set()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    rospy.init_node("laea_aiottalk_rtp")

    # IoTtalk registration (same device model as iottalk/sip.py)
    DAN.profile["dm_name"] = "SIP_SDP"
    DAN.profile["df_list"] = ["SIP_Sender", "SIP_Receiver"]
    DAN.device_registration_with_retry(IOTTALK_SERVER, None)
    rospy.loginfo("[laea_aiottalk_rtp] IoTtalk registered as SIP_SDP")

    publishers = {
        stream["key"]: rospy.Publisher(stream["output_topic"], stream["msg_type"], queue_size=5)
        for stream in STREAMS
    }

    # SDP negotiation in background thread
    t_neg = threading.Thread(target=_sdp_dialog, daemon=True)
    t_neg.start()

    for stream in STREAMS:
        t_recv = threading.Thread(
            target=_recv_loop,
            args=(stream, publishers[stream["key"]]),
            daemon=True,
        )
        t_recv.start()

    # Subscribe to drone sensor streams.
    for stream in STREAMS:
        if stream["key"] == "rgb":
            callback = _rgb_callback
        elif stream["key"] == "depth":
            callback = _depth_callback
        else:
            callback = _raw_ros_callback_factory(stream)
        rospy.Subscriber(stream["input_topic"], stream["msg_type"], callback, queue_size=5)

    rospy.loginfo(
        "[laea_aiottalk_rtp] Waiting for SDP negotiation… "
        "(%d streams: %s)",
        len(STREAMS),
        ", ".join(f"{stream['input_topic']}->{stream['output_topic']}" for stream in STREAMS),
    )
    rospy.spin()


if __name__ == "__main__":
    main()
