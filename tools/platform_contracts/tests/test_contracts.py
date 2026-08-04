from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import MappingProxyType

from tools.platform_contracts import (
    ArtifactVerificationError,
    ExperimentSpec,
    FileRef,
    LineageValidationError,
    ModelArtifact,
    RunArtifact,
    SerializationError,
    SpecValidationError,
    canonical_json,
    load_document,
    load_experiment_spec,
    load_model_artifact,
    load_run_artifact,
    sha256_file,
    validate_full_lineage,
    validate_lineage,
    verify_file_ref,
)
from tools.platform_contracts.cli import main
from tools.platform_contracts.canonical import pretty_json
from tools.platform_contracts.validation import UINT32_MAX

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
NORMAL_EXAMPLE = PACKAGE_ROOT / "examples" / "normal_experiment.json"
ATTACK_EXAMPLE = PACKAGE_ROOT / "examples" / "attack_experiment.json"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def provenance() -> dict:
    return {
        "created_at_utc": "2026-07-28T10:00:00Z",
        "created_by": "stdlib unittest",
        "tool_version": "1.0.0",
    }


def run_mapping(
    run_id: str,
    split: str,
    *,
    experiment_id: str = "exp-001",
    experiment_digest: str = DIGEST_A,
    seed: int = 7,
) -> dict:
    return {
        "schema_version": "platform-run-artifact-v2",
        "run_uid": f"indoor_01/{run_id}",
        "run_id": run_id,
        "experiment_id": experiment_id,
        "experiment_digest": experiment_digest,
        "campaign_id": "campaign-001",
        "campaign_kind": "normal",
        "world": {
            "name": "indoor_01",
            "world_file": "/tmp/worlds/indoor_01.world",
            "sha256": DIGEST_B,
        },
        "transport_mode": "nosip",
        "seed": seed,
        "outcome": "SUCCESS_FINISH",
        "split": split,
        "feature_schema": {
            "name": "gps_derived",
            "columns": ["pos_x", "pos_y"],
        },
        "data_files": [
            {
                "role": "kpi_log",
                "path": f"/tmp/{run_id}.csv",
                "sha256": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
                "size_bytes": 12,
                "num_rows": 100,
            }
        ],
        "quality": {
            "num_rows": 100,
            "duration_s": 10.0,
            "gps_valid_ratio": 1.0,
            "e_pos_p95": 0.4,
            "e_pos_max": 0.7,
            "quality_ok": True,
        },
        "timing": {
            "started_at_s": 2.0,
            "ended_at_s": 12.0,
            "duration_s": 10.0,
        },
        "recorded_at_utc": "2026-07-28T10:01:00+00:00",
        "provenance": provenance(),
    }


def model_mapping() -> dict:
    return {
        "schema_version": "platform-model-artifact-v2",
        "model_uid": "lstm-ae-001",
        "experiment_id": "exp-001",
        "experiment_digest": DIGEST_A,
        "algorithm": "lstm_ae",
        "framework": "pytorch",
        "feature_schema": {
            "name": "gps_derived",
            "columns": ["pos_x", "pos_y"],
        },
        "training_data": {
            "train_run_uids": ["indoor_01/run_001"],
            "val_run_uids": ["indoor_01/run_002"],
            "test_run_uids": [],
            "registry_path": "/tmp/registry.json",
            "registry_digest": DIGEST_B,
        },
        "threshold": {
            "name": "reconstruction_error",
            "value": 0.12,
            "selection_policy": "validation_p99",
            "selected_on": "val",
            "target_false_positive_rate": 0.01,
        },
        "artifacts": [
            {
                "role": "model",
                "path": "/tmp/model.onnx",
                "sha256": DIGEST_B,
            },
            {
                "role": "threshold",
                "path": "/tmp/threshold.json",
                "sha256": DIGEST_C,
            },
        ],
        "metrics": {
            "val_loss": 0.05,
            "false_alarms_per_hour": 0.25,
        },
        "trained_at_utc": "2026-07-28T10:02:00Z",
        "provenance": provenance(),
    }


