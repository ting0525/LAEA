#!/usr/bin/env python3
"""Validate source-layer effects in a completed LAEA attack pilot.

This is an evaluation-only tool.  It may use simulator ground truth
(``px_gt``, ``py_gt``, ``pz_gt``) to verify that an injected source changed by
the commanded amount.  Those columns are explicitly forbidden as detector or
model inputs.

Only attempts whose attempt_result.json says all of the following are analyzed:

* state == "completed"
* log_retained == true
* attributable == true

Those flags are not trusted on their own.  The task snapshot, run manifest,
KPI identity, time base, lifecycle windows, required columns, and observed
effect are independently checked.  Invalid or too-short windows never become a
successful validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


SCHEMA_VERSION = "laea-attack-pilot-effects-v1"
EARTH_RADIUS_M = 6378137.0

DEFAULT_MIN_PHASE_SAMPLES = 20
DEFAULT_MIN_PHASE_SPAN_S = 1.0
MAX_START_END_ALIGNMENT_ERROR_S = 2.0
MAX_DURATION_ALIGNMENT_ERROR_S = 2.0
MAX_ACTUAL_SCHEDULED_ONSET_ERROR_S = 1.0

# Deliberately descriptive rather than inferential: adjacent 20 Hz samples are
# autocorrelated.  Cliff's delta is reported as an effect size, not a p-value.
EFFECT_THRESHOLDS = {
    ("gps", "bias"): {
        "minimum_command_fraction": 0.50,
        "minimum_oriented_cliffs_delta": 0.50,
    },
    ("gps", "velocity_bias"): {
        # EKF/local velocity follows part of the source spoof in closed loop,
        # so the observable GPS-local residual is expected to be attenuated.
        "minimum_command_fraction": 0.20,
        "minimum_oriented_cliffs_delta": 0.50,
    },
    ("imu", "gyro_bias"): {
        # Pose yaw-rate is itself an estimated, closed-loop quantity.
        "minimum_command_fraction": 0.20,
        "minimum_oriented_cliffs_delta": 0.40,
    },
    ("barometer", "drift"): {
        "minimum_command_fraction": 0.50,
        "minimum_oriented_cliffs_delta": 0.50,
    },
}


class ValidationError(RuntimeError):
    """A task cannot be truthfully evaluated."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as target:
        target.write(text)
        target.flush()
        os.fsync(target.fileno())
    os.replace(str(temp), str(path))


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    atomic_write_text(path, text + "\n")


def load_json(path: Path, label: str) -> Dict[str, Any]:
    if not path.is_file():
        raise ValidationError("%s is missing: %s" % (label, path))
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("%s is unreadable: %s" % (label, exc))
    if not isinstance(value, dict):
        raise ValidationError("%s must contain a JSON object" % label)
    return value


