#!/usr/bin/env python3
import argparse
import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_COLS = [
    "t",
    "pos_x", "pos_y", "pos_z",
    "vel_x", "vel_y", "vel_z",
    "yaw",
    "gps_lat", "gps_lon", "gps_alt",
    "gps_vx", "gps_vy", "gps_vz",
    "gps_fix", "gps_sat",
]


def wrap_to_pi(angle_rad):
    return (angle_rad + np.pi) % (2 * np.pi) - np.pi


def compute_gps_step_m(df):
    # Equirectangular approximation, good for short frame-to-frame deltas.
    r_earth = 6378137.0
    lat = np.deg2rad(df["gps_lat"].to_numpy())
    lon = np.deg2rad(df["gps_lon"].to_numpy())
    alt = df["gps_alt"].to_numpy()

    dlat = np.diff(lat, prepend=np.nan)
    dlon = np.diff(lon, prepend=np.nan)
    lat_mid = (lat + np.roll(lat, 1)) * 0.5
    lat_mid[0] = np.nan

    dx = r_earth * dlon * np.cos(lat_mid)
    dy = r_earth * dlat
    dz = np.diff(alt, prepend=np.nan)
    return np.sqrt(dx * dx + dy * dy + dz * dz)


def build_features(df, gps_fix_threshold=2, heading_speed_eps=0.2):
    out = df.copy()

    out["local_speed"] = np.sqrt(out["vel_x"] ** 2 + out["vel_y"] ** 2 + out["vel_z"] ** 2)
    out["gps_speed"] = np.sqrt(out["gps_vx"] ** 2 + out["gps_vy"] ** 2 + out["gps_vz"] ** 2)
    out["speed_gap"] = np.abs(out["local_speed"] - out["gps_speed"])
    out["vertical_speed_gap"] = np.abs(out["vel_z"] - out["gps_vz"])

    gps_heading = np.arctan2(out["gps_vy"], out["gps_vx"])
    moving_mask = out["gps_speed"] > heading_speed_eps
    out["gps_heading"] = np.where(moving_mask, gps_heading, np.nan)
    out["heading_gap"] = np.abs(wrap_to_pi(out["gps_heading"] - out["yaw"]))

    out["local_step_m"] = np.sqrt(
        out["pos_x"].diff() ** 2 + out["pos_y"].diff() ** 2 + out["pos_z"].diff() ** 2
    )
    out["gps_step_m"] = compute_gps_step_m(out)
    out["step_gap"] = np.abs(out["gps_step_m"] - out["local_step_m"])

    out["sat_change"] = out["gps_sat"].diff()
    out["sat_drop"] = (-out["sat_change"]).clip(lower=0.0)
    out["fix_bad"] = (out["gps_fix"] < gps_fix_threshold).astype(int)

    out["dt"] = out["t"].diff()
    return out


def resolve_inputs(inputs):
    files = []
    for pattern in inputs:
        matched = glob.glob(pattern)
        if matched:
            files.extend(matched)
        else:
            p = Path(pattern)
            if p.exists() and p.is_file():
                files.append(str(p))
    return sorted(set(files))


def load_one_csv(path):
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")

    df = df[REQUIRED_COLS].copy()
    for c in REQUIRED_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("t").reset_index(drop=True)
    df["mission_id"] = Path(path).stem
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Build GPS anomaly-detection features from kpi_log CSV files."
    )
    parser.add_argument(
        "--input",
        nargs="+",
        default=["/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/kpi_log_*.csv"],
        help="Input CSV file(s) or glob(s).",
    )
    parser.add_argument("--out", required=True, help="Output feature CSV path.")
    parser.add_argument(
        "--gps-fix-threshold",
        type=int,
        default=2,
        help="gps_fix below this value is considered bad.",
    )
    parser.add_argument(
        "--heading-speed-eps",
        type=float,
        default=0.2,
        help="Minimum GPS speed (m/s) to compute heading_gap.",
    )
    parser.add_argument(
        "--drop-na",
        action="store_true",
        help="Drop rows with NaN after feature construction.",
    )
    parser.add_argument(
        "--label-value",
        type=int,
        default=0,
        help="Optional label value to append (normal=0 by default).",
    )
    args = parser.parse_args()

    files = resolve_inputs(args.input)
    if not files:
        raise SystemExit("No input files found.")

    frames = []
    for f in files:
        df = load_one_csv(f)
        feat = build_features(
            df,
            gps_fix_threshold=args.gps_fix_threshold,
            heading_speed_eps=args.heading_speed_eps,
        )
        frames.append(feat)

    out_df = pd.concat(frames, ignore_index=True)
    out_df["label"] = int(args.label_value)

    if args.drop_na:
        out_df = out_df.dropna(axis=0, how="any")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    print(f"[build_gps_features] input_files={len(files)} rows={len(out_df)}")
    print(f"[build_gps_features] output={out_path}")


if __name__ == "__main__":
    main()