def normal_spec_mapping() -> dict:
    return {
        "schema_version": "platform-experiment-spec-v2",
        "experiment_id": "exp-001",
        "campaign_kind": "normal",
        "worlds": [
            {
                "name": "indoor_01",
                "world_file": "/tmp/worlds/indoor_01.world",
                "sha256": DIGEST_B,
            }
        ],
        "repetitions": 2,
        "seeds": [7, 8],
        "transport_mode": "nosip",
        "feature_set": {
            "name": "gps_derived",
            "columns": ["pos_x", "pos_y"],
            "catalog_path": "tools/dt_ids/feature_sets.yaml",
            "catalog_sha256": DIGEST_C,
        },
        "runtime": {
            "max_duration_s": 180.0,
            "delete_on_non_success": True,
            "mission_aware": True,
            "aiottalk_rtp": False,
            "nosip_rtp": True,
        },
        "acceptance": {
            "required_outcomes": ["SUCCESS_FINISH"],
            "accepted_runs_per_world": 2,
            "require_log_retained": True,
            "require_quality_ok": True,
            "require_attack_attributable": False,
        },
        "data_split": {
            "unit": "run",
            "seed": 20260728,
            "train_per_world": 1,
            "val_per_world": 1,
            "test_per_world": 0,
        },
        "provenance": provenance(),
    }


def attack_spec_mapping() -> dict:
    return {
        "schema_version": "platform-experiment-spec-v2",
        "experiment_id": "attack-exp-001",
        "campaign_kind": "attack",
        "worlds": [
            {
                "name": "indoor_01",
                "world_file": "/tmp/worlds/attack_indoor_01.world",
                "sha256": DIGEST_D,
            }
        ],
        "repetitions": 1,
        "seeds": [9],
        "transport_mode": "nosip",
        "feature_set": {
            "name": "gps_derived",
            "columns": ["pos_x", "pos_y"],
            "catalog_path": "tools/dt_ids/feature_sets.yaml",
            "catalog_sha256": DIGEST_C,
        },
        "runtime": {
            "max_duration_s": 180.0,
            "delete_on_non_success": False,
            "mission_aware": True,
            "aiottalk_rtp": False,
            "nosip_rtp": True,
        },
        "acceptance": {
            "required_outcomes": ["SUCCESS_FINISH", "FAIL_SLAM"],
            "accepted_runs_per_world": 1,
            "require_log_retained": True,
            "require_quality_ok": False,
            "require_attack_attributable": True,
        },
        "attack_plan": {
            "profiles": [
                {
                    "name": "gps_bias_medium",
                    "source": "gps",
                    "mode": "bias",
                    "severity": "medium",
                    "ramp_s": 1.0,
                    "duration_s": 5.0,
                    "recovery_s": 1.0,
                    "vector": [2.0, 0.0, 0.0],
                }
            ],
            "runs_per_profile": 1,
            "onset_window_s": [2.0, 3.0],
        },
        "provenance": provenance(),
    }


def attack_run_mapping(
    experiment_digest: str,
    *,
    split: str = "test",
    attributable: bool = True,
) -> dict:
    payload = run_mapping(
        "run_001",
        split,
        experiment_id="attack-exp-001",
        experiment_digest=experiment_digest,
        seed=9,
    )
    payload["campaign_id"] = "attack-campaign-001"
    payload["campaign_kind"] = "attack"
    payload["world"]["world_file"] = "/tmp/worlds/attack_indoor_01.world"
    payload["world"]["sha256"] = DIGEST_D
    payload["outcome"] = "FAIL_SLAM"
    payload["quality"]["quality_ok"] = False
    payload["data_files"][0]["sha256"] = hashlib.sha256(b"attack-run_001").hexdigest()
    payload["attack"] = {
        "profile": "gps_bias_medium",
        "source": "gps",
        "mode": "bias",
        "severity": "medium",
        "seed": 9,
        "scheduled_onset_s": 2.0,
        "actual_onset_s": 2.5 if attributable else None,
        "attributable": attributable,
    }
    return payload


