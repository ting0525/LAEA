#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def normalized_ratios(train_ratio, val_ratio, test_ratio):
    total = train_ratio + val_ratio + test_ratio
    if total <= 0:
        raise ValueError("Split ratios must sum to a positive value.")
    return train_ratio / total, val_ratio / total, test_ratio / total


def main():
    parser = argparse.ArgumentParser(
        description="Split a dataset by mission_id so runs do not leak across splits."
    )
    parser.add_argument("--input", required=True, help="Input CSV containing mission_id.")
    parser.add_argument("--out-dir", required=True, help="Output directory for split CSV files.")
    parser.add_argument(
        "--prefix",
        default="dataset",
        help="Output prefix, e.g. dataset -> dataset_train.csv",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.7,
        help="Train split ratio.",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Validation split ratio.",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.15,
        help="Test split ratio.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for run shuffling.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Optional run manifest CSV used to filter mission_id values.",
    )
    parser.add_argument(
        "--quality-col",
        default="quality_ok",
        help="Manifest boolean/integer column used when --manifest is provided.",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    if "mission_id" not in df.columns:
        raise SystemExit("Input CSV must contain mission_id column.")

    if args.manifest:
        manifest = pd.read_csv(args.manifest)
        if "mission_id" not in manifest.columns:
            raise SystemExit("Manifest CSV must contain mission_id column.")
        if args.quality_col not in manifest.columns:
            raise SystemExit(f"Manifest CSV missing quality column: {args.quality_col}")
        keep_ids = set(
            manifest.loc[manifest[args.quality_col].astype(int) == 1, "mission_id"].astype(str)
        )
        df = df[df["mission_id"].astype(str).isin(keep_ids)].copy()

    mission_ids = sorted(df["mission_id"].astype(str).unique())
    if not mission_ids:
        raise SystemExit("No mission_id values available after filtering.")

    train_ratio, val_ratio, test_ratio = normalized_ratios(
        args.train_ratio, args.val_ratio, args.test_ratio
    )
    rng = np.random.default_rng(args.seed)
    shuffled = mission_ids[:]
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = max(1, int(round(n * train_ratio))) if n >= 3 else max(1, n - 2)
    n_val = int(round(n * val_ratio)) if n >= 3 else 1 if n == 3 else 0
    if n_train + n_val >= n:
        n_val = max(0, n - n_train - 1)
    n_test = n - n_train - n_val
    if n_test <= 0 and n >= 2:
        n_test = 1
        if n_train > 1:
            n_train -= 1
        elif n_val > 0:
            n_val -= 1

    train_ids = set(shuffled[:n_train])
    val_ids = set(shuffled[n_train:n_train + n_val])
    test_ids = set(shuffled[n_train + n_val:])

    split_map = {}
    for mission_id in train_ids:
        split_map[mission_id] = "train"
    for mission_id in val_ids:
        split_map[mission_id] = "val"
    for mission_id in test_ids:
        split_map[mission_id] = "test"

    df["split"] = df["mission_id"].astype(str).map(split_map)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for split_name in ("train", "val", "test"):
        split_df = df[df["split"] == split_name].copy()
        split_path = out_dir / f"{args.prefix}_{split_name}.csv"
        split_df.to_csv(split_path, index=False)

    split_manifest = pd.DataFrame(
        [{"mission_id": mission_id, "split": split_map[mission_id]} for mission_id in shuffled]
    )
    split_manifest.to_csv(out_dir / f"{args.prefix}_splits.csv", index=False)

    print(
        f"[split_dataset_by_run] missions train/val/test="
        f"{len(train_ids)}/{len(val_ids)}/{len(test_ids)}"
    )
    print(f"[split_dataset_by_run] output_dir={out_dir}")


if __name__ == "__main__":
    main()
