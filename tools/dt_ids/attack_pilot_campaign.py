#!/usr/bin/env python3
"""Plan and run the resumable four-map LAEA attack pilot.

The safe default is a read-only dry-run.  Runtime execution must be requested
explicitly, and a full 32-attempt campaign needs a second acknowledgement.

Each attempt owns a separate directory and immutable task specification.  A
completed attempt is recovered from its run_manifest.csv after interruption,
and the campaign-level pilot_manifest.csv adds the profile name and expected
onset window that the lower-level manifest does not carry.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_CONFIG = (
    REPO_ROOT / "laea_twin_tools/config/attack_pilot_four_maps_v1.yaml"
)
DEFAULT_WORLD_CATALOG = REPO_ROOT / "laea_twin_tools/config/world_profiles.yaml"
DEFAULT_ATTACK_CATALOG = REPO_ROOT / "laea_twin_tools/config/attack_profiles.yaml"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "laea_twin_tools/laea_logs/attack_pilots"
DEFAULT_BATCH_RUNNER = REPO_ROOT / "run_aiottalk_batches_restart.sh"
GLOBAL_LOCK = Path("/tmp/laea_attack_pilot_campaign.lock")
UINT32_MAX = 2**32 - 1
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

EXPECTED_ATTACK_KINDS = {
    ("gps", "bias"),
    ("gps", "velocity_bias"),
    ("imu", "gyro_bias"),
    ("barometer", "drift"),
}

PILOT_MANIFEST_FIELDS = [
    "task_id",
    "map",
    "world_file",
    "world_sha256",
    "profile",
    "source",
    "mode",
    "severity",
    "seed",
    "attempt_index",
    "onset_min_s",
    "onset_max_s",
    "transport",
    "state",
    "runner_exit_code",
    "run_id",
    "outcome",
    "log_retained",
    "kpi_path",
    "scheduled_onset_s",
    "actual_onset_s",
    "duration_s",
    "attributable",
    "attribution_reason",
    "completed_at_utc",
]


class CampaignError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(str(temp_path), str(path))


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise CampaignError("configuration file does not exist: %s" % path)
    with path.open(encoding="utf-8") as source:
        payload = yaml.safe_load(source)
    if not isinstance(payload, dict):
        raise CampaignError("expected a YAML mapping: %s" % path)
    return payload


def require_number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise CampaignError("%s must be numeric" % label)
    if not math.isfinite(parsed):
        raise CampaignError("%s must be finite" % label)
    if parsed < minimum:
        raise CampaignError("%s must be >= %s" % (label, minimum))
    return parsed


def require_name(value: Any, label: str) -> str:
    parsed = str(value or "").strip()
    if not ID_RE.fullmatch(parsed):
        raise CampaignError("%s is not a safe identifier: %r" % (label, value))
    return parsed


def _planner_runtime(world: Mapping[str, Any], world_name: str) -> Dict[str, float]:
    planner = world.get("planner")
    if not isinstance(planner, dict):
        raise CampaignError("world %s has no planner mapping" % world_name)

    required = [
        "map_size_x",
        "map_size_y",
        "map_size_z",
        "box_x_min",
        "box_y_min",
        "box_z_min",
        "box_x_max",
        "box_y_max",
        "box_z_max",
        "min_finish_time_s",
        "min_finish_distance_m",
    ]
    result: Dict[str, float] = {}
    for key in required:
        if key not in planner:
            raise CampaignError("world %s planner is missing %s" % (world_name, key))
        result[key] = require_number(
            planner[key],
            "worlds.%s.planner.%s" % (world_name, key),
            minimum=-100000.0,
        )
    return result


def _spawn_runtime(world: Mapping[str, Any], world_name: str) -> Dict[str, float]:
    spawn = world.get("spawn")
    if not isinstance(spawn, dict):
        raise CampaignError("world %s has no spawn mapping" % world_name)
    result: Dict[str, float] = {}
    for key in ("x", "y", "z", "roll", "pitch", "yaw"):
        if key not in spawn:
            raise CampaignError("world %s spawn is missing %s" % (world_name, key))
        result[key] = require_number(
            spawn[key],
            "worlds.%s.spawn.%s" % (world_name, key),
            minimum=-100000.0,
        )
    return result


def _profile_snapshot(profile: Mapping[str, Any], name: str) -> Dict[str, Any]:
    required = ("source", "mode", "severity", "ramp_s", "duration_s", "recovery_s")
    missing = [key for key in required if key not in profile]
    if missing:
        raise CampaignError(
            "attack profile %s is missing: %s" % (name, ", ".join(missing))
        )
    result: Dict[str, Any] = {
        "name": name,
        "source": str(profile["source"]),
        "mode": str(profile["mode"]),
        "severity": str(profile["severity"]),
        "ramp_s": require_number(profile["ramp_s"], "%s.ramp_s" % name),
        "duration_s": require_number(
            profile["duration_s"], "%s.duration_s" % name
        ),
        "recovery_s": require_number(
            profile["recovery_s"], "%s.recovery_s" % name
        ),
    }
    kind = (result["source"], result["mode"])
    if kind not in EXPECTED_ATTACK_KINDS:
        raise CampaignError(
            "profile %s is not one of the four source-layer pilot types: %s/%s"
            % (name, kind[0], kind[1])
        )
    if result["mode"] == "drift":
        scalar = require_number(
            profile.get("scalar"), "%s.scalar" % name, minimum=-100000.0
        )
        if scalar == 0:
            raise CampaignError("%s.scalar must be non-zero" % name)
        result["scalar"] = scalar
    else:
        vector = profile.get("vector")
        try:
            converted_vector = [float(item) for item in vector]
        except (TypeError, ValueError):
            converted_vector = []
        if (
            not isinstance(vector, list)
            or len(converted_vector) != 3
            or not all(math.isfinite(item) for item in converted_vector)
            or not any(item != 0.0 for item in converted_vector)
        ):
            raise CampaignError("%s.vector must have three values and be non-zero" % name)
        result["vector"] = converted_vector
    return result


def build_plan(
    config_path: Path,
    world_catalog_path: Path,
    attack_catalog_path: Path,
    campaign_id: str,
) -> Dict[str, Any]:
    """Validate catalogs and return a deterministic immutable plan."""
    config_path = config_path.resolve()
    world_catalog_path = world_catalog_path.resolve()
    attack_catalog_path = attack_catalog_path.resolve()
    config = load_yaml(config_path)
    worlds_catalog = load_yaml(world_catalog_path).get("worlds")
    profiles_catalog = load_yaml(attack_catalog_path).get("profiles")
    if not isinstance(worlds_catalog, dict):
        raise CampaignError("world catalog has no 'worlds' mapping")
    if not isinstance(profiles_catalog, dict):
        raise CampaignError("attack catalog has no 'profiles' mapping")

    if config.get("schema_version") != "laea-attack-pilot-config-v1":
        raise CampaignError("unsupported attack pilot config schema_version")
    campaign_name = require_name(config.get("campaign_name"), "campaign_name")
    campaign_id = require_name(campaign_id, "campaign_id")
    transport = str(config.get("transport_mode", "")).strip()
    if transport != "nosip":
        raise CampaignError(
            "pilot transport must be 'nosip'; got %r (prevents switch mismatch)"
            % transport
        )
    attack_sdf = require_name(config.get("attack_sdf"), "attack_sdf")

    world_names = config.get("worlds")
    profile_names = config.get("profiles")
    if not isinstance(world_names, list) or not world_names:
        raise CampaignError("worlds must be a non-empty list")
    if not isinstance(profile_names, list) or not profile_names:
        raise CampaignError("profiles must be a non-empty list")
    world_names = [require_name(item, "world") for item in world_names]
    profile_names = [require_name(item, "profile") for item in profile_names]
    if len(set(world_names)) != len(world_names):
        raise CampaignError("worlds contains duplicates")
    if len(set(profile_names)) != len(profile_names):
        raise CampaignError("profiles contains duplicates")

    attempts = config.get("attempts_per_combination")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise CampaignError("attempts_per_combination must be a positive integer")
    base_seed = config.get("base_seed")
    if (
        not isinstance(base_seed, int)
        or isinstance(base_seed, bool)
        or base_seed < 0
        or base_seed > UINT32_MAX
    ):
        raise CampaignError("base_seed must fit uint32")

    onset = config.get("onset_window_s")
    if not isinstance(onset, list) or len(onset) != 2:
        raise CampaignError("onset_window_s must contain [min, max]")
    onset_min = require_number(onset[0], "onset_window_s[0]")
    onset_max = require_number(onset[1], "onset_window_s[1]")
    if onset_max < onset_min:
        raise CampaignError("onset_window_s max must be >= min")

    max_duration_map = config.get("max_duration_s")
    if not isinstance(max_duration_map, dict):
        raise CampaignError("max_duration_s must be a per-world mapping")

    worlds: List[Dict[str, Any]] = []
    for name in world_names:
        raw = worlds_catalog.get(name)
        if not isinstance(raw, dict):
            raise CampaignError("world %s is absent from world catalog" % name)
        world_file = Path(str(raw.get("world_file", ""))).expanduser().resolve()
        if not world_file.is_file():
            raise CampaignError("world file does not exist: %s" % world_file)
        max_duration = require_number(
            max_duration_map.get(name), "max_duration_s.%s" % name, minimum=1.0
        )
        worlds.append(
            {
                "name": name,
                "label": str(raw.get("label", name)),
                "world_file": str(world_file),
                "world_sha256": sha256_file(world_file),
                "spawn": _spawn_runtime(raw, name),
                "planner": _planner_runtime(raw, name),
                "max_duration_s": max_duration,
            }
        )

    profiles: List[Dict[str, Any]] = []
    for name in profile_names:
        raw = profiles_catalog.get(name)
        if not isinstance(raw, dict):
            raise CampaignError("profile %s is absent from attack catalog" % name)
        profiles.append(_profile_snapshot(raw, name))
    selected_kinds = {(item["source"], item["mode"]) for item in profiles}
    if selected_kinds != EXPECTED_ATTACK_KINDS:
        missing = EXPECTED_ATTACK_KINDS - selected_kinds
        extra = selected_kinds - EXPECTED_ATTACK_KINDS
        raise CampaignError(
            "profiles must cover exactly four attack types; missing=%s extra=%s"
            % (sorted(missing), sorted(extra))
        )

    smoke = config.get("smoke")
    if not isinstance(smoke, dict):
        raise CampaignError("smoke must be a mapping")
    smoke_world = require_name(smoke.get("world"), "smoke.world")
    smoke_attempt = smoke.get("attempt")
    smoke_profiles = smoke.get("profiles")
    if smoke_world not in world_names:
        raise CampaignError("smoke.world is not in the campaign worlds")
    if (
        not isinstance(smoke_attempt, int)
        or smoke_attempt < 1
        or smoke_attempt > attempts
    ):
        raise CampaignError("smoke.attempt is outside the planned attempt range")
    if not isinstance(smoke_profiles, list):
        raise CampaignError("smoke.profiles must be a list")
    smoke_profiles = [require_name(item, "smoke profile") for item in smoke_profiles]
    if set(smoke_profiles) != set(profile_names):
        raise CampaignError("smoke.profiles must cover every selected attack profile")

    tasks: List[Dict[str, Any]] = []
    task_index = 0
    for world in worlds:
        for profile in profiles:
            for attempt_index in range(1, attempts + 1):
                seed = base_seed + task_index
                if seed > UINT32_MAX:
                    raise CampaignError("resolved task seed exceeds uint32")
                task_id = "%s__%s__a%02d" % (
                    world["name"],
                    profile["name"],
                    attempt_index,
                )
                tasks.append(
                    {
                        "task_id": task_id,
                        "map": world["name"],
                        "world_file": world["world_file"],
                        "world_sha256": world["world_sha256"],
                        "world": world,
                        "profile": profile["name"],
                        "attack": profile,
                        "severity": profile["severity"],
                        "seed": seed,
                        "attempt_index": attempt_index,
                        "onset_min_s": onset_min,
                        "onset_max_s": onset_max,
                        "transport": transport,
                        "smoke": (
                            world["name"] == smoke_world
                            and profile["name"] in smoke_profiles
                            and attempt_index == smoke_attempt
                        ),
                    }
                )
                task_index += 1

    plan_core: Dict[str, Any] = {
        "schema_version": "laea-attack-pilot-plan-v1",
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "scenario": "attack_pilot",
        "transport_mode": transport,
        "attack_sdf": attack_sdf,
        "attempts_per_combination": attempts,
        "onset_window_s": [onset_min, onset_max],
        "catalogs": {
            "campaign_config": {
                "path": str(config_path),
                "sha256": sha256_file(config_path),
            },
            "world_profiles": {
                "path": str(world_catalog_path),
                "sha256": sha256_file(world_catalog_path),
            },
            "attack_profiles": {
                "path": str(attack_catalog_path),
                "sha256": sha256_file(attack_catalog_path),
            },
        },
        "worlds": worlds,
        "profiles": profiles,
        "tasks": tasks,
    }
    plan_core["plan_digest"] = canonical_digest(plan_core)
    return plan_core


def preflight(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Read-only checks for runtime dependencies used by every task."""
    sdf = str(plan["attack_sdf"])
    model_root = Path("/home/tim/PX4-Autopilot/Tools/sitl_gazebo/models")
    build_root = Path("/home/tim/PX4-Autopilot/build/px4_sitl_default/build_gazebo")
    checks: List[Tuple[str, Path]] = [
        ("batch runner", DEFAULT_BATCH_RUNNER),
        (
            "attack vehicle SDF",
            model_root / sdf / ("%s.sdf" % sdf),
        ),
        ("GPS attack plugin", build_root / "libgazebo_gps_attack_plugin.so"),
        ("IMU attack plugin", build_root / "libgazebo_imu_attack_plugin.so"),
        (
            "barometer attack plugin",
            build_root / "libgazebo_barometer_attack_plugin.so",
        ),
        (
            "Gazebo attack bridge",
            Path("/home/tim/laea/devel/lib/px4_gazebo/attack_gazebo_bridge"),
        ),
    ]
    results: List[Dict[str, Any]] = []
    for label, path in checks:
        results.append(
            {
                "check": label,
                "ok": path.is_file(),
                "detail": str(path),
            }
        )
    for world in plan["worlds"]:
        path = Path(world["world_file"])
        current = sha256_file(path) if path.is_file() else ""
        results.append(
            {
                "check": "world:%s" % world["name"],
                "ok": current == world["world_sha256"],
                "detail": str(path),
            }
        )
    return results


