#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_IGNORE_COLS = ["t", "mission_id", "split", "label"]


def load_split(path):
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"{path} is empty")
    return df


def parse_max_samples(value):
    if value == "auto":
        return value
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid --max-samples value: {value}") from exc


def resolve_feature_columns(df, ignore_cols):
    ignore = set(ignore_cols)
    feature_cols = []
    for col in df.columns:
        if col in ignore:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            feature_cols.append(col)
    if not feature_cols:
        raise ValueError("No numeric feature columns found after filtering ignore_cols.")
    return feature_cols


def sanitize_frame(df, feature_cols):
    out = df.copy()
    missing = [c for c in feature_cols if c not in out.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    out = out.dropna(subset=feature_cols).reset_index(drop=True)
    return out


def build_summary(split_name, df, anomaly_score, threshold):
    flagged = anomaly_score >= threshold
    summary = {
        "split": split_name,
        "num_rows": int(len(df)),
        "num_flagged": int(flagged.sum()),
        "flagged_ratio": float(flagged.mean()) if len(df) else 0.0,
        "score_mean": float(np.mean(anomaly_score)),
        "score_std": float(np.std(anomaly_score)),
        "score_p95": float(np.quantile(anomaly_score, 0.95)),
        "score_p99": float(np.quantile(anomaly_score, 0.99)),
        "score_max": float(np.max(anomaly_score)),
        "threshold": float(threshold),
    }

    if "mission_id" in df.columns:
        per_mission = (
            pd.DataFrame({"mission_id": df["mission_id"], "flagged": flagged.astype(int)})
            .groupby("mission_id", as_index=False)["flagged"]
            .mean()
            .rename(columns={"flagged": "flagged_ratio"})
        )
        summary["mission_flagged_ratio_mean"] = float(per_mission["flagged_ratio"].mean())
        summary["mission_flagged_ratio_max"] = float(per_mission["flagged_ratio"].max())

    return summary, flagged


def write_scored_csv(path, df, anomaly_score, flagged):
    out = df.copy()
    out["anomaly_score"] = anomaly_score
    out["is_flagged"] = flagged.astype(int)
    out.to_csv(path, index=False)


def main():
    parser = argparse.ArgumentParser(
        description="Train a normal-only Isolation Forest on by-run split feature CSV files."
    )
    parser.add_argument("--train", required=True, help="Train split CSV path.")
    parser.add_argument("--val", default=None, help="Validation split CSV path.")
    parser.add_argument("--test", default=None, help="Test split CSV path.")
    parser.add_argument("--out-dir", required=True, help="Output directory.")
    parser.add_argument(
        "--ignore-cols",
        nargs="+",
        default=DEFAULT_IGNORE_COLS,
        help="Columns to exclude from model features.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed.",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=200,
        help="Number of trees for Isolation Forest.",
    )
    parser.add_argument(
        "--max-samples",
        default="auto",
        help="Isolation Forest max_samples parameter.",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.01,
        help="Expected anomaly ratio used by Isolation Forest.",
    )
    parser.add_argument(
        "--threshold-quantile",
        type=float,
        default=0.99,
        help="Quantile of train anomaly_score used as alert threshold.",
    )
    parser.add_argument(
        "--write-scored-csv",
        action="store_true",
        help="Write scored copies of train/val/test CSV files.",
    )
    args = parser.parse_args()

    try:
        import joblib
        from sklearn.ensemble import IsolationForest
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency. Install requirements first: "
            "`pip install -r tools/dt_ids/requirements.txt`"
        ) from exc

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_df = load_split(args.train)
    feature_cols = resolve_feature_columns(train_df, args.ignore_cols)
    train_df = sanitize_frame(train_df, feature_cols)

    model = IsolationForest(
        n_estimators=args.n_estimators,
        max_samples=parse_max_samples(args.max_samples),
        contamination=args.contamination,
        random_state=args.random_state,
        n_jobs=-1,
    )
    model.fit(train_df[feature_cols].to_numpy())

    train_score = -model.decision_function(train_df[feature_cols].to_numpy())
    threshold = float(np.quantile(train_score, args.threshold_quantile))

    summary_rows = []
    train_summary, train_flagged = build_summary("train", train_df, train_score, threshold)
    summary_rows.append(train_summary)

    split_outputs = {
        "train": (train_df, train_score, train_flagged),
    }

    for split_name, path in (("val", args.val), ("test", args.test)):
        if not path:
            continue
        df = load_split(path)
        df = sanitize_frame(df, feature_cols)
        score = -model.decision_function(df[feature_cols].to_numpy())
        summary, flagged = build_summary(split_name, df, score, threshold)
        summary_rows.append(summary)
        split_outputs[split_name] = (df, score, flagged)

    model_bundle = {
        "model": model,
        "feature_columns": feature_cols,
        "ignore_columns": list(args.ignore_cols),
        "threshold": threshold,
        "train_path": str(Path(args.train).resolve()),
        "val_path": str(Path(args.val).resolve()) if args.val else None,
        "test_path": str(Path(args.test).resolve()) if args.test else None,
    }
    joblib.dump(model_bundle, out_dir / "isolation_forest.joblib")

    with (out_dir / "feature_columns.json").open("w", encoding="utf-8") as f:
        json.dump(feature_cols, f, indent=2)

    with (out_dir / "training_config.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "ignore_cols": args.ignore_cols,
                "random_state": args.random_state,
                "n_estimators": args.n_estimators,
                "max_samples": args.max_samples,
                "contamination": args.contamination,
                "threshold_quantile": args.threshold_quantile,
                "threshold": threshold,
            },
            f,
            indent=2,
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(out_dir / "score_summary.csv", index=False)

    if args.write_scored_csv:
        for split_name, (df, score, flagged) in split_outputs.items():
            write_scored_csv(out_dir / f"{split_name}_scored.csv", df, score, flagged)

    print(f"[train_isolation_forest] features={len(feature_cols)}")
    print(f"[train_isolation_forest] threshold={threshold:.6f}")
    print(f"[train_isolation_forest] output_dir={out_dir}")


if __name__ == "__main__":
    main()
