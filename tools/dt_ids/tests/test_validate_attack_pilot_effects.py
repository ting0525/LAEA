import csv
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "validate_attack_pilot_effects.py"
)
SPEC = importlib.util.spec_from_file_location(
    "validate_attack_pilot_effects", MODULE_PATH
)
effects = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(effects)


PROFILES = {
    "gps_bias_5m": {
        "source": "gps",
        "mode": "bias",
        "severity": "sweep",
        "ramp_s": 12.0,
        "duration_s": 30.0,
        "recovery_s": 8.0,
        "vector": [5.0, 0.0, 0.0],
    },
    "gps_velocity_1p0": {
        "source": "gps",
        "mode": "velocity_bias",
        "severity": "sweep",
        "ramp_s": 5.0,
        "duration_s": 30.0,
        "recovery_s": 8.0,
        "vector": [1.0, 0.0, 0.0],
    },
    "imu_gyro_0p05": {
        "source": "imu",
        "mode": "gyro_bias",
        "severity": "sweep",
        "ramp_s": 5.0,
        "duration_s": 30.0,
        "recovery_s": 8.0,
        "vector": [0.0, 0.0, 0.05],
    },
    "baro_1p0": {
        "source": "barometer",
        "mode": "drift",
        "severity": "sweep",
        "ramp_s": 15.0,
        "duration_s": 30.0,
        "recovery_s": 15.0,
        "scalar": 1.0,
    },
}


def attack_scale(relative_t, profile):
    relative_t = np.asarray(relative_t)
    scale = np.zeros_like(relative_t, dtype=float)
    active = (relative_t >= 0.0) & (relative_t < profile["duration_s"])
    if profile["ramp_s"] > 0.0:
        scale[active] = np.minimum(
            relative_t[active] / profile["ramp_s"], 1.0
        )
    else:
        scale[active] = 1.0
    recovery = (
        (relative_t >= profile["duration_s"])
        & (
            relative_t
            < profile["duration_s"] + profile["recovery_s"]
        )
    )
    scale[recovery] = 1.0 - (
        (relative_t[recovery] - profile["duration_s"])
        / profile["recovery_s"]
    )
    return scale