def finite_float(value: Any, label: str, *, minimum: Optional[float] = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValidationError("%s must be numeric" % label)
    if not math.isfinite(parsed):
        raise ValidationError("%s must be finite" % label)
    if minimum is not None and parsed < minimum:
        raise ValidationError("%s must be >= %s" % (label, minimum))
    return parsed


def require_string(value: Any, label: str) -> str:
    parsed = str(value or "").strip()
    if not parsed:
        raise ValidationError("%s must be a non-empty string" % label)
    return parsed


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError("%s must be a JSON boolean" % label)
    return value


def manifest_bool(value: Any, label: str) -> bool:
    parsed = str(value or "").strip().lower()
    if parsed not in ("true", "false"):
        raise ValidationError("%s must be true or false" % label)
    return parsed == "true"


def read_matching_manifest_row(path: Path, run_id: str) -> Dict[str, str]:
    if not path.is_file():
        raise ValidationError("run manifest is missing: %s" % path)
    try:
        with path.open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
    except (OSError, csv.Error) as exc:
        raise ValidationError("run manifest is unreadable: %s" % exc)
    matches = [row for row in rows if str(row.get("run_id", "")).strip() == run_id]
    if len(matches) != 1:
        raise ValidationError(
            "run manifest must contain exactly one row for %s; found %d"
            % (run_id, len(matches))
        )
    return matches[0]


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if str(actual).strip() != str(expected).strip():
        raise ValidationError(
            "%s mismatch: expected %r, got %r" % (label, expected, actual)
        )


def profile_contract(task: Mapping[str, Any]) -> Dict[str, Any]:
    attack = task.get("attack")
    if not isinstance(attack, dict):
        raise ValidationError("task_spec.attack must be an object")
    source = require_string(attack.get("source"), "task_spec.attack.source")
    mode = require_string(attack.get("mode"), "task_spec.attack.mode")
    kind = (source, mode)
    if kind not in EFFECT_THRESHOLDS:
        raise ValidationError("unsupported source-layer attack: %s/%s" % kind)

    ramp_s = finite_float(attack.get("ramp_s"), "attack.ramp_s", minimum=0.0)
    duration_s = finite_float(
        attack.get("duration_s"), "attack.duration_s", minimum=0.1
    )
    recovery_s = finite_float(
        attack.get("recovery_s"), "attack.recovery_s", minimum=0.0
    )
    # The fixed two-second active guard and one-second recovery guards below
    # must leave non-empty requested windows.
    if duration_s <= ramp_s + 4.0:
        raise ValidationError(
            "attack duration is too short for a guarded active plateau"
        )
    if recovery_s <= 2.0:
        raise ValidationError(
            "attack recovery is too short for a guarded recovery window"
        )

    contract: Dict[str, Any] = {
        "name": require_string(attack.get("name"), "task_spec.attack.name"),
        "source": source,
        "mode": mode,
        "severity": require_string(
            attack.get("severity"), "task_spec.attack.severity"
        ),
        "ramp_s": ramp_s,
        "duration_s": duration_s,
        "recovery_s": recovery_s,
    }
    if mode in ("bias", "velocity_bias", "gyro_bias"):
        vector = attack.get("vector")
        if not isinstance(vector, list) or len(vector) != 3:
            raise ValidationError("attack.vector must contain exactly 3 values")
        parsed = [
            finite_float(value, "attack.vector[%d]" % index)
            for index, value in enumerate(vector)
        ]
        if np.linalg.norm(parsed) <= 0.0:
            raise ValidationError("attack.vector must be non-zero")
        contract["vector"] = parsed
    else:
        scalar = finite_float(attack.get("scalar"), "attack.scalar")
        if scalar == 0.0:
            raise ValidationError("attack.scalar must be non-zero")
        contract["scalar"] = scalar
    return contract


def phase_windows(
    started_at_s: float,
    actual_onset_s: float,
    contract: Mapping[str, Any],
) -> Dict[str, Dict[str, float]]:
    onset_abs = started_at_s + actual_onset_s
    ramp = float(contract["ramp_s"])
    duration = float(contract["duration_s"])
    recovery = float(contract["recovery_s"])
    relative = {
        "pre": (-20.0, -5.0),
        "active": (ramp + 2.0, duration - 2.0),
        "recovery": (duration + 1.0, duration + recovery - 1.0),
        # The attack scale is exactly zero here.  This is stable with respect to
        # the source command, although a closed-loop vehicle/EKF may retain a
        # transient aftereffect.
        "stable_post": (
            duration + recovery + 1.0,
            duration + recovery + 11.0,
        ),
    }
    return {
        name: {
            "start_relative_to_onset_s": bounds[0],
            "end_relative_to_onset_s": bounds[1],
            "start_absolute_s": onset_abs + bounds[0],
            "end_absolute_s": onset_abs + bounds[1],
        }
        for name, bounds in relative.items()
    }


def validate_kpi_identity_and_timebase(
    df: pd.DataFrame,
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    manifest: Mapping[str, Any],
    windows: Mapping[str, Mapping[str, float]],
) -> Dict[str, Any]:
    identity_columns = ("run_id", "transport_mode", "world_name")
    missing = [column for column in ("t",) + identity_columns if column not in df]
    if missing:
        raise ValidationError("KPI CSV missing identity/time columns: %s" % missing)
    if df.empty:
        raise ValidationError("KPI CSV is empty")

    for column, expected in (
        ("run_id", result["run_id"]),
        ("transport_mode", task["transport"]),
        ("world_name", task["map"]),
    ):
        values = {
            str(value).strip()
            for value in df[column].dropna().unique()
            if str(value).strip()
        }
        if values != {str(expected)}:
            raise ValidationError(
                "KPI %s identity mismatch: expected %r, got %r"
                % (column, expected, sorted(values))
            )

    numeric_t = pd.to_numeric(df["t"], errors="coerce")
    if numeric_t.isna().any() or not np.isfinite(numeric_t.to_numpy()).all():
        raise ValidationError("KPI t contains non-numeric or non-finite values")
    t = numeric_t.to_numpy(dtype=float)
    dt = np.diff(t)
    if len(dt) == 0 or np.any(dt <= 0.0):
        raise ValidationError("KPI t must be strictly increasing")
    median_dt = float(np.median(dt))
    if median_dt < 0.001 or median_dt > 1.0:
        raise ValidationError(
            "KPI median dt %.6fs is inconsistent with a seconds time base" % median_dt
        )

    started = finite_float(manifest.get("started_at_s"), "manifest.started_at_s")
    ended = finite_float(manifest.get("ended_at_s"), "manifest.ended_at_s")
    duration = finite_float(
        manifest.get("duration_s"), "manifest.duration_s", minimum=0.0
    )
    if ended <= started:
        raise ValidationError("manifest ended_at_s must be after started_at_s")
    if abs((ended - started) - duration) > 0.01:
        raise ValidationError("manifest duration disagrees with start/end timestamps")
    if abs(t[0] - started) > MAX_START_END_ALIGNMENT_ERROR_S:
        raise ValidationError(
            "KPI start %.3f and manifest start %.3f use inconsistent time bases"
            % (t[0], started)
        )
    if abs(t[-1] - ended) > MAX_START_END_ALIGNMENT_ERROR_S:
        raise ValidationError(
            "KPI end %.3f and manifest end %.3f use inconsistent time bases"
            % (t[-1], ended)
        )
    if abs((t[-1] - t[0]) - duration) > MAX_DURATION_ALIGNMENT_ERROR_S:
        raise ValidationError("KPI span and manifest duration disagree")

    actual_onset = finite_float(
        manifest.get("attack_actual_onset_s"),
        "manifest.attack_actual_onset_s",
        minimum=0.0,
    )
    scheduled_onset = finite_float(
        manifest.get("attack_scheduled_onset_s"),
        "manifest.attack_scheduled_onset_s",
        minimum=0.0,
    )
    if actual_onset <= 0.0:
        raise ValidationError("manifest has no positive actual attack onset")
    if abs(actual_onset - scheduled_onset) > MAX_ACTUAL_SCHEDULED_ONSET_ERROR_S:
        raise ValidationError(
            "actual and scheduled onset differ by more than %.1fs"
            % MAX_ACTUAL_SCHEDULED_ONSET_ERROR_S
        )
    onset_abs = started + actual_onset
    if onset_abs < t[0] or onset_abs > t[-1]:
        raise ValidationError("actual attack onset is outside the KPI time range")

    return {
        "t": t,
        "started_at_s": started,
        "ended_at_s": ended,
        "duration_s": duration,
        "actual_onset_s": actual_onset,
        "scheduled_onset_s": scheduled_onset,
        "onset_absolute_s": onset_abs,
        "kpi_t_start_s": float(t[0]),
        "kpi_t_end_s": float(t[-1]),
        "kpi_median_dt_s": median_dt,
        "actual_minus_scheduled_onset_s": actual_onset - scheduled_onset,
        "windows": windows,
    }


def require_numeric_columns(df: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in df]
    if missing:
        raise ValidationError("KPI CSV missing metric columns: %s" % missing)
    for column in columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        df[column] = converted


def pre_mask(
    t: np.ndarray, windows: Mapping[str, Mapping[str, float]]
) -> np.ndarray:
    bounds = windows["pre"]
    return (t >= bounds["start_absolute_s"]) & (t < bounds["end_absolute_s"])


def metric_gps_position_bias(
    df: pd.DataFrame,
    t: np.ndarray,
    windows: Mapping[str, Mapping[str, float]],
    contract: Mapping[str, Any],
) -> Tuple[np.ndarray, Dict[str, Any]]:
    columns = ("gps_lat", "gps_lon", "gps_alt", "px_gt", "py_gt", "pz_gt")
    require_numeric_columns(df, columns)
    mask = pre_mask(t, windows)
    if int(mask.sum()) == 0:
        raise ValidationError("GPS position metric has no pre samples")

    references = {}
    for column in columns:
        value = float(df.loc[mask, column].median(skipna=True))
        if not math.isfinite(value):
            raise ValidationError("GPS position pre reference %s is unavailable" % column)
        references[column] = value
    latitude_rad = math.radians(references["gps_lat"])
    if abs(math.cos(latitude_rad)) < 1.0e-6:
        raise ValidationError("GPS east projection is unstable near the pole")

    east = (
        np.deg2rad(df["gps_lon"].to_numpy() - references["gps_lon"])
        * EARTH_RADIUS_M
        * math.cos(latitude_rad)
    )
    north = (
        np.deg2rad(df["gps_lat"].to_numpy() - references["gps_lat"])
        * EARTH_RADIUS_M
    )
    up = df["gps_alt"].to_numpy() - references["gps_alt"]
    gt_east = df["px_gt"].to_numpy() - references["px_gt"]
    gt_north = df["py_gt"].to_numpy() - references["py_gt"]
    gt_up = df["pz_gt"].to_numpy() - references["pz_gt"]
    residual = np.column_stack(
        (east - gt_east, north - gt_north, up - gt_up)
    )
    vector = np.asarray(contract["vector"], dtype=float)
    command_magnitude = float(np.linalg.norm(vector))
    unit = vector / command_magnitude
    projected = residual @ unit
    return projected, {
        "name": "gps_position_residual_projected_on_command",
        "unit": "m",
        "command_value": command_magnitude,
        "command_direction": list(unit),
        "signed_metric": True,
        "uses_columns": list(columns),
        "ground_truth_columns": ["px_gt", "py_gt", "pz_gt"],
    }


def metric_gps_velocity_bias(
    df: pd.DataFrame,
    _t: np.ndarray,
    _windows: Mapping[str, Mapping[str, float]],
    contract: Mapping[str, Any],
) -> Tuple[np.ndarray, Dict[str, Any]]:
    columns = ("gps_vx", "gps_vy", "vel_x", "vel_y")
    require_numeric_columns(df, columns)
    vector = np.asarray(contract["vector"], dtype=float)
    command_magnitude = float(np.linalg.norm(vector[:2]))
    if command_magnitude <= 0.0 or abs(vector[2]) > 1.0e-12:
        raise ValidationError(
            "GPS velocity evaluator currently requires a non-zero horizontal "
            "command and zero vertical component"
        )
    residual = np.hypot(
        df["gps_vx"].to_numpy() - df["vel_x"].to_numpy(),
        df["gps_vy"].to_numpy() - df["vel_y"].to_numpy(),
    )
    return residual, {
        "name": "horizontal_gps_minus_local_velocity_residual",
        "unit": "m/s",
        "command_value": command_magnitude,
        "signed_metric": False,
        "uses_columns": list(columns),
        "ground_truth_columns": [],
        "interpretation": (
            "Closed-loop EKF/local velocity can follow part of the spoof; "
            "the residual is not a direct estimate of injected magnitude."
        ),
    }


def metric_imu_gyro_bias(
    df: pd.DataFrame,
    t: np.ndarray,
    _windows: Mapping[str, Mapping[str, float]],
    contract: Mapping[str, Any],
) -> Tuple[np.ndarray, Dict[str, Any]]:
    columns = ("yaw", "ang_vel_z")
    require_numeric_columns(df, columns)
    if df[list(columns)].isna().any().any():
        raise ValidationError("IMU gyro metric columns contain missing values")
    vector = np.asarray(contract["vector"], dtype=float)
    if np.linalg.norm(vector[:2]) > 1.0e-12 or abs(vector[2]) <= 0.0:
        raise ValidationError(
            "IMU evaluator currently supports a non-zero z gyro bias only"
        )
    yaw = np.unwrap(df["yaw"].to_numpy(dtype=float))
    yaw_rate = np.gradient(yaw, t)
    yaw_rate = (
        pd.Series(yaw_rate)
        .rolling(window=5, center=True, min_periods=3)
        .median()
        .to_numpy()
    )
    residual = df["ang_vel_z"].to_numpy(dtype=float) - yaw_rate
    return residual, {
        "name": "signed_gyro_z_minus_pose_yaw_rate",
        "unit": "rad/s",
        "command_value": float(vector[2]),
        "signed_metric": True,
        "uses_columns": list(columns),
        "ground_truth_columns": [],
        "interpretation": (
            "Pose yaw-rate is an estimated closed-loop reference; this residual "
            "can be attenuated relative to the source command."
        ),
    }


def metric_barometer_drift(
    df: pd.DataFrame,
    t: np.ndarray,
    windows: Mapping[str, Mapping[str, float]],
    contract: Mapping[str, Any],
) -> Tuple[np.ndarray, Dict[str, Any]]:
    columns = ("static_pressure", "pz_gt")
    require_numeric_columns(df, columns)
    mask = pre_mask(t, windows)
    pressure_reference = float(
        df.loc[mask, "static_pressure"].median(skipna=True)
    )
    z_reference = float(df.loc[mask, "pz_gt"].median(skipna=True))
    if not math.isfinite(pressure_reference) or pressure_reference <= 0.0:
        raise ValidationError("barometer pre pressure reference is unavailable")
    if not math.isfinite(z_reference):
        raise ValidationError("barometer pre ground-truth z is unavailable")
    pressure = df["static_pressure"].to_numpy(dtype=float)
    if np.any(pressure[np.isfinite(pressure)] <= 0.0):
        raise ValidationError("static pressure contains non-positive values")
    pressure_altitude = 44330.0 * (
        1.0 - np.power(pressure / pressure_reference, 0.1903)
    )
    gt_altitude = df["pz_gt"].to_numpy(dtype=float) - z_reference
    residual = pressure_altitude - gt_altitude
    return residual, {
        "name": "barometer_altitude_minus_ground_truth_altitude",
        "unit": "m",
        "command_value": float(contract["scalar"]),
        "signed_metric": True,
        "uses_columns": list(columns),
        "ground_truth_columns": ["pz_gt"],
    }


METRIC_BUILDERS = {
    ("gps", "bias"): metric_gps_position_bias,
    ("gps", "velocity_bias"): metric_gps_velocity_bias,
    ("imu", "gyro_bias"): metric_imu_gyro_bias,
    ("barometer", "drift"): metric_barometer_drift,
}


def cliffs_delta(active: np.ndarray, pre: np.ndarray) -> float:
    """Exact Cliff's delta without allocating an n×m comparison matrix."""
    a = np.asarray(active, dtype=float)
    b = np.asarray(pre, dtype=float)
    a = a[np.isfinite(a)]
    b = np.sort(b[np.isfinite(b)])
    if len(a) == 0 or len(b) == 0:
        raise ValidationError("Cliff's delta needs non-empty finite samples")
    less = np.searchsorted(b, a, side="left").sum()
    greater = (len(b) - np.searchsorted(b, a, side="right")).sum()
    return float((less - greater) / (len(a) * len(b)))


def phase_statistics(
    metric: np.ndarray,
    t: np.ndarray,
    windows: Mapping[str, Mapping[str, float]],
    min_samples: int,
    min_span_s: float,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, np.ndarray]]:
    statistics: Dict[str, Dict[str, Any]] = {}
    samples: Dict[str, np.ndarray] = {}
    for name in ("pre", "active", "recovery", "stable_post"):
        bounds = windows[name]
        mask = (
            (t >= bounds["start_absolute_s"])
            & (t < bounds["end_absolute_s"])
            & np.isfinite(metric)
        )
        values = np.asarray(metric[mask], dtype=float)
        times = np.asarray(t[mask], dtype=float)
        if len(values) < min_samples:
            raise ValidationError(
                "%s window has %d finite samples; minimum is %d"
                % (name, len(values), min_samples)
            )
        span = float(times[-1] - times[0]) if len(times) >= 2 else 0.0
        if span < min_span_s:
            raise ValidationError(
                "%s window spans %.3fs; minimum is %.3fs"
                % (name, span, min_span_s)
            )
        statistics[name] = {
            "sample_count": int(len(values)),
            "observed_span_s": span,
            "median": float(np.median(values)),
            "q1": float(np.quantile(values, 0.25)),
            "q3": float(np.quantile(values, 0.75)),
        }
        samples[name] = values
    return statistics, samples


