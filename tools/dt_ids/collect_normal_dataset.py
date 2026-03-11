#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

import pandas as pd
import yaml


def load_feature_set(path: Path, name: str):
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if "feature_sets" not in cfg or name not in cfg["feature_sets"]:
        raise ValueError(f"Feature set '{name}' not found in {path}")
    return cfg["feature_sets"][name]


def resolve_log_dir(p: Path):
    if p.is_dir():
        return p
    if p.name != "nosip":
        nosip = p / "nosip"
        if nosip.is_dir():
            return nosip
    # fallback for historical path without workspace /LAEA
    alt = Path("/home/tim/laea/src/laea_twin_tools/laea_logs")
    if alt.is_dir():
        return alt
    alt_nosip = Path("/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip")
    if alt_nosip.is_dir():
        return alt_nosip
    return p


def main():
    parser = argparse.ArgumentParser(
        description="Collect normal-flight training data from laea_twin_tools KPI logs."
    )
    parser.add_argument(
        "--log-dir",
        default="/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip",
        help="Directory containing kpi_log_*.csv",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output CSV path (e.g., data/normal.csv)",
    )
    parser.add_argument(
        "--feature-set",
        required=True,
        help="Feature set name from tools/dt_ids/feature_sets.yaml",
    )
    parser.add_argument(
        "--features-yaml",
        default="tools/dt_ids/feature_sets.yaml",
        help="Path to feature_sets.yaml",
    )
    parser.add_argument(
        "--label-col",
        default="label",
        help="Label column name to add",
    )
    parser.add_argument(
        "--label-value",
        type=int,
        default=0,
        help="Label value for normal samples",
    )
    parser.add_argument(
        "--max-e-pos",
        type=float,
        default=None,
        help="Optional max e_pos filter (drop rows with e_pos > threshold)",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=0,
        help="Optional minimum rows per file (skip if fewer)",
    )
    parser.add_argument(
        "--include-mission-id",
        action="store_true",
        help="Append mission_id column derived from each source CSV filename.",
    )
    args = parser.parse_args()

    log_dir = resolve_log_dir(Path(args.log_dir))
    if not log_dir.is_dir():
        raise SystemExit(f"log_dir not found: {log_dir}")

    features = load_feature_set(Path(args.features_yaml), args.feature_set)
    needed_cols = ["t"] + features
    if args.max_e_pos is not None:
        needed_cols.append("e_pos")

    files = sorted(log_dir.glob("kpi_log_*.csv"))
    if not files:
        raise SystemExit(f"No kpi_log_*.csv found in {log_dir}")

    frames = []
    skipped = 0
    for path in files:
        try:
            df = pd.read_csv(path)
        except Exception as e:
            print(f"[collect] skip {path.name}: read error {e}", file=sys.stderr)
            skipped += 1
            continue

        missing = [c for c in needed_cols if c not in df.columns]
        if missing:
            print(f"[collect] skip {path.name}: missing columns {missing}", file=sys.stderr)
            skipped += 1
            continue

        sub = df[needed_cols].copy()
        if args.max_e_pos is not None:
            sub = sub[sub["e_pos"] <= args.max_e_pos]
            sub = sub.drop(columns=["e_pos"])

        # drop rows with NaN in any feature
        sub = sub.dropna(axis=0, how="any")

        if args.min_rows and len(sub) < args.min_rows:
            print(f"[collect] skip {path.name}: rows {len(sub)} < min_rows", file=sys.stderr)
            skipped += 1
            continue

        if args.include_mission_id:
            sub["mission_id"] = path.stem

        frames.append(sub)

    if not frames:
        raise SystemExit("No valid logs after filtering.")

    out = pd.concat(frames, ignore_index=True)
    out[args.label_col] = int(args.label_value)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    print(f"[collect] wrote {len(out)} rows to {out_path}")
    print(f"[collect] used {len(frames)} files, skipped {skipped}")


if __name__ == "__main__":
    main()
