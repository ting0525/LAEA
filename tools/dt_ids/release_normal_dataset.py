#!/usr/bin/env python3
"""Create and verify an immutable, reference-only normal-dataset release.

The release contains manifests and checksums only.  It never copies, moves, or
rewrites source KPI logs.  A training host should copy the files listed in
``SHA256SUMS`` (selected records), ``RESERVE_SHA256SUMS`` (reserve records), and
``SOURCE_METADATA_SHA256SUMS`` below its local campaign root.  ``source_path``
is retained only as an audit trail for the simulator host.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from build_normal_campaign_registry import (
    DEFAULT_MAPS,
    assign_per_environment_splits,
    build_map_records,
    find_duplicate_hashes,
    load_json,
    positive_int,
    sha256_file,
)


SCHEMA_VERSION = "normal-dataset-release-v1"
POLICY_VERSION = "normal-dataset-selection-policy-v1"
DEFAULT_RELEASE_ID = "normal_dataset_v1"
REQUIRED_RELEASE_FILES = (
    "manifest.json",
    "records.csv",
    "reserves.csv",
    "selection_policy.json",
    "feature_columns.json",
    "SHA256SUMS",
    "RESERVE_SHA256SUMS",
    "SOURCE_METADATA_SHA256SUMS",
    "README.md",
    "release_files.sha256",
)
CSV_FIELDS = (
    "run_id",
    "source_run_id",
    "environment",
    "split",
    "relative_path",
    "source_path",
    "sha256",
    "quality_ok",
    "num_rows",
    "t_start",
    "t_end",
    "duration_s",
    "dt_min",
    "dt_mean",
    "dt_max",
    "zero_dt_count",
    "negative_dt_count",
    "gps_nan_ratio",
    "gps_valid_ratio",
    "e_pos_mean",
    "e_pos_p95",
    "e_pos_max",
    "campaign_id",
    "world_file",
    "world_sha256",
    "scenario",
    "transport_mode",
)
RUN_ID_PATTERN = re.compile(r"^run_(\d+)$")
DEFAULT_FEATURE_SETS_PATH = Path(__file__).with_name("feature_sets.yaml")
GROUND_TRUTH_COLUMNS = frozenset(
    {"px_gt", "py_gt", "pz_gt", "e_pos", "mission_outcome"}
)


class ReleaseError(RuntimeError):
    """Raised when a release cannot be created or verified safely."""


def natural_run_key(record: dict[str, Any]) -> tuple[int, str]:
    """Sort zero-padded and non-padded run IDs by their numeric sequence."""

    source_run_id = str(record.get("source_run_id", ""))
    match = RUN_ID_PATTERN.fullmatch(source_run_id)
    if not match:
        raise ReleaseError(f"unsupported source_run_id format: {source_run_id!r}")
    return int(match.group(1)), source_run_id


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_relative_path(value: object) -> PurePosixPath:
    raw = str(value)
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ReleaseError(f"unsafe campaign-relative path: {raw!r}")
    return path


def source_metadata_entries(campaign_dir: Path, maps: Iterable[str]) -> list[dict[str, str]]:
    relative_paths = [
        Path("campaign_summary.json"),
        Path("final_normal_collection_v1_status.json"),
    ]
    for environment in sorted(maps):
        relative_paths.extend(
            [
                Path(environment) / "collection_card.json",
                Path(environment) / "batch_progress.json",
                Path(environment) / "run_manifest.csv",
                Path(environment) / "quality_manifest.csv",
            ]
        )

    entries: list[dict[str, str]] = []
    for relative_path in sorted(relative_paths, key=lambda path: path.as_posix()):
        source_path = campaign_dir / relative_path
        if not source_path.is_file():
            raise ReleaseError(f"missing source metadata file: {source_path}")
        entries.append(
            {
                "relative_path": relative_path.as_posix(),
                "source_path": str(source_path),
                "sha256": sha256_file(source_path),
            }
        )
    return entries


def load_feature_columns(
    feature_sets_path: Path,
    feature_set: str,
) -> tuple[list[str], str]:
    feature_sets_path = feature_sets_path.resolve()
    if not feature_sets_path.is_file():
        raise ReleaseError(f"feature-set config does not exist: {feature_sets_path}")
    with feature_sets_path.open(encoding="utf-8") as source:
        payload = yaml.safe_load(source)
    try:
        columns = payload["feature_sets"][feature_set]
    except (KeyError, TypeError) as exc:
        raise ReleaseError(
            f"feature set {feature_set!r} is not defined in {feature_sets_path}"
        ) from exc
    if (
        not isinstance(columns, list)
        or not columns
        or any(not isinstance(column, str) or not column for column in columns)
    ):
        raise ReleaseError(f"feature set {feature_set!r} has an invalid column list")
    if len(set(columns)) != len(columns):
        raise ReleaseError(f"feature set {feature_set!r} contains duplicate columns")
    leaked = sorted(GROUND_TRUTH_COLUMNS.intersection(columns))
    if leaked:
        raise ReleaseError(
            f"feature set {feature_set!r} contains evaluation-only columns: "
            + ", ".join(leaked)
        )
    return columns, sha256_file(feature_sets_path)


def validate_feature_columns(
    records: Iterable[dict[str, Any]],
    feature_columns: Iterable[str],
    *,
    campaign_dir: Path | None = None,
) -> None:
    expected = set(feature_columns)
    for record in records:
        if campaign_dir is None:
            source_path = Path(str(record["source_path"]))
        else:
            relative = safe_relative_path(record["relative_path"])
            source_path = campaign_dir.joinpath(*relative.parts)
        with source_path.open(newline="", encoding="utf-8") as source:
            header = next(csv.reader(source), None)
        if not header:
            raise ReleaseError(f"{record['run_id']}: source CSV has no header")
        if len(header) != len(set(header)):
            raise ReleaseError(f"{record['run_id']}: source CSV has duplicate columns")
        missing = sorted(expected - set(header))
        if missing:
            raise ReleaseError(
                f"{record['run_id']}: source CSV is missing feature columns: "
                + ", ".join(missing)
            )


def portable_record(record: dict[str, Any], *, split: str | None = None) -> dict[str, Any]:
    result = dict(record)
    result["quality"] = dict(record["quality"])
    result["provenance"] = dict(record["provenance"])
    # `path` is intentionally portable.  `source_path` remains the absolute
    # audit location and must not be used after relocating the campaign.
    result["path"] = str(record["relative_path"])
    if split is not None:
        result["split"] = split
    return result


def dataset_fingerprint(records: Iterable[dict[str, Any]]) -> str:
    identity = [
        {
            "environment": record["environment"],
            "relative_path": record["relative_path"],
            "run_id": record["run_id"],
            "sha256": record["sha256"],
            "split": record["split"],
        }
        for record in sorted(records, key=lambda item: item["run_id"])
    ]
    return canonical_sha256(identity)


def build_release(
    campaign_dir: Path,
    *,
    maps: tuple[str, ...],
    release_id: str,
    feature_set: str,
    feature_sets_path: Path = DEFAULT_FEATURE_SETS_PATH,
    runs_per_map: int,
    train_per_map: int,
    val_per_map: int,
    test_per_map: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build deterministic release and policy payloads without writing files."""

    campaign_dir = campaign_dir.resolve()
    if runs_per_map != train_per_map + val_per_map + test_per_map:
        raise ReleaseError(
            "runs-per-map must equal train-per-map + val-per-map + test-per-map"
        )
    if len(set(maps)) != len(maps):
        raise ReleaseError("map list contains duplicates")
    if not feature_set.strip():
        raise ReleaseError("feature-set must not be empty")
    if not release_id.strip():
        raise ReleaseError("release-id must not be empty")
    feature_columns, feature_config_sha256 = load_feature_columns(
        feature_sets_path,
        feature_set,
    )

    final_status_path = campaign_dir / "final_normal_collection_v1_status.json"
    if not final_status_path.is_file():
        raise ReleaseError(f"missing final collection status: {final_status_path}")
    final_status = load_json(final_status_path)
    if final_status.get("state") != "COMPLETED":
        raise ReleaseError(
            "final normal collection is not complete: "
            f"state={final_status.get('state')!r}"
        )
    approved_maps = tuple(final_status.get("approved_maps", ()))
    missing_approvals = sorted(set(maps) - set(approved_maps))
    if missing_approvals:
        raise ReleaseError(
            "requested maps are not approved by final status: "
            + ", ".join(missing_approvals)
        )

    candidates_by_map: dict[str, list[dict[str, Any]]] = {}
    selected_by_map: dict[str, list[dict[str, Any]]] = {}
    reserves_by_map: dict[str, list[dict[str, Any]]] = {}
    map_summaries: list[dict[str, Any]] = []
    problems: list[str] = []

    for environment in maps:
        candidates, summary, map_problems = build_map_records(
            campaign_dir,
            environment,
            record_path_root=None,
            allow_active=False,
        )
        map_summaries.append(summary)
        problems.extend(map_problems)
        ordered = sorted(candidates, key=natural_run_key)
        candidates_by_map[environment] = ordered
        if len(ordered) < runs_per_map:
            problems.append(
                f"{environment}: eligible runs {len(ordered)} < required {runs_per_map}"
            )
        selected_by_map[environment] = ordered[:runs_per_map]
        reserves_by_map[environment] = ordered[runs_per_map:]

    if problems:
        raise ReleaseError("campaign is not releasable:\n- " + "\n- ".join(problems))

    selected_without_splits = [
        record
        for environment in maps
        for record in selected_by_map[environment]
    ]
    reserve_without_splits = [
        record
        for environment in maps
        for record in reserves_by_map[environment]
    ]
    duplicate_groups = find_duplicate_hashes(
        [*selected_without_splits, *reserve_without_splits]
    )
    if duplicate_groups:
        raise ReleaseError(
            "selected/reserve source files have duplicate SHA-256 values: "
            + json.dumps(duplicate_groups, sort_keys=True)
        )
    validate_feature_columns(
        [*selected_without_splits, *reserve_without_splits],
        feature_columns,
    )

    assigned_records = assign_per_environment_splits(
        selected_by_map,
        train_per_map=train_per_map,
        val_per_map=val_per_map,
        test_per_map=test_per_map,
        seed=seed,
    )
    records = sorted(
        (portable_record(record) for record in assigned_records),
        key=lambda record: (record["environment"], natural_run_key(record)),
    )
    reserves = sorted(
        (
            portable_record(record, split="reserve")
            for environment in maps
            for record in reserves_by_map[environment]
        ),
        key=lambda record: (record["environment"], natural_run_key(record)),
    )

    fingerprint = dataset_fingerprint(records)
    source_metadata = source_metadata_entries(campaign_dir, maps)
    split_counts = Counter(record["split"] for record in records)
    policy = {
        "schema_version": POLICY_VERSION,
        "release_id": release_id,
        "eligibility_rule": {
            "scenario": "normal",
            "transport_mode": "nosip",
            "outcome": "SUCCESS_FINISH",
            "log_retained": True,
            "quality_ok": True,
        },
        "selection": {
            "candidate_order": "numeric ascending source_run_id within each environment",
            "selected_rule": f"first {runs_per_map} eligible runs per environment",
            "reserve_rule": "all remaining eligible runs, excluded from model splits",
            "maps": list(maps),
            "runs_per_map": runs_per_map,
        },
        "split": {
            "unit": "complete run",
            "method": "deterministic per-environment shuffle",
            "seed": seed,
            "per_environment": {
                "train": train_per_map,
                "val": val_per_map,
                "test": test_per_map,
            },
        },
        "path_resolution": {
            "portable_field": "relative_path",
            "rule": "join local campaign root with relative_path",
            "source_path_role": "simulator-host audit trail only",
        },
        "feature_set": feature_set,
        "feature_columns": feature_columns,
        "feature_config_sha256": feature_config_sha256,
        "selected_records": len(records),
        "reserve_records": len(reserves),
        "dataset_sha256": fingerprint,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "release_id": release_id,
            "dataset_sha256": fingerprint,
            "feature_set": feature_set,
            "feature_columns": feature_columns,
            "feature_config": {
                "source_path": str(feature_sets_path.resolve()),
                "sha256": feature_config_sha256,
            },
            "training_eligible": True,
            "source_campaign": {
                "campaign_id": final_status.get(
                    "campaign_id", campaign_dir.name
                ),
                "campaign_dir": str(campaign_dir),
                "state": final_status["state"],
                "completed_at_utc": final_status.get("updated_at_utc"),
                "status_sha256": sha256_file(final_status_path),
            },
            "counts": {
                "maps": len(maps),
                "selected_records": len(records),
                "reserve_records": len(reserves),
                "split_records": dict(sorted(split_counts.items())),
            },
            "selection_policy_file": "selection_policy.json",
            "path_resolution": policy["path_resolution"],
        },
        "maps": map_summaries,
        "source_metadata": source_metadata,
        "records": records,
        "reserves": reserves,
    }
    return manifest, policy


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    quality = record["quality"]
    provenance = record["provenance"]
    row: dict[str, Any] = {
        field: record.get(field, "")
        for field in (
            "run_id",
            "source_run_id",
            "environment",
            "split",
            "relative_path",
            "source_path",
            "sha256",
        )
    }
    row.update(
        {
            "quality_ok": quality["quality_ok"],
            "num_rows": quality["num_rows"],
            "t_start": quality["t_start"],
            "t_end": quality["t_end"],
            "duration_s": quality["duration_s"],
            "dt_min": quality["dt_min"],
            "dt_mean": quality["dt_mean"],
            "dt_max": quality["dt_max"],
            "zero_dt_count": quality["zero_dt_count"],
            "negative_dt_count": quality["negative_dt_count"],
            "gps_nan_ratio": quality["gps_nan_ratio"],
            "gps_valid_ratio": quality["gps_valid_ratio"],
            "e_pos_mean": quality["e_pos_mean"],
            "e_pos_p95": quality["e_pos_p95"],
            "e_pos_max": quality["e_pos_max"],
            "campaign_id": provenance["campaign_id"],
            "world_file": provenance["world_file"],
            "world_sha256": provenance["world_sha256"],
            "scenario": provenance["scenario"],
            "transport_mode": provenance["transport_mode"],
        }
    )
    return row


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")