def compute_effects(
    phase_stats: Mapping[str, Mapping[str, Any]],
    phase_samples: Mapping[str, np.ndarray],
    metric_info: Mapping[str, Any],
    kind: Tuple[str, str],
) -> Dict[str, Any]:
    pre = float(phase_stats["pre"]["median"])
    active = float(phase_stats["active"]["median"])
    recovery = float(phase_stats["recovery"]["median"])
    stable = float(phase_stats["stable_post"]["median"])
    delta = active - pre
    command = finite_float(metric_info["command_value"], "metric.command_value")
    if command == 0.0:
        raise ValidationError("metric command value must be non-zero")

    signed = bool(metric_info["signed_metric"])
    orientation = math.copysign(1.0, command) if signed else 1.0
    oriented_delta = delta * orientation
    command_magnitude = abs(command)
    command_fraction = oriented_delta / command_magnitude
    raw_cliff = cliffs_delta(phase_samples["active"], phase_samples["pre"])
    oriented_cliff = raw_cliff * orientation

    pre_values = phase_samples["pre"]
    pre_mad = float(
        1.4826 * np.median(np.abs(pre_values - np.median(pre_values)))
    )
    robust_effect = oriented_delta / pre_mad if pre_mad > 0.0 else None

    thresholds = EFFECT_THRESHOLDS[kind]
    checks = {
        "command_fraction": {
            "value": command_fraction,
            "minimum": thresholds["minimum_command_fraction"],
            "passed": command_fraction
            >= thresholds["minimum_command_fraction"],
        },
        "oriented_cliffs_delta": {
            "value": oriented_cliff,
            "minimum": thresholds["minimum_oriented_cliffs_delta"],
            "passed": oriented_cliff
            >= thresholds["minimum_oriented_cliffs_delta"],
        },
    }
    # Position and barometer metrics are direct source-vs-ground-truth
    # measurements.  For those two modes, also prove that the configured
    # recovery tail and source-off window occurred.  GPS velocity and IMU use
    # closed-loop estimator references, so immediate post-attack transients are
    # reported but are not treated as a plugin-lifecycle failure.
    recovery_fraction = (
        (recovery - pre) * orientation / oriented_delta
        if oriented_delta != 0.0
        else None
    )
    stable_fraction = (
        (stable - pre) * orientation / oriented_delta
        if oriented_delta != 0.0
        else None
    )
    if kind in (("gps", "bias"), ("barometer", "drift")):
        recovery_passed = (
            recovery_fraction is not None
            and 0.10 <= recovery_fraction <= 0.90
        )
        stable_passed = (
            stable_fraction is not None and abs(stable_fraction) <= 0.25
        )
        checks["recovery_tail_fraction"] = {
            "value": recovery_fraction,
            "minimum": 0.10,
            "maximum": 0.90,
            "passed": recovery_passed,
        }
        checks["stable_post_absolute_fraction"] = {
            "value": abs(stable_fraction) if stable_fraction is not None else None,
            "maximum": 0.25,
            "passed": stable_passed,
        }
    verified = all(item["passed"] for item in checks.values())
    return {
        "active_minus_pre": delta,
        "oriented_active_minus_pre": oriented_delta,
        "active_command_fraction": command_fraction,
        "cliffs_delta_active_vs_pre": raw_cliff,
        "oriented_cliffs_delta_active_vs_pre": oriented_cliff,
        "pre_mad_scaled": pre_mad,
        "robust_effect_vs_pre_mad": robust_effect,
        "recovery_minus_pre": recovery - pre,
        "stable_post_minus_pre": stable - pre,
        "recovery_fraction_of_active_effect": recovery_fraction,
        "stable_post_fraction_of_active_effect": stable_fraction,
        "verification_checks": checks,
        "effect_verified": verified,
    }


