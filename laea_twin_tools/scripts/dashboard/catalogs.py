"""Attack/world catalogs and experiment start-config validation."""

import csv
import os
from pathlib import Path

import rosgraph
import yaml

from .common import *  # noqa: F401,F403  constants + helpers


def profile_catalog():
    definitions = load_profile_defs()
    catalog = [
        {
            "name": "none",
            "source": "none",
            "mode": "none",
            "severity": "none",
            "vector": [0.0, 0.0, 0.0],
            "scalar": 0.0,
            "live_supported": True,
            "note": "clean baseline",
        }
    ]
    for name in sorted(definitions):
        definition = dict(definitions[name] or {})
        source = str(definition.get("source", "none"))
        live_supported = source in LIVE_ATTACK_SOURCES
        catalog.append(
            {
                "name": name,
                "source": source,
                "mode": str(definition.get("mode", "none")),
                "severity": str(definition.get("severity", "none")),
                "ramp_s": float(definition.get("ramp_s", 0.0)),
                "duration_s": float(definition.get("duration_s", 0.0)),
                "recovery_s": float(definition.get("recovery_s", 0.0)),
                "vector": list(definition.get("vector", [0.0, 0.0, 0.0])),
                "scalar": float(definition.get("scalar", 0.0)),
                "live_supported": live_supported,
                "note": (
                    f"{source} source-layer injector connected"
                    if live_supported
                    else "profile only; injector not connected"
                ),
            }
        )
    return catalog


def load_world_defs():
    try:
        with open(WORLD_CONFIG, "r") as source:
            return dict(yaml.safe_load(source) or {}).get("worlds", {})
    except (OSError, yaml.YAMLError):
        return {}