def active_runtime_processes() -> List[str]:
    """Find processes that would contend for the fixed ROS/PX4/Gazebo ports."""
    executable_names = {
        "roscore",
        "rosmaster",
        "roslaunch",
        "gzserver",
        "gzclient",
        "px4",
    }
    script_markers = (
        "/run_aiottalk_batches_restart.sh",
        "/run_aiottalk_rtp.sh",
    )
    ignored = {os.getpid(), os.getppid()}
    matches: List[str] = []
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in ignored:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        parts = [item.decode("utf-8", "replace") for item in raw.split(b"\0") if item]
        if not parts:
            continue
        executable = Path(parts[0]).name
        command = " ".join(parts)
        if executable in executable_names or any(
            marker in command for marker in script_markers
        ):
            matches.append("%d %s" % (pid, command))
    return sorted(matches)


def task_environment(
    task: Mapping[str, Any],
    campaign_dir: Path,
    task_dir: Path,
    invocation: int,
) -> Dict[str, str]:
    """Build the fully explicit environment passed to the existing runner."""
    world = task["world"]
    planner = world["planner"]
    spawn = world["spawn"]
    system_log_dir = (
        campaign_dir
        / "system_logs"
        / task["task_id"]
        / ("invocation_%03d" % invocation)
    )
    env = {
        "TOTAL_ROUNDS": "1",
        "BATCH_INCREMENT_SEED": "false",
        "SLEEP_BETWEEN_ROUNDS": "0",
        "EXP_SCENARIO": "attack_pilot",
        "EXP_WORLD_NAME": str(task["map"]),
        "EXP_WORLD_FILE": str(task["world_file"]),
        "EXP_TRANSPORT_MODE": str(task["transport"]),
        "EXP_MAX_DURATION_S": str(world["max_duration_s"]),
        "EXP_SPAWN_X": str(spawn["x"]),
        "EXP_SPAWN_Y": str(spawn["y"]),
        "EXP_SPAWN_Z": str(spawn["z"]),
        "EXP_SPAWN_ROLL": str(spawn["roll"]),
        "EXP_SPAWN_PITCH": str(spawn["pitch"]),
        "EXP_SPAWN_YAW": str(spawn["yaw"]),
        "EXP_MAP_SIZE_X": str(planner["map_size_x"]),
        "EXP_MAP_SIZE_Y": str(planner["map_size_y"]),
        "EXP_MAP_SIZE_Z": str(planner["map_size_z"]),
        "EXP_BOX_X_MIN": str(planner["box_x_min"]),
        "EXP_BOX_Y_MIN": str(planner["box_y_min"]),
        "EXP_BOX_Z_MIN": str(planner["box_z_min"]),
        "EXP_BOX_X_MAX": str(planner["box_x_max"]),
        "EXP_BOX_Y_MAX": str(planner["box_y_max"]),
        "EXP_BOX_Z_MAX": str(planner["box_z_max"]),
        "EXP_MIN_FINISH_TIME_S": str(planner["min_finish_time_s"]),
        "EXP_MIN_FINISH_DISTANCE_M": str(planner["min_finish_distance_m"]),
        "EXP_DELETE_ON_NON_SUCCESS": "false",
        "ATTACK_PROFILE": str(task["profile"]),
        "ATTACK_SEED": str(task["seed"]),
        "ATTACK_ONSET_MIN_S": str(task["onset_min_s"]),
        "ATTACK_ONSET_MAX_S": str(task["onset_max_s"]),
        "ENABLE_MISSION_AWARE": "1",
        "ENABLE_ATTACK_PLANE": "true",
        "ENABLE_ATTACK_SCHEDULER": "true",
        "LAEA_PX4_SDF": str(task.get("attack_sdf", "iris_d435_lidar_gps_attack")),
        "ENABLE_DITTO_BRIDGE": "0",
        "ENABLE_AIOTTALK_RTP": "0",
        "ENABLE_NOSIP_RTP": "1",
        "ENABLE_RVIZ": "0",
        "ENABLE_GAZEBO_GUI": "0",
        "DISPLAY": os.environ.get("DISPLAY", ":0"),
        "LAEA_LOG_DIR": str(task_dir),
        "EXP_MANIFEST_PATH": str(task_dir / "run_manifest.csv"),
        "ROUND_STATUS_FILE": str(task_dir / "last_round_status.env"),
        "BATCH_PROGRESS_FILE": str(task_dir / "batch_progress.json"),
        "LAEA_SYS_LOG_DIR": str(system_log_dir),
    }
    return env


