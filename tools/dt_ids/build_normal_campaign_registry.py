#!/usr/bin/env python3
"""Build an auditable, run-level registry from a normal-flight campaign.

The KPI logger numbers runs independently inside each map directory (for
example, every map can contain ``kpi_log_run_001.csv``).  This tool makes the
composite ``environment/run_id`` the stable identifier, checks the experiment
and quality manifests, records immutable SHA-256 fingerprints, and assigns
train/validation/test splits at the *run* level per environment.

The output deliberately remains ``training_eligible: false`` until every
requested map has the requested number of SUCCESS_FINISH runs that also pass
the independent quality manifest.  A downstream trainer must refuse that
manifest instead of silently training on an imbalanced partial collection.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from typing import Any, Iterable


SCHEMA_VERSION = "normal-campaign-registry-v1"
DEFAULT_MAPS = ("indoor_01", "indoor_02", "lab_corridor_01", "lab_rooms_01")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def load_quality_index(path: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(path)
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        mission_id = row.get("mission_id", "")
        if not mission_id:
            raise ValueError(f"quality manifest has a row without mission_id: {path}")
        if mission_id in index:
            raise ValueError(f"quality manifest has duplicate mission_id {mission_id!r}: {path}")
        index[mission_id] = row
    return index


def stable_shuffle(records: list[dict[str, Any]], seed: int, environment: str) -> list[dict[str, Any]]:
    # Python's built-in hash is intentionally process-randomised; derive a
    # stable environment-specific seed instead so a registry can be rebuilt.
    env_offset = int(hashlib.sha256(environment.encode("utf-8")).hexdigest()[:16], 16)
    shuffled = records[:]
    Random(seed + env_offset).shuffle(shuffled)
    return shuffled


def build_map_records(
    campaign_dir: Path,
    environment: str,
    *,
    record_path_root: Path | None,
    allow_active: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    map_dir = campaign_dir / environment
    summary: dict[str, Any] = {
        "environment": environment,
        "directory": str(map_dir),
        "attempted": 0,
        "success_finish_retained": 0,
        "quality_ok": 0,
        "eligible_candidates": 0,
        "excluded": defaultdict(int),
    }
    problems: list[str] = []

    card_path = map_dir / "collection_card.json"
    progress_path = map_dir / "batch_progress.json"
    run_manifest_path = map_dir / "run_manifest.csv"
    quality_path = map_dir / "quality_manifest.csv"

    for required in (card_path, progress_path, run_manifest_path, quality_path):
        if not required.is_file():
            problems.append(f"{environment}: missing required file {required.name}")
    if problems:
        return [], summary, problems

    try:
        card = load_json(card_path)
        progress = load_json(progress_path)
        quality_index = load_quality_index(quality_path)
        run_rows = read_csv(run_manifest_path)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        problems.append(f"{environment}: cannot read campaign metadata: {exc}")
        return [], summary, problems

    card_world = card.get("world", {})
    if card.get("scenario") != "normal":
        problems.append(f"{environment}: collection card scenario is not normal")
    if card.get("transport_mode") != "nosip":
        problems.append(f"{environment}: collection card transport_mode is not nosip")
    if card.get("attack_profile") != "none":
        problems.append(f"{environment}: collection card attack_profile is not none")
    if not isinstance(card_world, dict) or card_world.get("name") != environment:
        problems.append(f"{environment}: collection card world name does not match directory")

    world_file = Path(str(card_world.get("file", "")))
    card_world_hash = card_world.get("sha256")
    if not isinstance(card_world_hash, str) or len(card_world_hash) != 64:
        problems.append(f"{environment}: collection card has no valid world SHA-256")
    elif not world_file.is_file():
        problems.append(f"{environment}: world file recorded by collection card no longer exists")
    elif sha256_file(world_file) != card_world_hash:
        problems.append(f"{environment}: world file changed after collection card was written")

    state = str(progress.get("state", ""))
    if not allow_active and state != "COMPLETED":
        problems.append(f"{environment}: batch_progress state is {state!r}, expected 'COMPLETED'")

    selected: list[dict[str, Any]] = []
    for row in sorted(run_rows, key=lambda item: item.get("run_id", "")):
        summary["attempted"] += 1
        run_id = row.get("run_id", "")
        retained = as_bool(row.get("log_retained", ""))
        success = row.get("outcome") == "SUCCESS_FINISH" and retained
        if not success:
            summary["excluded"]["not_success_finish_retained"] += 1
            continue
        summary["success_finish_retained"] += 1

        if row.get("scenario") != "normal" or row.get("world_name") != environment:
            summary["excluded"]["manifest_identity_mismatch"] += 1
            continue
        if row.get("transport_mode") != "nosip":
            summary["excluded"]["transport_not_nosip"] += 1
            continue
        if not run_id:
            summary["excluded"]["missing_run_id"] += 1
            continue

        quality = quality_index.get(f"kpi_log_{run_id}")
        if quality is None:
            summary["excluded"]["missing_quality_row"] += 1
            continue
        if not as_bool(quality.get("quality_ok", "")):
            summary["excluded"]["quality_not_ok"] += 1
            continue
        summary["quality_ok"] += 1

        source_path = map_dir / f"kpi_log_{run_id}.csv"
        if not source_path.is_file():
            summary["excluded"]["missing_kpi_csv"] += 1
            continue

        relative_path = source_path.relative_to(campaign_dir)
        training_path = (record_path_root / relative_path) if record_path_root else source_path
        try:
            quality_snapshot = {
                "quality_ok": True,
                "num_rows": int(float(quality.get("num_rows", "0"))),
                "t_start": float(quality.get("t_start", "nan")),
                "t_end": float(quality.get("t_end", "nan")),
                "duration_s": float(quality.get("duration_s", "0")),
                "dt_min": float(quality.get("dt_min", "nan")),
                "dt_mean": float(quality.get("dt_mean", "nan")),
                "dt_max": float(quality.get("dt_max", "nan")),
                "zero_dt_count": int(float(quality.get("zero_dt_count", "0"))),
                "negative_dt_count": int(float(quality.get("negative_dt_count", "0"))),
                "gps_nan_ratio": float(quality.get("gps_nan_ratio", "nan")),
                "gps_valid_ratio": float(quality.get("gps_valid_ratio", "0")),
                "e_pos_mean": float(quality.get("e_pos_mean", "nan")),
                "e_pos_p95": float(quality.get("e_pos_p95", "nan")),
                "e_pos_max": float(quality.get("e_pos_max", "nan")),
            }
        except (TypeError, ValueError):
            summary["excluded"]["invalid_quality_metrics"] += 1
            continue
        numeric_metrics = tuple(
            value for key, value in quality_snapshot.items() if key != "quality_ok"
        )
        if not all(math.isfinite(value) for value in numeric_metrics):
            summary["excluded"]["nonfinite_quality_metrics"] += 1
            continue
        if (
            quality_snapshot["num_rows"] <= 0
            or quality_snapshot["duration_s"] <= 0.0
            or quality_snapshot["zero_dt_count"] < 0
            or quality_snapshot["negative_dt_count"] < 0
            or not 0.0 <= quality_snapshot["gps_nan_ratio"] <= 1.0
            or not 0.0 <= quality_snapshot["gps_valid_ratio"] <= 1.0
        ):
            summary["excluded"]["out_of_range_quality_metrics"] += 1
            continue

        selected.append(
            {
                "path": str(training_path),
                "source_path": str(source_path.resolve()),
                "relative_path": str(relative_path),
                "sha256": sha256_file(source_path),
                "environment": environment,
                "run_id": f"{environment}/{run_id}",
                "source_run_id": run_id,
                "split": "unassigned",
                "quality_flags": [],
                "quality": quality_snapshot,
                "provenance": {
                    "campaign_id": card.get("campaign_id"),
                    "world_file": str(world_file),
                    "world_sha256": card_world_hash,
                    "transport_mode": row.get("transport_mode"),
                    "scenario": row.get("scenario"),
                },
            }
        )

    summary["eligible_candidates"] = len(selected)
    summary["excluded"] = dict(sorted(summary["excluded"].items()))
    return selected, summary, problems


def find_duplicate_hashes(records: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in records:
        grouped[record["sha256"]].append(record["run_id"])
    return {
        f"sha256:{digest}": run_ids
        for digest, run_ids in sorted(grouped.items())
        if len(run_ids) > 1
    }


def assign_per_environment_splits(
    selected_by_map: dict[str, list[dict[str, Any]]],
    *,
    train_per_map: int,
    val_per_map: int,
    test_per_map: int,
    seed: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for environment in sorted(selected_by_map):
        shuffled = stable_shuffle(selected_by_map[environment], seed, environment)
        boundaries = (train_per_map, train_per_map + val_per_map)
        for index, record in enumerate(shuffled):
            copy = dict(record)
            if index < boundaries[0]:
                copy["split"] = "train"
            elif index < boundaries[1]:
                copy["split"] = "val"
            else:
                copy["split"] = "test"
            result.append(copy)
    return result


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")
    os.replace(temporary, path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", dest="maps", action="append", choices=DEFAULT_MAPS)
    parser.add_argument("--runs-per-map", type=positive_int, default=12)
    parser.add_argument("--train-per-map", type=positive_int, default=8)
    parser.add_argument("--val-per-map", type=positive_int, default=2)
    parser.add_argument("--test-per-map", type=positive_int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--record-path-root",
        type=Path,
        default=None,
        help="Optional root used for record.path after copying the campaign to a training host.",
    )
    parser.add_argument(
        "--feature-set",
        default=None,
        help="Selected model feature set. Required before the registry becomes training-eligible.",
    )
    parser.add_argument(
        "--allow-active",
        action="store_true",
        help="Create a progress-only registry even when a map batch is not COMPLETED.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the generated registry is not training-eligible.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    campaign_dir = args.campaign_dir.resolve()
    if not campaign_dir.is_dir():
        raise SystemExit(f"campaign directory does not exist: {campaign_dir}")
    if args.runs_per_map != args.train_per_map + args.val_per_map + args.test_per_map:
        raise SystemExit("runs-per-map must equal train-per-map + val-per-map + test-per-map")

    maps = tuple(args.maps or DEFAULT_MAPS)
    candidates: dict[str, list[dict[str, Any]]] = {}
    map_summaries: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    for environment in maps:
        records, summary, problems = build_map_records(
            campaign_dir,
            environment,
            record_path_root=args.record_path_root,
            allow_active=args.allow_active,
        )
        candidates[environment] = records
        map_summaries.append(summary)
        blocking_reasons.extend(problems)
        if len(records) < args.runs_per_map:
            blocking_reasons.append(
                f"{environment}: eligible runs {len(records)} < required {args.runs_per_map}"
            )

    enough_data = not blocking_reasons
    selected_by_map = {
        environment: sorted(records, key=lambda item: item["source_run_id"])[: args.runs_per_map]
        for environment, records in candidates.items()
    }
    selected_records = [record for records in selected_by_map.values() for record in records]
    duplicate_groups = find_duplicate_hashes(selected_records)
    if duplicate_groups:
        blocking_reasons.append("selected records contain duplicate CSV SHA-256 values")
    if not args.feature_set:
        blocking_reasons.append("feature_set_not_selected")

    training_eligible = enough_data and not duplicate_groups and bool(args.feature_set)
    if training_eligible:
        records = assign_per_environment_splits(
            selected_by_map,
            train_per_map=args.train_per_map,
            val_per_map=args.val_per_map,
            test_per_map=args.test_per_map,
            seed=args.seed,
        )
    else:
        records = selected_records

    campaign_id = None
    first_card = campaign_dir / maps[0] / "collection_card.json"
    if first_card.is_file():
        try:
            campaign_id = load_json(first_card).get("campaign_id")
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    payload = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "campaign_dir": str(campaign_dir),
            "campaign_id": campaign_id,
            "feature_set": args.feature_set,
            "training_eligible": training_eligible,
            "blocking_reasons": sorted(set(blocking_reasons)),
            "acceptance_rule": "normal + nosip + SUCCESS_FINISH + retained CSV + quality_ok=1",
            "split_strategy": {
                "unit": "run",
                "method": "deterministic per-environment shuffle",
                "seed": args.seed,
                "per_environment": {
                    "train": args.train_per_map,
                    "val": args.val_per_map,
                    "test": args.test_per_map,
                },
            },
            "record_path_root": str(args.record_path_root) if args.record_path_root else None,
        },
        "maps": map_summaries,
        "duplicate_groups": duplicate_groups,
        "records": sorted(records, key=lambda item: (item["environment"], item["source_run_id"])),
    }
    write_json_atomic(args.out, payload)

    print(f"[build_normal_campaign_registry] maps={len(maps)} selected_records={len(records)}")
    print(f"[build_normal_campaign_registry] training_eligible={training_eligible}")
    if blocking_reasons:
        print(f"[build_normal_campaign_registry] blocking_reasons={len(set(blocking_reasons))}")
    print(f"[build_normal_campaign_registry] output={args.out}")
    return 0 if training_eligible or not args.strict else 2


if __name__ == "__main__":
    raise SystemExit(main())