def write_records_csv(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(flatten_record(record) for record in records)


def write_checksum_file(
    path: Path,
    records: Iterable[dict[str, Any]],
    *,
    path_field: str = "relative_path",
) -> None:
    with path.open("w", encoding="utf-8") as target:
        for record in sorted(records, key=lambda item: str(item[path_field])):
            target.write(f"{record['sha256']}  {record[path_field]}\n")


def write_readme(
    path: Path,
    *,
    manifest: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    metadata = manifest["metadata"]
    counts = metadata["counts"]
    split = policy["split"]["per_environment"]
    campaign = metadata["source_campaign"]
    content = f"""# {metadata['release_id']}

Reference-only release of quality-accepted normal-flight KPI logs.

- Source campaign: `{campaign['campaign_id']}`
- Selected runs: {counts['selected_records']} ({policy['selection']['runs_per_map']} per map)
- Per-map split: {split['train']} train / {split['val']} validation / {split['test']} test
- Reserve runs: {counts['reserve_records']}
- Feature set: `{metadata['feature_set']}` ({len(metadata['feature_columns'])} columns)
- Dataset fingerprint: `{metadata['dataset_sha256']}`

No raw KPI log is copied into this directory.  Copy the paths in
`SHA256SUMS`, `RESERVE_SHA256SUMS`, and `SOURCE_METADATA_SHA256SUMS`, then
resolve each `relative_path` under the local copy of the campaign directory.
`source_path` records the original simulator-host location and is not a
portable training path.

Run-level splitting is mandatory: one composite `environment/source_run_id`
appears in exactly one of train, validation, or test.  `SHA256SUMS` fingerprints
all selected KPI logs; `RESERVE_SHA256SUMS` fingerprints excluded reserve logs;
`SOURCE_METADATA_SHA256SUMS` fingerprints the campaign manifests used to make
the selection.

After relocating the files, verify them explicitly:

    python3 tools/dt_ids/release_normal_dataset.py verify \\
      --release-dir <release-dir> --campaign-dir <local-campaign-root>
"""
    path.write_text(content, encoding="utf-8")


def write_release_directory(
    release_dir: Path,
    *,
    manifest: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    """Atomically create a new immutable release directory."""

    release_dir = release_dir.resolve()
    if release_dir.exists():
        raise ReleaseError(
            f"release directory already exists; refusing to overwrite: {release_dir}"
        )
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{release_dir.name}.tmp-", dir=release_dir.parent)
    )
    try:
        write_json(temporary / "manifest.json", manifest)
        write_json(temporary / "selection_policy.json", policy)
        write_json(
            temporary / "feature_columns.json",
            {
                "feature_set": manifest["metadata"]["feature_set"],
                "columns": manifest["metadata"]["feature_columns"],
                "source_config_sha256": manifest["metadata"]["feature_config"]["sha256"],
            },
        )
        write_records_csv(temporary / "records.csv", manifest["records"])
        write_records_csv(temporary / "reserves.csv", manifest["reserves"])
        write_checksum_file(temporary / "SHA256SUMS", manifest["records"])
        write_checksum_file(
            temporary / "RESERVE_SHA256SUMS",
            manifest["reserves"],
        )
        write_checksum_file(
            temporary / "SOURCE_METADATA_SHA256SUMS",
            manifest["source_metadata"],
        )
        write_readme(temporary / "README.md", manifest=manifest, policy=policy)

        release_files = (
            "README.md",
            "RESERVE_SHA256SUMS",
            "SHA256SUMS",
            "SOURCE_METADATA_SHA256SUMS",
            "feature_columns.json",
            "manifest.json",
            "records.csv",
            "reserves.csv",
            "selection_policy.json",
        )
        with (temporary / "release_files.sha256").open(
            "w", encoding="utf-8"
        ) as target:
            for filename in release_files:
                target.write(f"{sha256_file(temporary / filename)}  {filename}\n")

        # Verify the complete staged release before making it visible.
        verify_release(temporary)
        os.replace(temporary, release_dir)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def read_checksum_file(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                digest, relative_path = line.split("  ", 1)
            except ValueError as exc:
                raise ReleaseError(
                    f"invalid checksum line {path}:{line_number}"
                ) from exc
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ReleaseError(
                    f"invalid SHA-256 at {path}:{line_number}: {digest!r}"
                )
            if relative_path in entries:
                raise ReleaseError(
                    f"duplicate checksum path at {path}:{line_number}: {relative_path!r}"
                )
            entries[relative_path] = digest
    return entries


def verify_release(
    release_dir: Path,
    *,
    campaign_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify release artifacts, split invariants, and referenced source bytes."""

    release_dir = release_dir.resolve()
    missing = [
        filename
        for filename in REQUIRED_RELEASE_FILES
        if not (release_dir / filename).is_file()
    ]
    if missing:
        raise ReleaseError("release is missing files: " + ", ".join(missing))

    release_file_hashes = read_checksum_file(release_dir / "release_files.sha256")
    expected_release_hashes = set(REQUIRED_RELEASE_FILES) - {"release_files.sha256"}
    if set(release_file_hashes) != expected_release_hashes:
        raise ReleaseError(
            "release_files.sha256 does not list the complete release artifact set"
        )
    for relative_path, expected_digest in release_file_hashes.items():
        safe = safe_relative_path(relative_path)
        artifact_path = release_dir.joinpath(*safe.parts)
        if not artifact_path.is_file():
            raise ReleaseError(f"release artifact is missing: {relative_path}")
        actual_digest = sha256_file(artifact_path)
        if actual_digest != expected_digest:
            raise ReleaseError(
                f"release artifact checksum mismatch: {relative_path}"
            )

    manifest = load_json(release_dir / "manifest.json")
    policy = load_json(release_dir / "selection_policy.json")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseError(
            f"unexpected release schema: {manifest.get('schema_version')!r}"
        )
    if policy.get("schema_version") != POLICY_VERSION:
        raise ReleaseError(
            f"unexpected selection policy schema: {policy.get('schema_version')!r}"
        )
    feature_payload = load_json(release_dir / "feature_columns.json")
    if (
        feature_payload.get("feature_set") != manifest["metadata"].get("feature_set")
        or feature_payload.get("columns")
        != manifest["metadata"].get("feature_columns")
        or feature_payload.get("source_config_sha256")
        != manifest["metadata"].get("feature_config", {}).get("sha256")
    ):
        raise ReleaseError(
            "feature_columns.json does not match manifest feature metadata"
        )

    records = manifest.get("records")
    reserves = manifest.get("reserves")
    if not isinstance(records, list) or not isinstance(reserves, list):
        raise ReleaseError("manifest records and reserves must be arrays")
    if not records:
        raise ReleaseError("release contains no selected records")

    run_ids = [str(record.get("run_id", "")) for record in records]
    if len(set(run_ids)) != len(run_ids):
        raise ReleaseError("a run_id appears more than once in selected records")
    relative_paths = [str(record.get("relative_path", "")) for record in records]
    if len(set(relative_paths)) != len(relative_paths):
        raise ReleaseError("a source path appears more than once in selected records")
    hashes = [str(record.get("sha256", "")) for record in records]
    if len(set(hashes)) != len(hashes):
        raise ReleaseError("a source SHA-256 appears more than once in selected records")
    reserve_run_ids = [str(record.get("run_id", "")) for record in reserves]
    if len(set(reserve_run_ids)) != len(reserve_run_ids):
        raise ReleaseError("a run_id appears more than once in reserve records")
    if set(run_ids) & set(reserve_run_ids):
        raise ReleaseError("a run_id appears in both selected and reserve records")
    reserve_hashes = [str(record.get("sha256", "")) for record in reserves]
    if len(set(reserve_hashes)) != len(reserve_hashes):
        raise ReleaseError("a source SHA-256 appears more than once in reserve records")
    if set(hashes) & set(reserve_hashes):
        raise ReleaseError(
            "a source SHA-256 appears in both selected and reserve records"
        )
    if any(record.get("split") != "reserve" for record in reserves):
        raise ReleaseError("every reserve record must have split='reserve'")

    split_spec = policy["split"]["per_environment"]
    selected_maps = tuple(policy["selection"]["maps"])
    if set(record.get("environment") for record in records) != set(selected_maps):
        raise ReleaseError("selected record maps do not match the selection policy")
    for environment in selected_maps:
        environment_records = [
            record for record in records if record.get("environment") == environment
        ]
        actual = Counter(record.get("split") for record in environment_records)
        expected = Counter(
            {
                "train": int(split_spec["train"]),
                "val": int(split_spec["val"]),
                "test": int(split_spec["test"]),
            }
        )
        if actual != expected:
            raise ReleaseError(
                f"{environment}: split counts {dict(actual)} != {dict(expected)}"
            )
        for record in environment_records:
            if not record.get("quality", {}).get("quality_ok"):
                raise ReleaseError(f"{record.get('run_id')}: quality_ok is not true")
    expected_selected_count = int(policy["selection"]["runs_per_map"]) * len(
        selected_maps
    )
    if len(records) != expected_selected_count:
        raise ReleaseError(
            f"selected record count {len(records)} != {expected_selected_count}"
        )
    if (
        int(policy.get("selected_records", -1)) != len(records)
        or int(policy.get("reserve_records", -1)) != len(reserves)
    ):
        raise ReleaseError("selection policy record counts do not match the manifest")
    manifest_counts = manifest["metadata"].get("counts", {})
    if (
        int(manifest_counts.get("selected_records", -1)) != len(records)
        or int(manifest_counts.get("reserve_records", -1)) != len(reserves)
        or int(manifest_counts.get("maps", -1)) != len(selected_maps)
    ):
        raise ReleaseError("manifest summary counts do not match its records")

    actual_fingerprint = dataset_fingerprint(records)
    expected_fingerprint = manifest["metadata"].get("dataset_sha256")
    if actual_fingerprint != expected_fingerprint:
        raise ReleaseError("dataset fingerprint does not match manifest records")
    if policy.get("dataset_sha256") != expected_fingerprint:
        raise ReleaseError("selection policy and manifest fingerprints differ")

    selected_checksum_entries = read_checksum_file(release_dir / "SHA256SUMS")
    expected_selected_checksums = {
        str(record["relative_path"]): str(record["sha256"]) for record in records
    }
    if selected_checksum_entries != expected_selected_checksums:
        raise ReleaseError("SHA256SUMS does not match selected manifest records")
    reserve_checksum_entries = read_checksum_file(
        release_dir / "RESERVE_SHA256SUMS"
    )
    expected_reserve_checksums = {
        str(record["relative_path"]): str(record["sha256"]) for record in reserves
    }
    if reserve_checksum_entries != expected_reserve_checksums:
        raise ReleaseError(
            "RESERVE_SHA256SUMS does not match reserve manifest records"
        )

    with (release_dir / "records.csv").open(
        newline="", encoding="utf-8"
    ) as source:
        csv_rows = list(csv.DictReader(source))
    csv_identity = {
        (
            row["run_id"],
            row["environment"],
            row["split"],
            row["relative_path"],
            row["sha256"],
        )
        for row in csv_rows
    }
    manifest_identity = {
        (
            str(record["run_id"]),
            str(record["environment"]),
            str(record["split"]),
            str(record["relative_path"]),
            str(record["sha256"]),
        )
        for record in records
    }
    if len(csv_rows) != len(records) or csv_identity != manifest_identity:
        raise ReleaseError("records.csv does not match manifest records")
    with (release_dir / "reserves.csv").open(
        newline="", encoding="utf-8"
    ) as source:
        reserve_csv_rows = list(csv.DictReader(source))
    reserve_csv_identity = {
        (
            row["run_id"],
            row["environment"],
            row["split"],
            row["relative_path"],
            row["sha256"],
        )
        for row in reserve_csv_rows
    }
    reserve_manifest_identity = {
        (
            str(record["run_id"]),
            str(record["environment"]),
            str(record["split"]),
            str(record["relative_path"]),
            str(record["sha256"]),
        )
        for record in reserves
    }
    if (
        len(reserve_csv_rows) != len(reserves)
        or reserve_csv_identity != reserve_manifest_identity
    ):
        raise ReleaseError("reserves.csv does not match manifest reserves")

    resolved_campaign_dir = (
        campaign_dir.resolve()
        if campaign_dir is not None
        else Path(manifest["metadata"]["source_campaign"]["campaign_dir"]).resolve()
    )
    for record in [*records, *reserves]:
        relative = safe_relative_path(record["relative_path"])
        source_path = resolved_campaign_dir.joinpath(*relative.parts)
        if not source_path.is_file():
            raise ReleaseError(f"referenced KPI log is missing: {source_path}")
        if sha256_file(source_path) != record["sha256"]:
            raise ReleaseError(
                f"referenced KPI log checksum mismatch: {record['relative_path']}"
            )
    validate_feature_columns(
        [*records, *reserves],
        manifest["metadata"]["feature_columns"],
        campaign_dir=resolved_campaign_dir,
    )

    source_metadata_checksums = read_checksum_file(
        release_dir / "SOURCE_METADATA_SHA256SUMS"
    )
    expected_metadata_checksums = {
        str(entry["relative_path"]): str(entry["sha256"])
        for entry in manifest["source_metadata"]
    }
    if source_metadata_checksums != expected_metadata_checksums:
        raise ReleaseError(
            "SOURCE_METADATA_SHA256SUMS does not match manifest source metadata"
        )
    for relative_path, expected_digest in source_metadata_checksums.items():
        relative = safe_relative_path(relative_path)
        source_path = resolved_campaign_dir.joinpath(*relative.parts)
        if not source_path.is_file():
            raise ReleaseError(f"referenced source metadata is missing: {source_path}")
        if sha256_file(source_path) != expected_digest:
            raise ReleaseError(
                f"source metadata checksum mismatch: {relative_path}"
            )

    return {
        "release_dir": str(release_dir),
        "campaign_dir": str(resolved_campaign_dir),
        "dataset_sha256": expected_fingerprint,
        "selected_records": len(records),
        "reserve_records": len(reserves),
        "maps": len(selected_maps),
        "verified": True,
    }


def add_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument("--feature-set", required=True)
    parser.add_argument(
        "--feature-sets",
        type=Path,
        default=DEFAULT_FEATURE_SETS_PATH,
        help="YAML file that defines the selected feature columns.",
    )
    parser.add_argument("--map", dest="maps", action="append", choices=DEFAULT_MAPS)
    parser.add_argument("--runs-per-map", type=positive_int, default=25)
    parser.add_argument("--train-per-map", type=positive_int, default=17)
    parser.add_argument("--val-per-map", type=positive_int, default=4)
    parser.add_argument("--test-per-map", type=positive_int, default=4)
    parser.add_argument("--seed", type=int, default=42)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser(
        "create", help="Create and internally verify a new release directory."
    )
    add_create_arguments(create_parser)
    verify_parser = commands.add_parser(
        "verify", help="Verify a release and all referenced source files."
    )
    verify_parser.add_argument("--release-dir", type=Path, required=True)
    verify_parser.add_argument(
        "--campaign-dir",
        type=Path,
        default=None,
        help="Override the source campaign root after relocating the dataset.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "create":
            manifest, policy = build_release(
                args.campaign_dir,
                maps=tuple(args.maps or DEFAULT_MAPS),
                release_id=args.release_id,
                feature_set=args.feature_set,
                feature_sets_path=args.feature_sets,
                runs_per_map=args.runs_per_map,
                train_per_map=args.train_per_map,
                val_per_map=args.val_per_map,
                test_per_map=args.test_per_map,
                seed=args.seed,
            )
            write_release_directory(
                args.release_dir,
                manifest=manifest,
                policy=policy,
            )
            summary = verify_release(args.release_dir)
            print(
                "[release_normal_dataset] created "
                f"{summary['selected_records']} selected + "
                f"{summary['reserve_records']} reserve records"
            )
        else:
            summary = verify_release(
                args.release_dir,
                campaign_dir=args.campaign_dir,
            )
            print(
                "[release_normal_dataset] verified "
                f"{summary['selected_records']} selected + "
                f"{summary['reserve_records']} reserve records"
            )
        print(f"[release_normal_dataset] dataset_sha256={summary['dataset_sha256']}")
        print(f"[release_normal_dataset] release_dir={summary['release_dir']}")
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        yaml.YAMLError,
        ReleaseError,
    ) as exc:
        print(f"[release_normal_dataset] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