def _as_float(value: Any) -> Optional[float]:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed


def _as_true(value: Any) -> bool:
    return str(value or "").strip().lower() == "true"


def read_manifest_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def result_from_row(
    task: Mapping[str, Any],
    task_dir: Path,
    row: Mapping[str, Any],
    runner_exit_code: Optional[int],
) -> Dict[str, Any]:
    actual_onset = _as_float(row.get("attack_actual_onset_s"))
    scheduled_onset = _as_float(row.get("attack_scheduled_onset_s"))
    duration = _as_float(row.get("duration_s"))
    retained = _as_true(row.get("log_retained"))
    run_id = str(row.get("run_id", "")).strip()
    kpi_path = task_dir / ("kpi_log_%s.csv" % run_id)

    attributable = True
    reason = "keep"
    if str(row.get("world_name", "")).strip() != task["map"]:
        attributable = False
        reason = "world_mismatch"
    elif str(row.get("transport_mode", "")).strip() != task["transport"]:
        attributable = False
        reason = "transport_mismatch"
    elif str(row.get("attack_source", "")).strip() != task["attack"]["source"]:
        attributable = False
        reason = "attack_source_mismatch_or_missing"
    elif str(row.get("attack_mode", "")).strip() != task["attack"]["mode"]:
        attributable = False
        reason = "attack_mode_mismatch_or_missing"
    elif str(row.get("attack_severity", "")).strip() != task["severity"]:
        attributable = False
        reason = "attack_severity_mismatch_or_missing"
    elif str(row.get("attack_seed", "")).strip() != str(task["seed"]):
        attributable = False
        reason = "attack_seed_mismatch_or_missing"
    elif actual_onset is None or actual_onset <= 0:
        attributable = False
        reason = "attack_never_fired"
    elif duration is None or duration < actual_onset:
        attributable = False
        reason = "mission_ended_before_attack_onset"
    elif not retained or not kpi_path.is_file():
        attributable = False
        reason = "retained_kpi_csv_missing"

    return {
        "schema_version": "laea-attack-pilot-result-v1",
        "task_id": task["task_id"],
        "map": task["map"],
        "world_file": task["world_file"],
        "world_sha256": task["world_sha256"],
        "profile": task["profile"],
        "source": task["attack"]["source"],
        "mode": task["attack"]["mode"],
        "severity": task["severity"],
        "seed": task["seed"],
        "attempt_index": task["attempt_index"],
        "onset_min_s": task["onset_min_s"],
        "onset_max_s": task["onset_max_s"],
        "transport": task["transport"],
        "state": "completed",
        "runner_exit_code": runner_exit_code,
        "run_id": run_id,
        "outcome": str(row.get("outcome", "")).strip(),
        "log_retained": retained,
        "kpi_path": str(kpi_path.resolve()) if kpi_path.is_file() else "",
        "scheduled_onset_s": scheduled_onset,
        "actual_onset_s": actual_onset,
        "duration_s": duration,
        "attributable": attributable,
        "attribution_reason": reason,
        "completed_at_utc": utc_now(),
    }