class SyntheticCampaign:
    def __init__(self, root):
        self.root = Path(root)
        self.runs = self.root / "runs"
        self.runs.mkdir(parents=True)
        (self.root / "campaign_plan.json").write_text(
            json.dumps(
                {
                    "campaign_id": "synthetic_attack_pilot",
                    "plan_digest": "0" * 64,
                }
            ),
            encoding="utf-8",
        )

    def add_task(
        self,
        profile_name,
        *,
        inject=True,
        attributable=True,
        retained=True,
        state="completed",
        drop_column=None,
        manifest_start=100.0,
        csv_start=99.5,
        csv_end=200.0,
    ):
        profile = dict(PROFILES[profile_name])
        task_id = "indoor_01__%s__a01" % profile_name
        task_dir = self.runs / task_id
        task_dir.mkdir()
        task = {
            "schema_version": "laea-attack-pilot-task-v1",
            "task_id": task_id,
            "map": "indoor_01",
            "profile": profile_name,
            "seed": 1234,
            "severity": profile["severity"],
            "transport": "nosip",
            "attack": {"name": profile_name, **profile},
        }
        (task_dir / "task_spec.json").write_text(
            json.dumps(task), encoding="utf-8"
        )

        run_id = "run_001"
        onset = 30.0
        t = np.arange(csv_start, csv_end + 0.0001, 0.05)
        relative = t - (manifest_start + onset)
        scale = attack_scale(relative, profile) if inject else np.zeros_like(t)
        gt_x = 0.2 * (t - manifest_start)
        gt_y = 0.1 * np.sin(0.1 * (t - manifest_start))
        gt_z = np.ones_like(t)
        frame = pd.DataFrame(
            {
                "run_id": run_id,
                "scenario": "attack_pilot",
                "transport_mode": "nosip",
                "world_name": "indoor_01",
                "t": t,
            }
        )

        if profile_name == "gps_bias_5m":
            latitude = 24.0
            longitude = 120.0
            gps_east = gt_x + 5.0 * scale
            gps_north = gt_y
            frame["gps_lat"] = latitude + np.rad2deg(
                gps_north / effects.EARTH_RADIUS_M
            )
            frame["gps_lon"] = longitude + np.rad2deg(
                gps_east
                / (
                    effects.EARTH_RADIUS_M
                    * math.cos(math.radians(latitude))
                )
            )
            frame["gps_alt"] = 500.0 + gt_z
            frame["px_gt"] = gt_x
            frame["py_gt"] = gt_y
            frame["pz_gt"] = gt_z
        elif profile_name == "gps_velocity_1p0":
            frame["vel_x"] = 0.2
            frame["vel_y"] = 0.0
            frame["gps_vx"] = 0.2 + scale
            frame["gps_vy"] = 0.0
        elif profile_name == "imu_gyro_0p05":
            frame["yaw"] = 0.02 * (t - manifest_start)
            frame["ang_vel_z"] = 0.02 + 0.05 * scale
        elif profile_name == "baro_1p0":
            reported_altitude = scale
            frame["static_pressure"] = 100000.0 * np.power(
                1.0 - reported_altitude / 44330.0,
                1.0 / 0.1903,
            )
            frame["pz_gt"] = gt_z

        if drop_column is not None:
            frame = frame.drop(columns=[drop_column])
        kpi_path = task_dir / "kpi_log_run_001.csv"
        frame.to_csv(kpi_path, index=False)

        ended = csv_end
        duration = ended - manifest_start
        manifest_fields = [
            "manifest_version",
            "run_id",
            "scenario",
            "transport_mode",
            "world_name",
            "started_at_s",
            "ended_at_s",
            "duration_s",
            "outcome",
            "log_retained",
            "log_deleted",
            "delete_reason",
            "attack_source",
            "attack_mode",
            "attack_severity",
            "attack_seed",
            "attack_scheduled_onset_s",
            "attack_actual_onset_s",
        ]
        manifest = {
            "manifest_version": "1",
            "run_id": run_id,
            "scenario": "attack_pilot",
            "transport_mode": "nosip",
            "world_name": "indoor_01",
            "started_at_s": str(manifest_start),
            "ended_at_s": str(ended),
            "duration_s": str(duration),
            "outcome": "TIMEOUT_NO_FINISH",
            "log_retained": "true" if retained else "false",
            "log_deleted": "false" if retained else "true",
            "delete_reason": "TIMEOUT_NO_FINISH",
            "attack_source": profile["source"],
            "attack_mode": profile["mode"],
            "attack_severity": profile["severity"],
            "attack_seed": "1234",
            "attack_scheduled_onset_s": "29.95",
            "attack_actual_onset_s": str(onset),
        }
        with (task_dir / "run_manifest.csv").open(
            "w", newline="", encoding="utf-8"
        ) as target:
            writer = csv.DictWriter(target, fieldnames=manifest_fields)
            writer.writeheader()
            writer.writerow(manifest)

        result = {
            "schema_version": "laea-attack-pilot-result-v1",
            "task_id": task_id,
            "state": state,
            "map": "indoor_01",
            "profile": profile_name,
            "source": profile["source"],
            "mode": profile["mode"],
            "severity": profile["severity"],
            "seed": 1234,
            "transport": "nosip",
            "run_id": run_id,
            "outcome": "TIMEOUT_NO_FINISH",
            "log_retained": retained,
            "attributable": attributable,
            "scheduled_onset_s": 29.95,
            "actual_onset_s": onset,
            "duration_s": duration,
            "kpi_path": str(kpi_path.resolve()),
        }
        (task_dir / "attempt_result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
        return task_dir


class ValidateAttackPilotEffectsTest(unittest.TestCase):
    def test_four_source_profiles_are_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            for name in PROFILES:
                campaign.add_task(name)
            report = effects.validate_campaign(campaign.root)

        self.assertTrue(report["summary"]["all_eligible_effects_verified"])
        self.assertEqual(report["summary"]["verified_effect_tasks"], 4)
        self.assertRegex(
            report["validator"]["script_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            report["ground_truth_policy"]["ground_truth_columns_used"],
            ["px_gt", "py_gt", "pz_gt"],
        )
        by_profile = {task["profile"]: task for task in report["tasks"]}
        self.assertAlmostEqual(
            by_profile["gps_bias_5m"]["effects"]["active_minus_pre"],
            5.0,
            places=3,
        )
        self.assertAlmostEqual(
            by_profile["gps_velocity_1p0"]["effects"]["active_minus_pre"],
            1.0,
            places=3,
        )
        self.assertAlmostEqual(
            by_profile["imu_gyro_0p05"]["effects"]["active_minus_pre"],
            0.05,
            places=3,
        )
        self.assertAlmostEqual(
            by_profile["baro_1p0"]["effects"]["active_minus_pre"],
            1.0,
            places=3,
        )
        for task in report["tasks"]:
            self.assertTrue(task["metric"]["evaluation_only"])
            self.assertFalse(task["metric"]["eligible_for_model_input"])
            self.assertRegex(
                task["provenance"]["attempt_result_sha256"],
                r"^[0-9a-f]{64}$",
            )

    def test_ineligible_result_is_skipped_without_reading_missing_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            campaign.add_task("gps_bias_5m")
            skipped = campaign.add_task(
                "baro_1p0", attributable=False, drop_column="pz_gt"
            )
            # Demonstrate that only result eligibility is consulted for this
            # task; its other inputs can be absent/corrupt without processing.
            (skipped / "task_spec.json").unlink()
            report = effects.validate_campaign(campaign.root)

        self.assertEqual(report["summary"]["eligible_tasks"], 1)
        self.assertEqual(report["summary"]["verified_effect_tasks"], 1)
        self.assertEqual(report["summary"]["skipped_ineligible_tasks"], 1)
        self.assertEqual(report["skipped_tasks"][0]["reason"], "not_attributable")

    def test_malformed_attempt_result_is_invalid_without_crashing_campaign(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            campaign.add_task("gps_bias_5m")
            malformed = campaign.add_task("baro_1p0")
            (malformed / "attempt_result.json").write_text(
                "{not valid JSON", encoding="utf-8"
            )
            report = effects.validate_campaign(campaign.root)

        self.assertEqual(report["summary"]["eligible_tasks"], 1)
        self.assertEqual(report["summary"]["verified_effect_tasks"], 1)
        self.assertEqual(report["summary"]["invalid_tasks"], 1)
        self.assertIn(
            "attempt result is unreadable",
            report["invalid_tasks"][0]["errors"][0],
        )
        self.assertFalse(report["summary"]["all_eligible_effects_verified"])

    def test_missing_ground_truth_column_is_invalid_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            campaign.add_task("gps_bias_5m", drop_column="px_gt")
            report = effects.validate_campaign(campaign.root)

        self.assertFalse(report["summary"]["all_eligible_effects_verified"])
        self.assertEqual(report["summary"]["invalid_tasks"], 1)
        self.assertIn("missing metric columns", report["invalid_tasks"][0]["errors"][0])

    def test_inconsistent_time_base_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            campaign.add_task(
                "baro_1p0",
                manifest_start=102.5,
                csv_start=99.5,
                csv_end=200.0,
            )
            report = effects.validate_campaign(campaign.root)

        self.assertEqual(report["summary"]["invalid_tasks"], 1)
        self.assertIn("time bases", report["invalid_tasks"][0]["errors"][0])

    def test_short_stable_post_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            # GPS lifecycle ends at onset+38s. End only 0.5s into the requested
            # stable-post window, below both the count and span requirements.
            campaign.add_task("gps_bias_5m", csv_end=169.5)
            report = effects.validate_campaign(campaign.root)

        self.assertEqual(report["summary"]["invalid_tasks"], 1)
        self.assertIn("stable_post window", report["invalid_tasks"][0]["errors"][0])

    def test_attributable_metadata_without_effect_is_not_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            campaign.add_task("gps_velocity_1p0", inject=False)
            report = effects.validate_campaign(campaign.root)

        self.assertEqual(report["summary"]["effect_not_verified_tasks"], 1)
        self.assertFalse(report["summary"]["all_eligible_effects_verified"])
        task = report["tasks"][0]
        self.assertEqual(task["task_status"], "effect_not_verified")
        self.assertFalse(task["effects"]["effect_verified"])

    def test_direct_source_effect_that_never_recovers_is_not_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign = SyntheticCampaign(temp)
            task_dir = campaign.add_task("gps_bias_5m")
            path = task_dir / "kpi_log_run_001.csv"
            frame = pd.read_csv(path)
            # Lifecycle onset=130, main duration ends at t=160. Force the
            # reported GPS east residual to stay at +5 m through recovery/post.
            stuck = frame["t"] >= 160.0
            latitude = 24.0
            longitude = 120.0
            gps_east = frame["px_gt"] + 5.0
            frame.loc[stuck, "gps_lon"] = longitude + np.rad2deg(
                gps_east[stuck]
                / (
                    effects.EARTH_RADIUS_M
                    * math.cos(math.radians(latitude))
                )
            )
            frame.to_csv(path, index=False)
            report = effects.validate_campaign(campaign.root)

        task = report["tasks"][0]
        self.assertEqual(task["task_status"], "effect_not_verified")
        self.assertFalse(
            task["effects"]["verification_checks"][
                "stable_post_absolute_fraction"
            ]["passed"]
        )

    def test_cli_writes_atomic_json_and_optional_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign_root = Path(temp) / "campaign"
            campaign = SyntheticCampaign(campaign_root)
            campaign.add_task("baro_1p0")
            json_out = Path(temp) / "report.json"
            markdown_out = Path(temp) / "report.md"
            rc = effects.main(
                [
                    "--campaign-dir",
                    str(campaign.root),
                    "--out",
                    str(json_out),
                    "--markdown-out",
                    str(markdown_out),
                ]
            )
            report = json.loads(json_out.read_text(encoding="utf-8"))
            markdown = markdown_out.read_text(encoding="utf-8")

        self.assertEqual(rc, 0)
        self.assertTrue(report["summary"]["all_eligible_effects_verified"])
        self.assertIn(
            "Ground-truth fields are used only for simulator evaluation",
            markdown,
        )

    def test_cliffs_delta_handles_ties_exactly(self):
        active = np.array([1.0, 2.0, 2.0])
        pre = np.array([0.0, 2.0])
        # 3 wins, 1 loss, 2 ties out of 6 comparisons.
        self.assertAlmostEqual(effects.cliffs_delta(active, pre), 1.0 / 3.0)


if __name__ == "__main__":
    unittest.main()
