#!/usr/bin/env python3
import argparse
import glob
from pathlib import Path

import numpy as np
import pandas as pd


GPS_COLS = [
    "gps_lat",
    "gps_lon",
    "gps_alt",
    "gps_vx",
    "gps_vy",
    "gps_vz",
    "gps_fix",
    "gps_sat",
]

REQUIRED_COLS = ["t", "e_pos"] + GPS_COLS


def resolve_inputs(inputs):
    files = []
    for pattern in inputs:
        matched = glob.glob(pattern)
        if matched:
            files.extend(matched)
            continue
        path = Path(pattern)
        if path.is_file():
            files.append(str(path))
    return sorted(set(files))


def safe_quantile(series, q):
    vals = series.dropna().to_numpy()
    if len(vals) == 0:
        return np.nan
    return float(np.quantile(vals, q))


def summarize_one(path, args):
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")

    for col in REQUIRED_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("t").reset_index(drop=True)

    t = df["t"]
    dt = t.diff()
    gps_all_nan = df[GPS_COLS].isna().all(axis=1)

    summary = {
        "mission_id": Path(path).stem,
        "file_path": str(Path(path).resolve()),
        "num_rows": int(len(df)),
        "t_start": float(t.iloc[0]) if len(df) else np.nan,
        "t_end": float(t.iloc[-1]) if len(df) else np.nan,
        "duration_s": float(t.iloc[-1] - t.iloc[0]) if len(df) >= 2 else 0.0,
        "dt_min": float(dt.dropna().min()) if dt.notna().any() else np.nan,
        "dt_mean": float(dt.dropna().mean()) if dt.notna().any() else np.nan,
        "dt_max": float(dt.dropna().max()) if dt.notna().any() else np.nan,
        "zero_dt_count": int((dt == 0).sum()),
        "negative_dt_count": int((dt < 0).sum()),
        "gps_nan_ratio": float(gps_all_nan.mean()) if len(df) else 1.0,
        "gps_valid_ratio": float((~gps_all_nan).mean()) if len(df) else 0.0,
        "e_pos_mean": float(df["e_pos"].mean()),
        "e_pos_p95": safe_quantile(df["e_pos"], 0.95),
        "e_pos_max": float(df["e_pos"].max()),
    }

    quality_ok = True
    if summary["num_rows"] < args.min_rows:
        quality_ok = False
    if summary["duration_s"] < args.min_duration_s:
        quality_ok = False
    if summary["gps_nan_ratio"] > args.max_gps_nan_ratio:
        quality_ok = False
    if summary["e_pos_p95"] > args.max_e_pos_p95:
        quality_ok = False
    if summary["e_pos_max"] > args.max_e_pos_max:
        quality_ok = False
    if summary["negative_dt_count"] > 0:
        quality_ok = False

    summary["quality_ok"] = int(quality_ok)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Build per-run manifest and quality flags from kpi_log CSV files."
    )
    parser.add_argument(
        "--input",
        nargs="+",
        default=["/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip/kpi_log_run_*.csv"],
        help="Input CSV file(s) or glob(s).",
    )
    parser.add_argument("--out", required=True, help="Output manifest CSV path.")
    parser.add_argument(
        "--min-rows",
        type=int,
        default=2000,
        help="Minimum rows required for quality_ok.",
    )
    parser.add_argument(
        "--min-duration-s",
        type=float,
        default=120.0,
        help="Minimum mission duration required for quality_ok.",
    )
    parser.add_argument(
        "--max-gps-nan-ratio",
        type=float,
        default=0.05,
        help="Maximum allowed ratio of rows with all GPS fields missing.",
    )
    parser.add_argument(
        "--max-e-pos-p95",
        type=float,
        default=1.0,
        help="Maximum allowed 95th percentile of e_pos for quality_ok.",
    )
    parser.add_argument(
        "--max-e-pos-max",
        type=float,
        default=2.0,
        help="Maximum allowed max e_pos for quality_ok.",
    )
    args = parser.parse_args()

    files = resolve_inputs(args.input)
    if not files:
        raise SystemExit("No input files found.")

    rows = []
    for path in files:
        try:
            rows.append(summarize_one(path, args))
        except Exception as exc:
            print(f"[build_run_manifest] skip {path}: {exc}")

    if not rows:
        raise SystemExit("No valid input files after parsing.")

    out_df = pd.DataFrame(rows).sort_values("mission_id").reset_index(drop=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    kept = int(out_df["quality_ok"].sum())
    print(f"[build_run_manifest] runs={len(out_df)} quality_ok={kept}")
    print(f"[build_run_manifest] output={out_path}")


if __name__ == "__main__":
    main()