def recover_task(
    task: Mapping[str, Any], task_dir: Path
) -> Optional[Dict[str, Any]]:
    """Recover a finished attempt without launching the simulator again."""
    result_path = task_dir / "attempt_result.json"
    if result_path.is_file():
        with result_path.open(encoding="utf-8") as source:
            result = json.load(source)
        if result.get("task_id") != task["task_id"]:
            raise CampaignError("result task_id mismatch in %s" % result_path)
        if result.get("state") == "completed":
            return result

    rows = read_manifest_rows(task_dir / "run_manifest.csv")
    for row in reversed(rows):
        # A user interruption is retryable and does not consume the attempt.
        if str(row.get("outcome", "")).strip() == "ABORTED":
            continue
        world = str(row.get("world_name", "")).strip()
        transport = str(row.get("transport_mode", "")).strip()
        seed = str(row.get("attack_seed", "")).strip()
        if world and world != task["map"]:
            continue
        if transport and transport != task["transport"]:
            continue
        if seed and seed != str(task["seed"]):
            continue
        result = result_from_row(task, task_dir, row, runner_exit_code=None)
        atomic_write_json(result_path, result)
        return result
    return None


def _invocation_number(task_dir: Path) -> int:
    existing = sorted(task_dir.glob("driver_invocation_*.log"))
    return len(existing) + 1