def full_lineage_fixture():
    training_spec = ExperimentSpec.from_dict(normal_spec_mapping())
    evaluation_spec = ExperimentSpec.from_dict(attack_spec_mapping())
    model_payload = model_mapping()
    model_payload["experiment_id"] = training_spec.experiment_id
    model_payload["experiment_digest"] = training_spec.spec_digest()
    model_payload["evaluation_data"] = [
        {
            "experiment_id": evaluation_spec.experiment_id,
            "experiment_digest": evaluation_spec.spec_digest(),
            "test_run_uids": ["indoor_01/run_001"],
        }
    ]
    model = ModelArtifact.from_dict(model_payload)
    train = RunArtifact.from_dict(
        run_mapping(
            "run_001",
            "train",
            experiment_digest=training_spec.spec_digest(),
            seed=7,
        )
    )
    validation = RunArtifact.from_dict(
        run_mapping(
            "run_002",
            "val",
            experiment_digest=training_spec.spec_digest(),
            seed=8,
        )
    )
    attack = RunArtifact.from_dict(attack_run_mapping(evaluation_spec.spec_digest()))
    return model, training_spec, evaluation_spec, train, validation, attack


class ExperimentSpecTests(unittest.TestCase):
    def test_normal_and_attack_examples_are_valid(self) -> None:
        normal = load_experiment_spec(NORMAL_EXAMPLE)
        attack = load_experiment_spec(ATTACK_EXAMPLE)
        self.assertEqual(normal.planned_runs(), 100)
        self.assertEqual(normal.data_split.total_per_world(), 25)
        self.assertEqual(attack.attack_plan.total_runs_per_world(), 4)

    def test_contradictory_spec_collects_errors(self) -> None:
        payload = copy.deepcopy(load_document(NORMAL_EXAMPLE))
        payload["transport_mode"] = "aiottalk_rtp"
        payload["acceptance"]["accepted_runs_per_world"] = 26
        payload["data_split"]["unit"] = "row"
        with self.assertRaises(SpecValidationError) as caught:
            ExperimentSpec.from_dict(payload)
        paths = caught.exception.paths()
        self.assertIn("spec.runtime", paths)
        self.assertIn("spec.acceptance.accepted_runs_per_world", paths)
        self.assertIn("spec.data_split.unit", paths)

    def test_unknown_key_is_rejected(self) -> None:
        payload = copy.deepcopy(load_document(NORMAL_EXAMPLE))
        payload["repetitons"] = payload["repetitions"]
        with self.assertRaises(SpecValidationError) as caught:
            ExperimentSpec.from_dict(payload)
        self.assertTrue(any("unknown field" in issue.message for issue in caught.exception.issues))

    def test_seed_uint32_boundary_and_overflow(self) -> None:
        payload = copy.deepcopy(load_document(NORMAL_EXAMPLE))
        payload["worlds"] = payload["worlds"][:1]
        payload["repetitions"] = 1
        payload.pop("seed_policy")
        payload["seeds"] = [UINT32_MAX]
        payload["acceptance"]["accepted_runs_per_world"] = 1
        payload["data_split"].update(
            train_per_world=1,
            val_per_world=0,
            test_per_world=0,
        )
        self.assertEqual(ExperimentSpec.from_dict(payload).resolved_seeds(), (UINT32_MAX,))

        payload["seeds"] = [UINT32_MAX + 1]
        with self.assertRaises(SpecValidationError) as caught:
            ExperimentSpec.from_dict(payload)
        self.assertIn("spec.seeds[0]", caught.exception.paths())

    def test_digest_is_deterministic_and_identity_ignores_provenance(self) -> None:
        payload = load_document(NORMAL_EXAMPLE)
        reordered = {key: payload[key] for key in reversed(tuple(payload))}
        first = ExperimentSpec.from_dict(payload)
        second = ExperimentSpec.from_dict(reordered)
        self.assertEqual(first.digest(), second.digest())
        self.assertEqual(first.spec_digest(), second.spec_digest())

        changed = copy.deepcopy(payload)
        changed["provenance"]["created_by"] = "different operator"
        third = ExperimentSpec.from_dict(changed)
        self.assertEqual(first.spec_digest(), third.spec_digest())
        self.assertNotEqual(first.digest(), third.digest())

    def test_ground_truth_and_e_pos_are_forbidden_model_features(self) -> None:
        for forbidden in ("e_pos", "px_gt", "ground_truth_pose", "groundtruth_pose"):
            with self.subTest(forbidden=forbidden):
                payload = copy.deepcopy(load_document(NORMAL_EXAMPLE))
                payload["feature_set"]["columns"].append(forbidden)
                with self.assertRaises(SpecValidationError) as caught:
                    ExperimentSpec.from_dict(payload)
                self.assertIn("spec.feature_set.columns", caught.exception.paths())

    def test_invalid_timestamp_and_nonfinite_freeform_value_are_rejected(self) -> None:
        payload = copy.deepcopy(load_document(NORMAL_EXAMPLE))
        payload["provenance"]["created_at_utc"] = "2026-99-28T10:00:00Z"
        payload["labels"]["bad_number"] = float("nan")
        with self.assertRaises(SpecValidationError) as caught:
            ExperimentSpec.from_dict(payload)
        self.assertIn("spec.provenance.created_at_utc", caught.exception.paths())
        self.assertIn("spec.labels", caught.exception.paths())

    def test_spec_pins_world_and_feature_catalog_content(self) -> None:
        for field_path in ("world_sha", "columns", "catalog_sha"):
            with self.subTest(field_path=field_path):
                payload = copy.deepcopy(load_document(NORMAL_EXAMPLE))
                if field_path == "world_sha":
                    payload["worlds"][0].pop("sha256")
                elif field_path == "columns":
                    payload["feature_set"].pop("columns")
                else:
                    payload["feature_set"].pop("catalog_sha256")
                with self.assertRaises(SpecValidationError):
                    ExperimentSpec.from_dict(payload)


