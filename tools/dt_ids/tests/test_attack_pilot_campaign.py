import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "attack_pilot_campaign.py"
SPEC = importlib.util.spec_from_file_location("attack_pilot_campaign", MODULE_PATH)
pilot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pilot)


class AttackPilotCampaignTest(unittest.TestCase):
    def build_plan(self):
        return pilot.build_plan(
            pilot.DEFAULT_CONFIG,
            pilot.DEFAULT_WORLD_CATALOG,
            pilot.DEFAULT_ATTACK_CATALOG,
            "unit_test_campaign",
        )

    def test_plan_is_four_by_four_by_two_with_unique_seeds(self):
        plan = self.build_plan()
        self.assertEqual(len(plan["worlds"]), 4)
        self.assertEqual(len(plan["profiles"]), 4)
        self.assertEqual(len(plan["tasks"]), 32)
        self.assertEqual(len({task["task_id"] for task in plan["tasks"]}), 32)
        self.assertEqual(len({task["seed"] for task in plan["tasks"]}), 32)
        self.assertEqual(
            {(item["source"], item["mode"]) for item in plan["profiles"]},
            pilot.EXPECTED_ATTACK_KINDS,
        )
        self.assertTrue(all(item["severity"] == "sweep" for item in plan["profiles"]))

    def test_smoke_is_one_stable_map_attempt_per_attack_type(self):
        plan = self.build_plan()
        smoke = pilot.selected_tasks(plan, "smoke", [])
        self.assertEqual(len(smoke), 4)
        self.assertEqual({task["map"] for task in smoke}, {"indoor_01"})
        self.assertEqual({task["attempt_index"] for task in smoke}, {1})
        self.assertEqual(
            {(task["attack"]["source"], task["attack"]["mode"]) for task in smoke},
            pilot.EXPECTED_ATTACK_KINDS,
        )

    def test_runtime_environment_pins_labels_and_safe_retention(self):
        plan = self.build_plan()
        task = pilot.selected_tasks(plan, "smoke", [])[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = pilot.task_environment(task, root, root / "task", 1)
        self.assertEqual(env["EXP_WORLD_NAME"], task["map"])
        self.assertEqual(env["ATTACK_PROFILE"], task["profile"])
        self.assertEqual(env["ATTACK_SEED"], str(task["seed"]))
        self.assertEqual(env["ATTACK_ONSET_MIN_S"], str(task["onset_min_s"]))
        self.assertEqual(env["ATTACK_ONSET_MAX_S"], str(task["onset_max_s"]))
        self.assertEqual(env["EXP_TRANSPORT_MODE"], "nosip")
        self.assertEqual(env["EXP_DELETE_ON_NON_SUCCESS"], "false")
        self.assertEqual(env["ENABLE_ATTACK_PLANE"], "true")
        self.assertEqual(env["ENABLE_ATTACK_SCHEDULER"], "true")
        self.assertEqual(env["ENABLE_AIOTTALK_RTP"], "0")
        self.assertEqual(env["ENABLE_NOSIP_RTP"], "1")

    def test_result_requires_actual_onset_and_retained_kpi(self):
        plan = self.build_plan()
        task = pilot.selected_tasks(plan, "smoke", [])[0]
        with tempfile.TemporaryDirectory() as temp:
            task_dir = Path(temp)
            row = {
                "run_id": "run_001",
                "world_name": task["map"],
                "transport_mode": task["transport"],
                "attack_source": task["attack"]["source"],
                "attack_mode": task["attack"]["mode"],
                "attack_severity": task["severity"],
                "attack_seed": str(task["seed"]),
                "attack_scheduled_onset_s": "75.0",
                "attack_actual_onset_s": "",
                "duration_s": "180.0",
                "log_retained": "true",
                "outcome": "TIMEOUT_NO_FINISH",
            }
            (task_dir / "kpi_log_run_001.csv").write_text("t\n0\n", encoding="utf-8")
            result = pilot.result_from_row(task, task_dir, row, 0)
            self.assertFalse(result["attributable"])
            self.assertEqual(result["attribution_reason"], "attack_never_fired")

            row["attack_actual_onset_s"] = "75.1"
            result = pilot.result_from_row(task, task_dir, row, 0)
            self.assertTrue(result["attributable"])
            self.assertEqual(result["attribution_reason"], "keep")

    def test_recovery_ignores_aborted_then_uses_terminal_row(self):
        plan = self.build_plan()
        task = pilot.selected_tasks(plan, "smoke", [])[0]
        fields = [
            "run_id",
            "world_name",
            "transport_mode",
            "attack_source",
            "attack_mode",
            "attack_severity",
            "attack_seed",
            "attack_scheduled_onset_s",
            "attack_actual_onset_s",
            "duration_s",
            "log_retained",
            "outcome",
        ]
        with tempfile.TemporaryDirectory() as temp:
            task_dir = Path(temp)
            base = {
                "world_name": task["map"],
                "transport_mode": task["transport"],
                "attack_source": task["attack"]["source"],
                "attack_mode": task["attack"]["mode"],
                "attack_severity": task["severity"],
                "attack_seed": str(task["seed"]),
                "attack_scheduled_onset_s": "70",
                "attack_actual_onset_s": "70.1",
                "duration_s": "100",
                "log_retained": "true",
            }
            rows = [
                dict(base, run_id="run_001", outcome="TIMEOUT_NO_FINISH"),
                dict(base, run_id="run_002", outcome="ABORTED"),
            ]
            with (task_dir / "run_manifest.csv").open(
                "w", newline="", encoding="utf-8"
            ) as target:
                writer = csv.DictWriter(target, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            (task_dir / "kpi_log_run_001.csv").write_text("t\n0\n", encoding="utf-8")
            result = pilot.recover_task(task, task_dir)
            self.assertIsNotNone(result)
            self.assertEqual(result["run_id"], "run_001")
            self.assertEqual(result["state"], "completed")

    def test_consolidated_manifest_preserves_campaign_labels(self):
        plan = self.build_plan()
        task = plan["tasks"][0]
        with tempfile.TemporaryDirectory() as temp:
            campaign_dir = Path(temp)
            result_dir = campaign_dir / "runs" / task["task_id"]
            result_dir.mkdir(parents=True)
            result = {
                key: ""
                for key in pilot.PILOT_MANIFEST_FIELDS
            }
            result.update(
                {
                    "task_id": task["task_id"],
                    "map": task["map"],
                    "profile": task["profile"],
                    "source": task["attack"]["source"],
                    "mode": task["attack"]["mode"],
                    "severity": task["severity"],
                    "seed": task["seed"],
                    "transport": task["transport"],
                    "state": "completed",
                    "outcome": "TIMEOUT_NO_FINISH",
                    "attributable": True,
                }
            )
            (result_dir / "attempt_result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            status = pilot.consolidate_results(campaign_dir, plan)
            with (campaign_dir / "pilot_manifest.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(status["completed_attempts"], 1)
            self.assertEqual(status["attributable_attempts"], 1)
            self.assertEqual(rows[0]["map"], task["map"])
            self.assertEqual(rows[0]["profile"], task["profile"])
            self.assertEqual(rows[0]["seed"], str(task["seed"]))


if __name__ == "__main__":
    unittest.main()
