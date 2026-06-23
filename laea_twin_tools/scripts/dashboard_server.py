#!/usr/bin/env python3

import atexit
import csv
import json
import os
import re
import signal
import site
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# ROS environments often prepend Ubuntu's Python packages. Prefer the user's
# site packages when present so Flask and its Click dependency stay compatible.
USER_SITE = site.getusersitepackages()
if USER_SITE in sys.path:
    sys.path.remove(USER_SITE)
if os.path.isdir(USER_SITE):
    sys.path.insert(0, USER_SITE)

import rosgraph
import rosnode
import rospy
import yaml
from flask import Flask, jsonify, request, send_from_directory
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import State
from std_msgs.msg import String, UInt32

from laea_twin_tools.msg import (
    AttackCommand,
    AttackStatus,
    MissionState,
    SupervisorCommand,
)


from dashboard.common import *  # noqa: F401,F403
from dashboard.procutil import *  # noqa: F401,F403
from dashboard.roscleanup import *  # noqa: F401,F403
from dashboard.catalogs import *  # noqa: F401,F403
from dashboard.experiment import ExperimentProcess
from dashboard.monitor import RosMonitor


rospy.init_node("laea_dashboard", anonymous=True, disable_signals=True)
purged_dashboard_nodes, dashboard_cleanup_errors = purge_stale_dashboard_ros_nodes(
    rospy.get_name()
)
if purged_dashboard_nodes:
    rospy.loginfo(
        "[laea_dashboard] removed stale ROS registrations: %s",
        ", ".join(purged_dashboard_nodes),
    )
for cleanup_error in dashboard_cleanup_errors:
    rospy.logwarn("[laea_dashboard] %s", cleanup_error)


def shutdown_dashboard(reason="dashboard server exiting"):
    if not rospy.is_shutdown():
        rospy.signal_shutdown(reason)


def handle_shutdown_signal(signum, _frame):
    shutdown_dashboard(f"received signal {signum}")
    raise SystemExit(0)


atexit.register(shutdown_dashboard)
signal.signal(signal.SIGINT, handle_shutdown_signal)
signal.signal(signal.SIGTERM, handle_shutdown_signal)

monitor = RosMonitor()
experiment = ExperimentProcess(monitor)
profiles = load_profiles()
app = Flask(__name__, static_folder=None)


@app.get("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


@app.get("/assets/<path:name>")
def assets(name):
    return send_from_directory(str(WEB_DIR), name)


@app.get("/api/state")
def api_state():
    process = experiment.snapshot()
    online_nodes = ros_nodes_online()
    components = {
        key: {
            "node": node,
            "online": node in online_nodes,
        }
        for key, node in COMPONENT_NODES.items()
    }
    return jsonify(
        {
            "ros_master_online": ros_master_online(),
            "process": process,
            "telemetry": monitor.snapshot(),
            "recent_runs": read_recent_runs(process["dataset_dir"]),
            "profiles": profiles,
            "profile_catalog": profile_catalog(),
            "world_catalog": world_catalog(),
            "components": components,
            "capabilities": runtime_capabilities(process, components),
            "server_time": time.time(),
        }
    )


@app.get("/api/logs")
def api_logs():
    process = experiment.snapshot()
    return jsonify({"text": tail_text(process["log_path"], request.args.get("lines", 160))})


@app.post("/api/experiment/start")
def api_experiment_start():
    try:
        config = normalize_start_config(request.get_json(silent=True), profiles)
        return jsonify({"ok": True, "process": experiment.start(config)})
    except (ValueError, RuntimeError, OSError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/experiment/stop")
def api_experiment_stop():
    try:
        return jsonify({"ok": True, "process": experiment.stop()})
    except (OSError, subprocess.SubprocessError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/supervisor")
def api_supervisor():
    payload = request.get_json(silent=True) or {}
    try:
        level = str(payload.get("level", "")).upper()
        monitor.publish_override(level, str(payload.get("reason", "dashboard_override")))
        return jsonify({"ok": True, "level": level})
    except (ValueError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/attack/trigger")
def api_attack_trigger():
    payload = request.get_json(silent=True) or {}
    profile = str(payload.get("profile", "")).strip()
    process = experiment.snapshot()
    if not process.get("running"):
        return jsonify({"ok": False, "error": "No experiment is running."}), 400
    if not process.get("config", {}).get("attack_capable_model", False):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": (
                        "This normal run uses the stock GPS model. "
                        "Start an attack-profile experiment to enable injection."
                    ),
                }
            ),
            400,
        )
    defs = load_profile_defs()
    if profile not in defs:
        return jsonify({"ok": False, "error": "Unknown attack profile."}), 400
    if str(defs[profile].get("source", "none")) not in LIVE_ATTACK_SOURCES:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "This profile has no connected Gazebo injector yet.",
                }
            ),
            400,
        )
    try:
        monitor.publish_attack(defs[profile], enabled=True)
        return jsonify({"ok": True, "profile": profile})
    except (ValueError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/attack/stop")
def api_attack_stop():
    try:
        monitor.publish_attack({}, enabled=False)
        return jsonify({"ok": True})
    except (ValueError, rospy.ROSException) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


if __name__ == "__main__":
    host = os.environ.get("LAEA_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("LAEA_DASHBOARD_PORT", "12346"))
    app.run(host=host, port=port, threaded=True, use_reloader=False)