def normalized_world_profile(name, definitions=None):
    definitions = definitions if definitions is not None else load_world_defs()
    if name not in definitions:
        raise ValueError("Unknown world profile.")

    definition = dict(definitions[name] or {})
    world_file = Path(
        os.path.expandvars(os.path.expanduser(str(definition.get("world_file", ""))))
    )
    if not world_file.is_file():
        raise ValueError(f"World file is unavailable: {world_file}")

    spawn_source = dict(definition.get("spawn") or {})
    planner_source = dict(definition.get("planner") or {})

    def number(source, key, default):
        try:
            return float(source.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {name}.{key}.") from exc

    spawn = {
        "x": number(spawn_source, "x", 0.0),
        "y": number(spawn_source, "y", 0.0),
        "z": number(spawn_source, "z", 1.0),
        "roll": number(spawn_source, "roll", 0.0),
        "pitch": number(spawn_source, "pitch", 0.0),
        "yaw": number(spawn_source, "yaw", 0.0),
    }
    planner = {
        "map_size_x": number(planner_source, "map_size_x", 80.0),
        "map_size_y": number(planner_source, "map_size_y", 80.0),
        "map_size_z": number(planner_source, "map_size_z", 3.0),
        "box_x_min": number(planner_source, "box_x_min", -23.0),
        "box_y_min": number(planner_source, "box_y_min", -11.0),
        "box_z_min": number(planner_source, "box_z_min", -0.1),
        "box_x_max": number(planner_source, "box_x_max", 23.0),
        "box_y_max": number(planner_source, "box_y_max", 11.0),
        "box_z_max": number(planner_source, "box_z_max", 2.3),
        "min_finish_time_s": number(
            planner_source, "min_finish_time_s", 300.0
        ),
        "min_finish_distance_m": number(
            planner_source, "min_finish_distance_m", 200.0
        ),
    }
    for axis in ("x", "y", "z"):
        if planner[f"box_{axis}_min"] >= planner[f"box_{axis}_max"]:
            raise ValueError(f"Invalid {name} planner boundary for axis {axis}.")
    if planner["min_finish_time_s"] < 0.0:
        raise ValueError(f"Invalid {name}.min_finish_time_s.")
    if planner["min_finish_distance_m"] < 0.0:
        raise ValueError(f"Invalid {name}.min_finish_distance_m.")

    return {
        "name": name,
        "label": str(definition.get("label", name)),
        "description": str(definition.get("description", "")),
        "world_file": str(world_file.resolve()),
        "spawn": spawn,
        "planner": planner,
    }


def world_catalog():
    definitions = load_world_defs()
    catalog = []
    for name in definitions:
        try:
            profile = normalized_world_profile(name, definitions)
            profile["available"] = True
            profile["error"] = ""
        except ValueError as exc:
            definition = dict(definitions.get(name) or {})
            profile = {
                "name": name,
                "label": str(definition.get("label", name)),
                "description": str(definition.get("description", "")),
                "available": False,
                "error": str(exc),
            }
        catalog.append(profile)
    return catalog


def load_profiles():
    try:
        with open(PROFILE_CONFIG, "r") as source:
            profiles = dict(yaml.safe_load(source) or {}).get("profiles", {})
    except (OSError, yaml.YAMLError):
        profiles = {}
    return ["none"] + sorted(profiles.keys())


def load_profile_defs():
    try:
        with open(PROFILE_CONFIG, "r") as source:
            return dict(yaml.safe_load(source) or {}).get("profiles", {})
    except (OSError, yaml.YAMLError):
        return {}


def normalize_start_config(payload, profiles):
    payload = dict(payload or {})

    def clean_name(key, default):
        value = str(payload.get(key, default)).strip()
        if not NAME_RE.match(value):
            raise ValueError(f"Invalid {key}.")
        return value

    profile = clean_name("attack_profile", "none")
    if profile not in profiles:
        raise ValueError("Unknown attack profile.")
    if profile != "none":
        definition = load_profile_defs().get(profile, {})
        if str(definition.get("source", "none")) not in LIVE_ATTACK_SOURCES:
            raise ValueError(
                "This attack profile is not connected to a source-layer injector yet."
            )

    seed = int(payload.get("attack_seed", 42))
    if seed < 0 or seed > 4294967295:
        raise ValueError("attack_seed must fit uint32.")
    max_duration = float(payload.get("max_duration_s", 900.0))
    if max_duration < 30.0 or max_duration > 7200.0:
        raise ValueError("max_duration_s must be between 30 and 7200.")
    collection_mode = str(payload.get("collection_mode", "single")).lower()
    if collection_mode not in ("single", "batch"):
        raise ValueError("collection_mode must be single or batch.")
    total_rounds = int(payload.get("total_rounds", 10))
    if total_rounds < 1 or total_rounds > 1000:
        raise ValueError("total_rounds must be between 1 and 1000.")
    sleep_between_rounds_s = float(payload.get("sleep_between_rounds_s", 5.0))
    if sleep_between_rounds_s < 0.0 or sleep_between_rounds_s > 600.0:
        raise ValueError("sleep_between_rounds_s must be between 0 and 600.")
    increment_seed = bool(payload.get("increment_seed", True))
    if increment_seed and seed + total_rounds - 1 > 4294967295:
        raise ValueError("The final incremented attack seed would exceed uint32.")

    world_name = clean_name("world_name", "indoor_01")
    world_profile = normalized_world_profile(world_name)

    return {
        "runtime_profile": STABLE_RUNTIME_PROFILE,
        "collection_mode": collection_mode,
        "dataset_name": clean_name("dataset_name", "dashboard"),
        "scenario": clean_name("scenario", "normal"),
        "world_name": world_name,
        "world_profile": world_profile,
        "attack_profile": profile,
        "manual_attack": bool(payload.get("manual_attack", False)),
        "attack_seed": seed,
        "max_duration_s": max_duration,
        "detector_name": clean_name("detector_name", "rule_mad"),
        "supervisor_policy": clean_name("supervisor_policy", "none"),
        "total_rounds": total_rounds,
        "sleep_between_rounds_s": sleep_between_rounds_s,
        "increment_seed": increment_seed,
        "enable_rviz": bool(payload.get("enable_rviz", False)),
        "enable_ditto": bool(payload.get("enable_ditto", False)),
        "enable_rtp": bool(payload.get("enable_rtp", True)),
    }


def read_recent_runs(dataset_dir, limit=12):
    path = os.path.join(dataset_dir, "run_manifest.csv")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", newline="") as source:
            rows = list(csv.DictReader(source))
    except (OSError, csv.Error):
        return []
    return rows[-max(1, min(int(limit), 100)) :][::-1]


def ros_master_online():
    try:
        rosgraph.Master("/laea_dashboard").getPid()
        return True
    except Exception:
        return False


# An anonymous ROS node name prevents a newly launched dashboard from shutting
# down another Flask process that is still exiting with the same node name.
