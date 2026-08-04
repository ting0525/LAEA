"""Linux process-tree inspection and signalling for experiment cleanup."""

import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import (
    BATCH_SCRIPT,
    DASHBOARD_RUN_ID_ENV,
    EXPERIMENT_EXECUTABLE_NAMES,
    EXPERIMENT_LAUNCH_FILES,
    EXPERIMENT_ROS_NAME_ARGS,
    EXPERIMENT_SCRIPT_NAMES,
    RUN_SCRIPT,
    read_json_file,
    write_json_file,
)


def process_table():
    table = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            stat_text = (entry / "stat").read_text()
            fields = stat_text[stat_text.rfind(")") + 2 :].split()
            cmdline_bytes = (entry / "cmdline").read_bytes()
            argv = [
                value.decode(errors="replace")
                for value in cmdline_bytes.split(b"\0")
                if value
            ]
            cmdline = " ".join(argv)
            table[pid] = {
                "pid": pid,
                "state": fields[0],
                "ppid": int(fields[1]),
                "pgid": int(fields[2]),
                "sid": int(fields[3]),
                "argv": argv,
                "cmdline": cmdline,
            }
        except (OSError, ValueError, IndexError):
            continue
    return table


def process_environment(pid):
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return {}
    environment = {}
    for entry in entries:
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        environment[key.decode(errors="replace")] = value.decode(errors="replace")
    return environment


def process_run_id(pid):
    return process_environment(pid).get(DASHBOARD_RUN_ID_ENV, "")


def descendant_pids(root_pids, table=None):
    table = table or process_table()
    children = {}
    for pid, info in table.items():
        children.setdefault(info["ppid"], set()).add(pid)

    descendants = set()
    pending = [int(pid) for pid in root_pids]
    while pending:
        parent = pending.pop()
        for child in children.get(parent, ()):
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def process_descendants(root_pid):
    return descendant_pids({root_pid})


def command_is_runner(command):
    argv = command if isinstance(command, (list, tuple)) else [command]
    return str(RUN_SCRIPT) in argv or str(BATCH_SCRIPT) in argv


def process_is_experiment_component(info):
    argv = list(info.get("argv") or [])
    if not argv:
        return False
    basenames = {Path(value).name for value in argv if value}
    if basenames & EXPERIMENT_EXECUTABLE_NAMES:
        return True
    if basenames & EXPERIMENT_SCRIPT_NAMES:
        return True
    if "roslaunch" in basenames and basenames & EXPERIMENT_LAUNCH_FILES:
        return True
    return bool(set(argv) & EXPERIMENT_ROS_NAME_ARGS)


def discover_experiment_roots(table=None):
    table = table or process_table()
    candidates = {
        pid for pid, info in table.items() if command_is_runner(info["argv"])
    }
    roots = set()
    for pid in candidates:
        parent = table.get(pid, {}).get("ppid", 0)
        seen = set()
        has_runner_ancestor = False
        while parent > 1 and parent not in seen:
            seen.add(parent)
            if parent in candidates:
                has_runner_ancestor = True
                break
            parent = table.get(parent, {}).get("ppid", 0)
        if not has_runner_ancestor:
            roots.add(pid)
    return roots


def experiment_component_pids(table=None, run_ids=None):
    table = table or process_table()
    run_ids = {value for value in (run_ids or set()) if value}
    matched = set()
    for pid, info in table.items():
        if process_is_experiment_component(info):
            matched.add(pid)
            continue
        if run_ids and process_run_id(pid) in run_ids:
            matched.add(pid)
    return matched


def live_pids(pids):
    alive = set()
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat", "r") as source:
                state = source.read().split()[2]
            if state != "Z":
                alive.add(pid)
        except (OSError, IndexError):
            pass
    return alive


def signal_process_tree(pids, process_groups, sig):
    own_group = os.getpgrp()
    for group in sorted(process_groups, reverse=True):
        if group <= 1 or group == own_group:
            continue
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            pass
    for pid in sorted(pids, reverse=True):
        if pid <= 1 or pid == os.getpid():
            continue
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def wait_for_processes(pids, timeout_s):
    deadline = time.time() + timeout_s
    remaining = live_pids(pids)
    while remaining and time.time() < deadline:
        time.sleep(0.2)
        remaining = live_pids(remaining)
    return remaining


def update_stopped_progress(
    path, cleanup_complete, remaining_pids, remaining_ros_nodes
):
    payload = read_json_file(path)
    if not payload:
        return
    payload.update(
        {
            "state": "STOPPED",
            "stop_requested_at": datetime.now(timezone.utc).isoformat(),
            "cleanup_complete": bool(cleanup_complete),
            "remaining_pids": sorted(int(pid) for pid in remaining_pids),
            "remaining_ros_nodes": sorted(remaining_ros_nodes),
        }
    )
    write_json_file(path, payload)