def validate_metadata(
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    assert_equal(
        task.get("profile"), contract["name"], "task_spec.profile/attack.name"
    )
    assert_equal(
        task.get("severity"),
        contract["severity"],
        "task_spec.severity/attack.severity",
    )
    assert_equal(result.get("task_id"), task.get("task_id"), "result.task_id")
    assert_equal(result.get("profile"), task.get("profile"), "result.profile")
    assert_equal(result.get("map"), task.get("map"), "result.map")
    assert_equal(result.get("seed"), task.get("seed"), "result.seed")
    assert_equal(
        result.get("transport"), task.get("transport"), "result.transport"
    )
    assert_equal(result.get("source"), contract["source"], "result.source")
    assert_equal(result.get("mode"), contract["mode"], "result.mode")
    assert_equal(
        result.get("severity"), contract["severity"], "result.severity"
    )

    assert_equal(
        manifest.get("scenario"), "attack_pilot", "manifest.scenario"
    )
    assert_equal(
        manifest.get("transport_mode"),
        task.get("transport"),
        "manifest.transport_mode",
    )
    assert_equal(
        manifest.get("world_name"), task.get("map"), "manifest.world_name"
    )
    assert_equal(
        manifest.get("attack_source"),
        contract["source"],
        "manifest.attack_source",
    )
    assert_equal(
        manifest.get("attack_mode"), contract["mode"], "manifest.attack_mode"
    )
    assert_equal(
        manifest.get("attack_severity"),
        contract["severity"],
        "manifest.attack_severity",
    )
    assert_equal(
        manifest.get("attack_seed"), task.get("seed"), "manifest.attack_seed"
    )
    assert_equal(
        manifest.get("outcome"), result.get("outcome"), "manifest.outcome"
    )
    if not manifest_bool(manifest.get("log_retained"), "manifest.log_retained"):
        raise ValidationError("manifest says the KPI log was not retained")
    if manifest_bool(manifest.get("log_deleted"), "manifest.log_deleted"):
        raise ValidationError("manifest says the KPI log was deleted")

    result_onset = finite_float(
        result.get("actual_onset_s"), "result.actual_onset_s", minimum=0.0
    )
    manifest_onset = finite_float(
        manifest.get("attack_actual_onset_s"),
        "manifest.attack_actual_onset_s",
        minimum=0.0,
    )
    if abs(result_onset - manifest_onset) > 0.001:
        raise ValidationError("result and manifest actual onset disagree")
    result_scheduled = finite_float(
        result.get("scheduled_onset_s"), "result.scheduled_onset_s", minimum=0.0
    )
    manifest_scheduled = finite_float(
        manifest.get("attack_scheduled_onset_s"),
        "manifest.attack_scheduled_onset_s",
        minimum=0.0,
    )
    if abs(result_scheduled - manifest_scheduled) > 0.001:
        raise ValidationError("result and manifest scheduled onset disagree")
    result_duration = finite_float(
        result.get("duration_s"), "result.duration_s", minimum=0.0
    )
    manifest_duration = finite_float(
        manifest.get("duration_s"), "manifest.duration_s", minimum=0.0
    )
    if abs(result_duration - manifest_duration) > 0.001:
        raise ValidationError("result and manifest duration disagree")


def analyze_task(
    task_dir: Path,
    min_phase_samples: int = DEFAULT_MIN_PHASE_SAMPLES,
    min_phase_span_s: float = DEFAULT_MIN_PHASE_SPAN_S,
) -> Dict[str, Any]:
    task_path = task_dir / "task_spec.json"
    result_path = task_dir / "attempt_result.json"
    manifest_path = task_dir / "run_manifest.csv"
    task = load_json(task_path, "task spec")
    result = load_json(result_path, "attempt result")

    # Callers normally filter before analyze_task; keep this guard so direct use
    # cannot accidentally analyze an ineligible attempt.
    if result.get("state") != "completed":
        raise ValidationError("attempt state is not completed")
    if not require_bool(result.get("log_retained"), "result.log_retained"):
        raise ValidationError("attempt result is not retained")
    if not require_bool(result.get("attributable"), "result.attributable"):
        raise ValidationError("attempt result is not attributable")

    task_id = require_string(task.get("task_id"), "task_spec.task_id")
    if task_dir.name != task_id:
        raise ValidationError(
            "task directory name does not match task_spec.task_id"
        )
    run_id = require_string(result.get("run_id"), "result.run_id")
    manifest = read_matching_manifest_row(manifest_path, run_id)
    contract = profile_contract(task)
    validate_metadata(task, result, manifest, contract)

    started_at = finite_float(manifest.get("started_at_s"), "manifest.started_at_s")
    actual_onset = finite_float(
        manifest.get("attack_actual_onset_s"),
        "manifest.attack_actual_onset_s",
        minimum=0.0,
    )
    windows = phase_windows(started_at, actual_onset, contract)

    expected_kpi = (task_dir / ("kpi_log_%s.csv" % run_id)).resolve()
    result_kpi = Path(require_string(result.get("kpi_path"), "result.kpi_path")).resolve()
    if result_kpi != expected_kpi:
        raise ValidationError(
            "result KPI path does not match task-local expected path"
        )
    if not expected_kpi.is_file():
        raise ValidationError("retained KPI CSV is missing: %s" % expected_kpi)
    try:
        df = pd.read_csv(expected_kpi)
    except Exception as exc:
        raise ValidationError("KPI CSV is unreadable: %s" % exc)

    timebase = validate_kpi_identity_and_timebase(
        df, task, result, manifest, windows
    )
    t = timebase.pop("t")
    kind = (contract["source"], contract["mode"])
    metric, metric_info = METRIC_BUILDERS[kind](
        df, t, windows, contract
    )
    phase_stats, phase_samples = phase_statistics(
        metric,
        t,
        windows,
        min_phase_samples,
        min_phase_span_s,
    )
    effects = compute_effects(
        phase_stats, phase_samples, metric_info, kind
    )

    return {
        "task_id": task_id,
        "task_status": (
            "verified" if effects["effect_verified"] else "effect_not_verified"
        ),
        "profile": contract["name"],
        "source": contract["source"],
        "mode": contract["mode"],
        "severity": contract["severity"],
        "seed": int(task["seed"]),
        "map": task["map"],
        "transport": task["transport"],
        "run_id": run_id,
        "outcome": result["outcome"],
        "attributable": True,
        "log_retained": True,
        "profile_lifecycle": {
            "ramp_s": contract["ramp_s"],
            "duration_s": contract["duration_s"],
            "recovery_s": contract["recovery_s"],
        },
        "timing": timebase,
        "phase_windows": windows,
        "metric": {
            **metric_info,
            "evaluation_only": True,
            "eligible_for_model_input": False,
        },
        "phase_statistics": phase_stats,
        "effects": effects,
        "provenance": {
            "task_spec_path": str(task_path.resolve()),
            "task_spec_sha256": sha256_file(task_path),
            "attempt_result_path": str(result_path.resolve()),
            "attempt_result_sha256": sha256_file(result_path),
            "run_manifest_path": str(manifest_path.resolve()),
            "run_manifest_sha256": sha256_file(manifest_path),
            "kpi_path": str(expected_kpi),
            "kpi_sha256": sha256_file(expected_kpi),
        },
    }


def ineligible_reason(result: Mapping[str, Any]) -> Optional[str]:
    if result.get("state") != "completed":
        return "state_not_completed"
    if result.get("log_retained") is not True:
        return "log_not_retained"
    if result.get("attributable") is not True:
        return "not_attributable"
    return None


def validate_campaign(
    campaign_dir: Path,
    min_phase_samples: int = DEFAULT_MIN_PHASE_SAMPLES,
    min_phase_span_s: float = DEFAULT_MIN_PHASE_SPAN_S,
) -> Dict[str, Any]:
    campaign_dir = campaign_dir.expanduser().resolve()
    runs_dir = campaign_dir / "runs"
    if not runs_dir.is_dir():
        raise ValidationError("campaign runs directory is missing: %s" % runs_dir)
    if min_phase_samples < 2:
        raise ValidationError("min_phase_samples must be at least 2")
    if min_phase_span_s <= 0.0:
        raise ValidationError("min_phase_span_s must be positive")

    plan_path = campaign_dir / "campaign_plan.json"
    plan = load_json(plan_path, "campaign plan") if plan_path.is_file() else {}
    task_dirs = sorted(
        path for path in runs_dir.iterdir() if path.is_dir()
    )
    tasks: List[Dict[str, Any]] = []
    invalid_tasks: List[Dict[str, Any]] = []
    skipped_tasks: List[Dict[str, Any]] = []
    eligible_count = 0

    for task_dir in task_dirs:
        result_path = task_dir / "attempt_result.json"
        if not result_path.is_file():
            skipped_tasks.append(
                {"task_id": task_dir.name, "reason": "attempt_result_missing"}
            )
            continue
        try:
            result = load_json(result_path, "attempt result")
        except ValidationError as exc:
            invalid_tasks.append(
                {"task_id": task_dir.name, "errors": [str(exc)]}
            )
            continue
        except (KeyError, TypeError, ValueError, OSError) as exc:
            invalid_tasks.append(
                {
                    "task_id": task_dir.name,
                    "errors": [
                        "unexpected malformed task input: %s" % exc
                    ],
                }
            )
            continue
        reason = ineligible_reason(result)
        if reason is not None:
            skipped_tasks.append({"task_id": task_dir.name, "reason": reason})
            continue
        eligible_count += 1
        try:
            tasks.append(
                analyze_task(
                    task_dir,
                    min_phase_samples=min_phase_samples,
                    min_phase_span_s=min_phase_span_s,
                )
            )
        except ValidationError as exc:
            invalid_tasks.append(
                {"task_id": task_dir.name, "errors": [str(exc)]}
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            invalid_tasks.append(
                {
                    "task_id": task_dir.name,
                    "errors": [
                        "unexpected malformed task input: %s" % exc
                    ],
                }
            )

    if eligible_count == 0:
        raise ValidationError(
            "no completed + retained + attributable attempts were found"
        )

    verified = sum(task["task_status"] == "verified" for task in tasks)
    unverified = sum(
        task["task_status"] == "effect_not_verified" for task in tasks
    )
    all_verified = (
        eligible_count > 0
        and verified == eligible_count
        and not invalid_tasks
        and unverified == 0
    )
    gt_columns = sorted(
        {
            column
            for task in tasks
            for column in task["metric"]["ground_truth_columns"]
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "validator": {
            "script": str(Path(__file__).resolve()),
            "script_sha256": sha256_file(Path(__file__).resolve()),
        },
        "campaign_dir": str(campaign_dir),
        "campaign_id": plan.get("campaign_id", campaign_dir.name),
        "campaign_plan_digest": plan.get("plan_digest"),
        "evaluation_only": True,
        "ground_truth_policy": {
            "ground_truth_columns_used": gt_columns,
            "allowed_purpose": "simulator injection-effect validation only",
            "eligible_for_model_input": False,
        },
        "phase_policy": {
            "pre_relative_to_onset_s": [-20.0, -5.0],
            "active_relative_to_onset_s": [
                "ramp_s + 2.0",
                "duration_s - 2.0",
            ],
            "recovery_relative_to_onset_s": [
                "duration_s + 1.0",
                "duration_s + recovery_s - 1.0",
            ],
            "stable_post_relative_to_onset_s": [
                "duration_s + recovery_s + 1.0",
                "duration_s + recovery_s + 11.0",
            ],
            "stable_post_interpretation": (
                "attack source command is off; closed-loop estimator or vehicle "
                "transients may remain"
            ),
            "minimum_phase_samples": min_phase_samples,
            "minimum_phase_span_s": min_phase_span_s,
        },
        "summary": {
            "discovered_task_directories": len(task_dirs),
            "eligible_tasks": eligible_count,
            "validly_analyzed_tasks": len(tasks),
            "verified_effect_tasks": verified,
            "effect_not_verified_tasks": unverified,
            "invalid_tasks": len(invalid_tasks),
            "skipped_ineligible_tasks": len(skipped_tasks),
            "all_eligible_effects_verified": all_verified,
        },
        "tasks": tasks,
        "invalid_tasks": invalid_tasks,
        "skipped_tasks": skipped_tasks,
    }


def format_number(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return ("%.*f" % (digits, float(value))).rstrip("0").rstrip(".")


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# LAEA attack pilot effect validation",
        "",
        "- Campaign: `%s`" % report["campaign_id"],
        "- Evaluation only: **yes**",
        "- Verified effects: **%d/%d**"
        % (summary["verified_effect_tasks"], summary["eligible_tasks"]),
        "- All eligible effects verified: **%s**"
        % ("yes" if summary["all_eligible_effects_verified"] else "no"),
        "",
        "| Task | Metric | Onset (s) | Pre median | Active median | Recovery median | Stable-post median | Active−pre | Cliff's δ | Result |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for task in report["tasks"]:
        stats = task["phase_statistics"]
        effects = task["effects"]
        lines.append(
            "| `%s` | %s (%s) | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                task["task_id"],
                task["metric"]["name"],
                task["metric"]["unit"],
                format_number(task["timing"]["actual_onset_s"], 3),
                format_number(stats["pre"]["median"]),
                format_number(stats["active"]["median"]),
                format_number(stats["recovery"]["median"]),
                format_number(stats["stable_post"]["median"]),
                format_number(effects["active_minus_pre"]),
                format_number(effects["cliffs_delta_active_vs_pre"], 3),
                task["task_status"],
            )
        )
    if report["invalid_tasks"]:
        lines.extend(["", "## Invalid tasks", ""])
        for item in report["invalid_tasks"]:
            lines.append(
                "- `%s`: %s" % (item["task_id"], "; ".join(item["errors"]))
            )
    if report["skipped_tasks"]:
        lines.extend(["", "## Skipped ineligible tasks", ""])
        for item in report["skipped_tasks"]:
            lines.append("- `%s`: %s" % (item["task_id"], item["reason"]))
    lines.extend(
        [
            "",
            "> Ground-truth fields are used only for simulator evaluation and "
            "must never be detector/model inputs.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate source-layer effects in retained attack pilot KPI logs."
    )
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Atomic JSON output.")
    parser.add_argument(
        "--markdown-out",
        type=Path,
        help="Optional atomic Markdown summary output.",
    )
    parser.add_argument(
        "--min-phase-samples",
        type=int,
        default=DEFAULT_MIN_PHASE_SAMPLES,
    )
    parser.add_argument(
        "--min-phase-span-s",
        type=float,
        default=DEFAULT_MIN_PHASE_SPAN_S,
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        report = validate_campaign(
            args.campaign_dir,
            min_phase_samples=args.min_phase_samples,
            min_phase_span_s=args.min_phase_span_s,
        )
        atomic_write_json(args.out.expanduser().resolve(), report)
        if args.markdown_out is not None:
            atomic_write_text(
                args.markdown_out.expanduser().resolve(),
                render_markdown(report),
            )
        summary = report["summary"]
        print(
            "[attack_effects] verified=%d/%d invalid=%d unverified=%d"
            % (
                summary["verified_effect_tasks"],
                summary["eligible_tasks"],
                summary["invalid_tasks"],
                summary["effect_not_verified_tasks"],
            )
        )
        print("[attack_effects] JSON: %s" % args.out.expanduser().resolve())
        if args.markdown_out is not None:
            print(
                "[attack_effects] Markdown: %s"
                % args.markdown_out.expanduser().resolve()
            )
        if summary["invalid_tasks"]:
            return 2
        if not summary["all_eligible_effects_verified"]:
            return 3
        return 0
    except ValidationError as exc:
        print("[attack_effects] ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