def run_subprocess_with_tee(
    command: Sequence[str],
    env: Mapping[str, str],
    cwd: Path,
    log_path: Path,
) -> int:
    full_env = os.environ.copy()
    full_env.update(env)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n[%s] command=%s\n" % (utc_now(), " ".join(command)))
        log.flush()
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            start_new_session=True,
        )
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def request_stop(_signum: int, _frame: Any) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, request_stop)
        try:
            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()
            return process.wait()
        except KeyboardInterrupt:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=20)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)


def write_task_spec(task_dir: Path, task: Mapping[str, Any]) -> None:
    path = task_dir / "task_spec.json"
    snapshot = dict(task)
    snapshot["schema_version"] = "laea-attack-pilot-task-v1"
    snapshot["task_digest"] = canonical_digest(task)
    if path.is_file():
        with path.open(encoding="utf-8") as source:
            existing = json.load(source)
        if existing.get("task_digest") != snapshot["task_digest"]:
            raise CampaignError("immutable task spec changed: %s" % path)
        return
    atomic_write_json(path, snapshot)


def selected_tasks(
    plan: Mapping[str, Any], selection: str, task_ids: Sequence[str]
) -> List[Dict[str, Any]]:
    tasks = list(plan["tasks"])
    if selection == "smoke":
        tasks = [task for task in tasks if task["smoke"]]
    if task_ids:
        wanted = set(task_ids)
        known = {task["task_id"] for task in tasks}
        missing = wanted - known
        if missing:
            raise CampaignError(
                "task id is not part of the %s selection: %s"
                % (selection, ", ".join(sorted(missing)))
            )
        tasks = [task for task in tasks if task["task_id"] in wanted]
    return tasks