class LineageTests(unittest.TestCase):
    def test_run_and_model_roundtrip(self) -> None:
        run = RunArtifact.from_dict(run_mapping("run_001", "train"))
        model = ModelArtifact.from_dict(model_mapping())
        self.assertEqual(RunArtifact.from_dict(run.to_dict()).to_dict(), run.to_dict())
        self.assertEqual(ModelArtifact.from_dict(model.to_dict()).to_dict(), model.to_dict())
        self.assertEqual(ModelArtifact.from_dict(model.to_dict()).digest(), model.digest())
        self.assertEqual(model.metrics, (("false_alarms_per_hour", 0.25), ("val_loss", 0.05)))

    def test_json_file_roundtrip_loaders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_path = root / "run.json"
            model_path = root / "model.json"
            run_path.write_text(pretty_json(run_mapping("run_001", "train")), encoding="utf-8")
            model_path.write_text(pretty_json(model_mapping()), encoding="utf-8")
            self.assertEqual(load_run_artifact(run_path).run_id, "run_001")
            self.assertEqual(load_model_artifact(model_path).model_uid, "lstm-ae-001")

    def test_split_leakage_is_rejected(self) -> None:
        payload = model_mapping()
        payload["training_data"]["val_run_uids"] = ["indoor_01/run_001"]
        with self.assertRaises(LineageValidationError) as caught:
            ModelArtifact.from_dict(payload)
        self.assertTrue(
            any("more than one split" in issue.message for issue in caught.exception.issues)
        )

    def test_threshold_requires_declared_selection_split_data(self) -> None:
        payload = model_mapping()
        payload["training_data"]["val_run_uids"] = []
        with self.assertRaises(LineageValidationError) as caught:
            ModelArtifact.from_dict(payload)
        self.assertIn("model_artifact.threshold.selected_on", caught.exception.paths())

    def test_model_to_run_lineage_cross_check(self) -> None:
        model = ModelArtifact.from_dict(model_mapping())
        train = RunArtifact.from_dict(run_mapping("run_001", "train"))
        validation = RunArtifact.from_dict(run_mapping("run_002", "val"))
        validate_lineage(model, [train, validation])

        wrong_id = RunArtifact.from_dict(
            run_mapping("run_002", "val", experiment_id="other-exp")
        )
        with self.assertRaises(LineageValidationError) as caught:
            validate_lineage(model, [train, wrong_id])
        self.assertTrue(any("experiment id" in issue.message for issue in caught.exception.issues))

        wrong_columns_payload = run_mapping("run_002", "val")
        wrong_columns_payload["feature_schema"]["columns"] = ["pos_y", "pos_x"]
        wrong_columns = RunArtifact.from_dict(wrong_columns_payload)
        with self.assertRaises(LineageValidationError) as caught:
            validate_lineage(model, [train, wrong_columns])
        self.assertTrue(
            any("different column order" in issue.message for issue in caught.exception.issues)
        )

    def test_run_lineage_rejects_ground_truth_features(self) -> None:
        payload = run_mapping("run_001", "train")
        payload["feature_schema"]["columns"].append("e_pos")
        with self.assertRaises(LineageValidationError) as caught:
            RunArtifact.from_dict(payload)
        self.assertIn("run_artifact.feature_schema.columns", caught.exception.paths())

    def test_legal_cross_campaign_attack_evaluation_and_uid_collision(self) -> None:
        model, training_spec, evaluation_spec, train, validation, attack = (
            full_lineage_fixture()
        )
        # Normal train and attack test intentionally share run_uid. The
        # experiment digest disambiguates them.
        self.assertEqual(train.run_uid, attack.run_uid)
        self.assertEqual(attack.outcome, "FAIL_SLAM")
        self.assertFalse(attack.quality.quality_ok)
        validate_lineage(model, [train, validation, attack])
        validate_full_lineage(
            model,
            training_spec,
            [evaluation_spec],
            [train, validation, attack],
        )

        with self.assertRaises(LineageValidationError) as caught:
            validate_full_lineage(
                model,
                training_spec,
                [],
                [train, validation, attack],
            )
        self.assertTrue(
            any("no evaluation spec" in issue.message for issue in caught.exception.issues)
        )

    def test_evaluation_reference_requires_experiment_digest(self) -> None:
        payload = model_mapping()
        payload["evaluation_data"] = [
            {
                "experiment_id": "attack-exp-001",
                "test_run_uids": ["indoor_01/run_001"],
            }
        ]
        with self.assertRaises(LineageValidationError) as caught:
            ModelArtifact.from_dict(payload)
        self.assertIn(
            "model_artifact.evaluation_data[0].experiment_digest",
            caught.exception.paths(),
        )

    def test_attack_train_and_unattributable_attack_test_are_rejected(self) -> None:
        evaluation_spec = ExperimentSpec.from_dict(attack_spec_mapping())
        with self.assertRaises(LineageValidationError) as caught:
            RunArtifact.from_dict(
                attack_run_mapping(evaluation_spec.spec_digest(), split="train")
            )
        self.assertIn("run_artifact.split", caught.exception.paths())

        with self.assertRaises(LineageValidationError) as caught:
            RunArtifact.from_dict(
                attack_run_mapping(
                    evaluation_spec.spec_digest(),
                    split="test",
                    attributable=False,
                )
            )
        self.assertIn("run_artifact.split", caught.exception.paths())

    def test_evaluation_allowlist_rejects_unassigned_unattributable_run(self) -> None:
        model, _, evaluation_spec, train, validation, _ = full_lineage_fixture()
        attack = RunArtifact.from_dict(
            attack_run_mapping(
                evaluation_spec.spec_digest(),
                split="unassigned",
                attributable=False,
            )
        )
        with self.assertRaises(LineageValidationError) as caught:
            validate_lineage(model, [train, validation, attack])
        messages = [issue.message for issue in caught.exception.issues]
        self.assertTrue(any("not 'test'" in message for message in messages))
        self.assertTrue(any("not attributable" in message for message in messages))

    def test_attack_run_requires_seed(self) -> None:
        evaluation_spec = ExperimentSpec.from_dict(attack_spec_mapping())
        payload = attack_run_mapping(evaluation_spec.spec_digest())
        payload.pop("seed")
        with self.assertRaises(LineageValidationError) as caught:
            RunArtifact.from_dict(payload)
        self.assertIn("run_artifact.seed", caught.exception.paths())

    def test_duplicate_kpi_content_across_splits_is_rejected(self) -> None:
        model = ModelArtifact.from_dict(model_mapping())
        train_payload = run_mapping("run_001", "train")
        validation_payload = run_mapping("run_002", "val")
        validation_payload["data_files"][0]["sha256"] = train_payload["data_files"][0]["sha256"]
        train = RunArtifact.from_dict(train_payload)
        validation = RunArtifact.from_dict(validation_payload)
        with self.assertRaises(LineageValidationError) as caught:
            validate_lineage(model, [train, validation])
        self.assertTrue(
            any("duplicated flight content" in issue.message for issue in caught.exception.issues)
        )

    def test_full_lineage_checks_runtime_world_seed_and_feature_contract(self) -> None:
        model, training_spec, evaluation_spec, train, validation, attack = (
            full_lineage_fixture()
        )
        mutations = {
            "transport": ("transport_mode", "aiottalk_rtp"),
            "world": ("world.sha256", DIGEST_C),
            "seed": ("seed", 12345),
            "features": ("feature_schema.columns", ["pos_y", "pos_x"]),
        }
        for name, (field, value) in mutations.items():
            with self.subTest(name=name):
                payload = train.to_dict()
                if field == "world.sha256":
                    payload["world"]["sha256"] = value
                elif field == "feature_schema.columns":
                    payload["feature_schema"]["columns"] = value
                else:
                    payload[field] = value
                mutated = RunArtifact.from_dict(payload)
                with self.assertRaises(LineageValidationError):
                    validate_full_lineage(
                        model,
                        training_spec,
                        [evaluation_spec],
                        [mutated, validation, attack],
                    )


