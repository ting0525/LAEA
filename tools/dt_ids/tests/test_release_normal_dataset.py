from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from release_normal_dataset import (  # noqa: E402
    DEFAULT_MAPS,
    ReleaseError,
    build_release,
    sha256_file,
    verify_release,
    write_release_directory,
)


RUN_MANIFEST_FIELDS = (
    "manifest_version",
    "run_id",
    "scenario",
    "transport_mode",
    "world_name",
    "outcome",
    "log_retained",
)
QUALITY_FIELDS = (
    "mission_id",
    "file_path",
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
    "quality_ok",
)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class NormalDatasetReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.campaign = self.root / "normal_four_maps_v1_test"
        self.campaign.mkdir()
        self.feature_sets = self.root / "feature_sets.yaml"
        self.feature_sets.write_text(
            "feature_sets:\n"
            "  sensor_multimodal_baseline:\n"
            "    - feature_a\n"
            "    - feature_b\n",
            encoding="utf-8",
        )
        self.counts = {
            "indoor_01": 27,
            "indoor_02": 25,
            "lab_corridor_01": 26,
            "lab_rooms_01": 25,
        }
        self._build_campaign()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build_campaign(self) -> None:
        write_json(
            self.campaign / "campaign_summary.json",
            {"campaign_id": self.campaign.name, "state": "COMPLETED"},
        )
        write_json(
            self.campaign / "final_normal_collection_v1_status.json",
            {
                "approved_maps": list(DEFAULT_MAPS),
                "campaign_dir": str(self.campaign),
                "campaign_id": self.campaign.name,
                "state": "COMPLETED",
                "updated_at_utc": "2026-07-29T00:00:00+00:00",
            },
        )
        worlds = self.root / "worlds"
        worlds.mkdir()
        for environment in DEFAULT_MAPS:
            world_file = worlds / f"{environment}.world"
            world_file.write_text(f"world={environment}\n", encoding="utf-8")
            map_dir = self.campaign / environment
            map_dir.mkdir()
            write_json(
                map_dir / "collection_card.json",
                {
                    "attack_profile": "none",
                    "campaign_id": self.campaign.name,
                    "scenario": "normal",
                    "transport_mode": "nosip",
                    "world": {
                        "file": str(world_file),
                        "name": environment,
                        "sha256": sha256_file(world_file),
                    },
                },
            )
            write_json(map_dir / "batch_progress.json", {"state": "COMPLETED"})

            run_rows: list[dict[str, object]] = []
            quality_rows: list[dict[str, object]] = []
            for sequence in range(1, self.counts[environment] + 1):
                source_run_id = f"run_{sequence:03d}"
                source_path = map_dir / f"kpi_log_{source_run_id}.csv"
                source_path.write_text(
                    "run_id,scenario,world_name,feature_a,feature_b\n"
                    f"{source_run_id},normal,{environment},{sequence},"
                    f"{environment}-{sequence}\n",
                    encoding="utf-8",
                )
                run_rows.append(
                    {
                        "manifest_version": 1,
                        "run_id": source_run_id,
                        "scenario": "normal",
                        "transport_mode": "nosip",
                        "world_name": environment,
                        "outcome": "SUCCESS_FINISH",
                        "log_retained": "true",
                    }
                )
                quality_rows.append(
                    {
                        "mission_id": f"kpi_log_{source_run_id}",
                        "file_path": str(source_path),
                        "num_rows": 5000 + sequence,
                        "t_start": 100.0,
                        "t_end": 400.0,
                        "duration_s": 300.0,
                        "dt_min": 0.049,
                        "dt_mean": 0.05,
                        "dt_max": 0.051,
                        "zero_dt_count": 0,
                        "negative_dt_count": 0,
                        "gps_nan_ratio": 0.0,
                        "gps_valid_ratio": 1.0,
                        "e_pos_mean": 0.1,
                        "e_pos_p95": 0.2,
                        "e_pos_max": 0.3,
                        "quality_ok": 1,
                    }
                )
            write_csv(map_dir / "run_manifest.csv", RUN_MANIFEST_FIELDS, run_rows)
            write_csv(map_dir / "quality_manifest.csv", QUALITY_FIELDS, quality_rows)

    def _payloads(self) -> tuple[dict[str, object], dict[str, object]]:
        return build_release(
            self.campaign,
            maps=DEFAULT_MAPS,
            release_id="normal_dataset_v1",
            feature_set="sensor_multimodal_baseline",
            feature_sets_path=self.feature_sets,
            runs_per_map=25,
            train_per_map=17,
            val_per_map=4,
            test_per_map=4,
            seed=42,
        )

    def test_create_has_balanced_run_level_splits_and_reserves(self) -> None:
        manifest, policy = self._payloads()
        release_dir = self.root / "release"
        write_release_directory(release_dir, manifest=manifest, policy=policy)
        summary = verify_release(release_dir, campaign_dir=self.campaign)

        self.assertTrue(summary["verified"])
        self.assertEqual(summary["selected_records"], 100)
        self.assertEqual(summary["reserve_records"], 3)
        self.assertEqual(
            manifest["metadata"]["feature_columns"],
            ["feature_a", "feature_b"],
        )
        self.assertEqual(
            len({record["run_id"] for record in manifest["records"]}),
            100,
        )
        for environment in DEFAULT_MAPS:
            splits = Counter(
                record["split"]
                for record in manifest["records"]
                if record["environment"] == environment
            )
            self.assertEqual(splits, {"train": 17, "val": 4, "test": 4})
        self.assertEqual(
            {
                record["run_id"]
                for record in manifest["reserves"]
            },
            {
                "indoor_01/run_026",
                "indoor_01/run_027",
                "lab_corridor_01/run_026",
            },
        )

    def test_rebuild_is_byte_reproducible(self) -> None:
        first_manifest, first_policy = self._payloads()
        second_manifest, second_policy = self._payloads()
        first = self.root / "release_a"
        second = self.root / "release_b"
        write_release_directory(first, manifest=first_manifest, policy=first_policy)
        write_release_directory(second, manifest=second_manifest, policy=second_policy)

        for filename in (
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
        ):
            self.assertEqual(
                (first / filename).read_bytes(),
                (second / filename).read_bytes(),
                filename,
            )

    def test_verify_detects_source_tampering(self) -> None:
        manifest, policy = self._payloads()
        release_dir = self.root / "release"
        write_release_directory(release_dir, manifest=manifest, policy=policy)
        source = self.campaign / manifest["records"][0]["relative_path"]
        with source.open("a", encoding="utf-8") as target:
            target.write("tampered\n")

        with self.assertRaisesRegex(ReleaseError, "checksum mismatch"):
            verify_release(release_dir, campaign_dir=self.campaign)

    def test_missing_model_feature_blocks_release(self) -> None:
        source = self.campaign / "indoor_01" / "kpi_log_run_001.csv"
        source.write_text(
            "run_id,scenario,world_name,feature_a\n"
            "run_001,normal,indoor_01,1\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ReleaseError, "missing feature columns"):
            self._payloads()

    def test_ground_truth_feature_is_rejected(self) -> None:
        self.feature_sets.write_text(
            "feature_sets:\n"
            "  sensor_multimodal_baseline:\n"
            "    - feature_a\n"
            "    - e_pos\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ReleaseError, "evaluation-only columns"):
            self._payloads()

    def test_missing_reserve_feature_blocks_release(self) -> None:
        source = self.campaign / "indoor_01" / "kpi_log_run_026.csv"
        source.write_text(
            "run_id,scenario,world_name,feature_a\n"
            "run_026,normal,indoor_01,26\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ReleaseError, "missing feature columns"):
            self._payloads()


if __name__ == "__main__":
    unittest.main()