def consolidate_results(campaign_dir: Path, plan: Mapping[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for task in plan["tasks"]:
        result_path = (
            campaign_dir / "runs" / task["task_id"] / "attempt_result.json"
        )
        if result_path.is_file():
            with result_path.open(encoding="utf-8") as source:
                result = json.load(source)
            if result.get("state") == "completed":
                rows.append(result)

    manifest_path = campaign_dir / "pilot_manifest.csv"
    temp_path = manifest_path.with_name(manifest_path.name + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=PILOT_MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in PILOT_MANIFEST_FIELDS})
        target.flush()
        os.fsync(target.fileno())
    os.replace(str(temp_path), str(manifest_path))

    status = {
        "schema_version": "laea-attack-pilot-status-v1",
        "campaign_id": plan["campaign_id"],
        "plan_digest": plan["plan_digest"],
        "state": "completed" if len(rows) == len(plan["tasks"]) else "in_progress",
        "planned_attempts": len(plan["tasks"]),
        "completed_attempts": len(rows),
        "remaining_attempts": len(plan["tasks"]) - len(rows),
        "attributable_attempts": sum(bool(row.get("attributable")) for row in rows),
        "rejected_attempts": sum(
            not bool(row.get("attributable")) for row in rows
        ),
        "outcomes": {},
        "updated_at_utc": utc_now(),
    }
    for row in rows:
        outcome = str(row.get("outcome") or "UNKNOWN")
        status["outcomes"][outcome] = status["outcomes"].get(outcome, 0) + 1
    atomic_write_json(campaign_dir / "campaign_status.json", status)
    return status


def initialize_campaign(campaign_dir: Path, plan: Mapping[str, Any]) -> None:
    campaign_dir.mkdir(parents=True, exist_ok=True)
    plan_path = campaign_dir / "campaign_plan.json"
    if plan_path.is_file():
        with plan_path.open(encoding="utf-8") as source:
            existing = json.load(source)
        if existing.get("plan_digest") != plan["plan_digest"]:
            raise CampaignError(
                "campaign plan changed; use the original config/catalogs or a new campaign id"
            )
        return
    saved = dict(plan)
    saved["created_at_utc"] = utc_now()
    atomic_write_json(plan_path, saved)


def execute_campaign(
    campaign_dir: Path,
    plan: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
) -> int:
    initialize_campaign(campaign_dir, plan)
    checks = preflight(plan)
    failures = [item for item in checks if not item["ok"]]
    if failures:
        raise CampaignError(
            "preflight failed: "
            + "; ".join("%s (%s)" % (item["check"], item["detail"]) for item in failures)
        )

    with GLOBAL_LOCK.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CampaignError(
                "another attack pilot driver holds %s; refusing shared ROS/PX4 ports"
                % GLOBAL_LOCK
            )
        lock.seek(0)
        lock.truncate()
        lock.write("%s pid=%d campaign=%s\n" % (utc_now(), os.getpid(), plan["campaign_id"]))
        lock.flush()

        for index, task in enumerate(tasks, 1):
            task_dir = campaign_dir / "runs" / task["task_id"]
            task_dir.mkdir(parents=True, exist_ok=True)
            write_task_spec(task_dir, task)
            recovered = recover_task(task, task_dir)
            if recovered is not None:
                print(
                    "[pilot] %d/%d skip completed %s outcome=%s attributable=%s"
                    % (
                        index,
                        len(tasks),
                        task["task_id"],
                        recovered.get("outcome"),
                        recovered.get("attributable"),
                    )
                )
                consolidate_results(campaign_dir, plan)
                continue

            conflicts = active_runtime_processes()
            if conflicts:
                raise CampaignError(
                    "ROS/PX4/Gazebo runtime already active; refusing fixed-port "
                    "collision: " + " | ".join(conflicts)
                )

            invocation = _invocation_number(task_dir)
            env = task_environment(task, campaign_dir, task_dir, invocation)
            # Plan-level SDF is injected here, keeping individual task records
            # small while still pinning the model name in campaign_plan.json.
            env["LAEA_PX4_SDF"] = str(plan["attack_sdf"])
            log_path = task_dir / ("driver_invocation_%03d.log" % invocation)
            print(
                "[pilot] %d/%d run %s map=%s profile=%s severity=%s seed=%s "
                "onset=[%s,%s] transport=%s"
                % (
                    index,
                    len(tasks),
                    task["task_id"],
                    task["map"],
                    task["profile"],
                    task["severity"],
                    task["seed"],
                    task["onset_min_s"],
                    task["onset_max_s"],
                    task["transport"],
                )
            )
            try:
                rc = run_subprocess_with_tee(
                    ["bash", str(DEFAULT_BATCH_RUNNER)],
                    env,
                    REPO_ROOT,
                    log_path,
                )
            except KeyboardInterrupt:
                interrupted = {
                    "schema_version": "laea-attack-pilot-result-v1",
                    "task_id": task["task_id"],
                    "state": "interrupted",
                    "completed_at_utc": utc_now(),
                }
                atomic_write_json(task_dir / "attempt_result.json", interrupted)
                consolidate_results(campaign_dir, plan)
                print("[pilot] interrupted; rerun the same command to resume", file=sys.stderr)
                return 130

            rows = read_manifest_rows(task_dir / "run_manifest.csv")
            result: Optional[Dict[str, Any]] = None
            for row in reversed(rows):
                if str(row.get("outcome", "")).strip() == "ABORTED":
                    continue
                result = result_from_row(task, task_dir, row, rc)
                break
            if result is None:
                failure = {
                    "schema_version": "laea-attack-pilot-result-v1",
                    "task_id": task["task_id"],
                    "state": "failed_infrastructure",
                    "runner_exit_code": rc,
                    "completed_at_utc": utc_now(),
                }
                atomic_write_json(task_dir / "attempt_result.json", failure)
                consolidate_results(campaign_dir, plan)
                print(
                    "[pilot] no terminal run manifest row for %s; stopped so a "
                    "setup failure is not repeated across all tasks" % task["task_id"],
                    file=sys.stderr,
                )
                return 2
            atomic_write_json(task_dir / "attempt_result.json", result)
            consolidate_results(campaign_dir, plan)
            print(
                "[pilot] completed %s outcome=%s actual_onset=%s attributable=%s (%s)"
                % (
                    task["task_id"],
                    result["outcome"],
                    result["actual_onset_s"],
                    result["attributable"],
                    result["attribution_reason"],
                )
            )

    status = consolidate_results(campaign_dir, plan)
    selection_results = []
    for task in tasks:
        path = campaign_dir / "runs" / task["task_id"] / "attempt_result.json"
        if path.is_file():
            with path.open(encoding="utf-8") as source:
                selection_results.append(json.load(source))
    rejected = [
        item
        for item in selection_results
        if item.get("state") == "completed" and not item.get("attributable")
    ]
    print(
        "[pilot] selection complete; campaign=%d/%d attributable=%d rejected=%d"
        % (
            status["completed_attempts"],
            status["planned_attempts"],
            status["attributable_attempts"],
            status["rejected_attempts"],
        )
    )
    return 3 if rejected else 0


def print_dry_run(
    plan: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    checks: Sequence[Mapping[str, Any]],
    campaign_dir: Path,
) -> None:
    print("LAEA attack pilot dry-run (no simulator processes started)")
    print("campaign_id : %s" % plan["campaign_id"])
    print("plan_digest : %s" % plan["plan_digest"])
    print("output      : %s" % campaign_dir)
    print(
        "plan        : %d maps x %d profiles x %d attempts = %d attempts"
        % (
            len(plan["worlds"]),
            len(plan["profiles"]),
            plan["attempts_per_combination"],
            len(plan["tasks"]),
        )
    )
    print("selected    : %d attempts" % len(tasks))
    print("preflight:")
    for item in checks:
        print(
            "  %-4s %-28s %s"
            % ("OK" if item["ok"] else "FAIL", item["check"], item["detail"])
        )
    print("tasks:")
    for task in tasks:
        print(
            "  %-53s map=%-18s profile=%-25s severity=%-5s seed=%d "
            "onset=%.1f-%.1fs transport=%s%s"
            % (
                task["task_id"],
                task["map"],
                task["profile"],
                task["severity"],
                task["seed"],
                task["onset_min_s"],
                task["onset_max_s"],
                task["transport"],
                " [smoke]" if task["smoke"] else "",
            )
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or execute the resumable four-map x four-attack x two-attempt pilot."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--world-catalog", type=Path, default=DEFAULT_WORLD_CATALOG)
    parser.add_argument("--attack-catalog", type=Path, default=DEFAULT_ATTACK_CATALOG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--campaign-id",
        default="attack_four_maps_pilot_v1_DRYRUN",
        help="Required as a non-DRYRUN identifier with --execute.",
    )
    parser.add_argument(
        "--selection", choices=("smoke", "full"), default="smoke"
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        help="Run/print only this task within the selected set (repeatable).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually start sequential ROS/PX4/Gazebo attempts.",
    )
    parser.add_argument(
        "--allow-full-campaign",
        action="store_true",
        help="Second acknowledgement required with --execute --selection full.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.execute and str(args.campaign_id).endswith("_DRYRUN"):
            raise CampaignError(
                "--execute requires an explicit persistent --campaign-id"
            )
        if args.execute and args.selection == "full" and not args.allow_full_campaign:
            raise CampaignError(
                "full execution needs --allow-full-campaign; run the smoke selection first"
            )
        output_root = args.output_root.expanduser().resolve()
        if output_root in (Path("/"), Path.home().resolve(), REPO_ROOT.resolve()):
            raise CampaignError("unsafe output root: %s" % output_root)

        plan = build_plan(
            args.config,
            args.world_catalog,
            args.attack_catalog,
            args.campaign_id,
        )
        tasks = selected_tasks(plan, args.selection, args.task_id)
        campaign_dir = output_root / plan["campaign_id"]
        if not args.execute:
            checks = preflight(plan)
            print_dry_run(plan, tasks, checks, campaign_dir)
            return 0 if all(item["ok"] for item in checks) else 2
        return execute_campaign(campaign_dir, plan, tasks)
    except CampaignError as exc:
        print("[attack_pilot] ERROR: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[attack_pilot] interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