class SerializationAndCliTests(unittest.TestCase):
    def test_artifact_file_digest(self) -> None:
        content = b"FedDroneLab artifact\n\x00\xff"
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "model.onnx"
            artifact.write_bytes(content)
            self.assertEqual(sha256_file(artifact), hashlib.sha256(content).hexdigest())

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "duplicate.json"
            document.write_text('{"kind": "normal", "kind": "attack"}', encoding="utf-8")
            with self.assertRaises(SerializationError) as caught:
                load_document(document)
            self.assertIn("duplicate mapping key", str(caught.exception))

    def test_nonstandard_json_constants_are_rejected(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), tempfile.TemporaryDirectory() as directory:
                document = Path(directory) / "constant.json"
                document.write_text(f'{{"value": {constant}}}', encoding="utf-8")
                with self.assertRaises(SerializationError):
                    load_document(document)

    def test_canonical_json_supports_read_only_mapping(self) -> None:
        value = MappingProxyType({"nested": MappingProxyType({"value": 1})})
        self.assertEqual(canonical_json(value), '{"nested":{"value":1}}')
        self.assertEqual(pretty_json(value), '{\n  "nested": {\n    "value": 1\n  }\n}\n')

    def test_file_ref_verification_is_explicit(self) -> None:
        content = b"verified model artifact"
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "model.onnx"
            artifact.write_bytes(content)
            reference = FileRef(
                role="model",
                path=str(artifact),
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
            )
            verify_file_ref(reference)
            wrong = FileRef(
                role="model",
                path=str(artifact),
                sha256=DIGEST_A,
                size_bytes=len(content) + 1,
            )
            with self.assertRaises(ArtifactVerificationError) as caught:
                verify_file_ref(wrong)
            self.assertEqual(
                set(caught.exception.paths()),
                {"file.sha256", "file.size_bytes"},
            )

    def test_yaml_loader_is_optional_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "normal.yaml"
            document.write_text(NORMAL_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                import yaml  # noqa: F401
            except ImportError:
                with self.assertRaises(SerializationError) as caught:
                    load_document(document)
                self.assertIn("PyYAML", str(caught.exception))
            else:
                self.assertEqual(load_experiment_spec(document).campaign_kind, "normal")

    def test_cli_validates_example_without_writes(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["validate", "spec", str(NORMAL_EXAMPLE), "--json"])
        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "spec")

    def test_cli_runs_full_model_lineage_validation(self) -> None:
        model, training_spec, evaluation_spec, train, validation, attack = (
            full_lineage_fixture()
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = {
                "model": model.to_dict(),
                "training_spec": training_spec.to_dict(),
                "evaluation_spec": evaluation_spec.to_dict(),
                "train": train.to_dict(),
                "validation": validation.to_dict(),
                "attack": attack.to_dict(),
            }
            paths = {}
            for name, payload in documents.items():
                path = root / f"{name}.json"
                path.write_text(pretty_json(payload), encoding="utf-8")
                paths[name] = path
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate",
                        "model",
                        str(paths["model"]),
                        "--spec",
                        str(paths["training_spec"]),
                        "--evaluation-spec",
                        str(paths["evaluation_spec"]),
                        "--run",
                        str(paths["train"]),
                        "--run",
                        str(paths["validation"]),
                        "--run",
                        str(paths["attack"]),
                        "--json",
                    ]
                )
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
