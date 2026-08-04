# Four-map attack pilot v1

This pilot validates four existing, source-layer sensitivity profiles without
changing their definitions:

| Attack type | Existing profile | Magnitude |
|---|---|---|
| GPS position bias | `gps_bias_5m` | 5 m east |
| GPS velocity bias | `gps_velocity_1p0` | 1.0 m/s |
| IMU gyro bias | `imu_gyro_0p05` | 0.05 rad/s around z |
| Barometer drift | `baro_1p0` | 1.0 m altitude-equivalent |

The full plan is four maps × four profiles × two attempts = 32 attempts.  Seeds
are unique and deterministic.  Every task records map, profile, source, mode,
severity, seed, expected onset window, scheduled/actual onset, transport,
outcome, retained KPI path, and an attribution decision.

## Safe dry-run

Dry-run is the default and does not create a campaign directory or start ROS,
PX4, or Gazebo:

```bash
python3 tools/dt_ids/attack_pilot_campaign.py --selection smoke
python3 tools/dt_ids/attack_pilot_campaign.py --selection full
```

## Recommended first smoke

Run only one profile at first, review its actual onset and KPI evidence, and
then run the other three smoke tasks.  GPS position bias is the simplest first
end-to-end check:

```bash
python3 tools/dt_ids/attack_pilot_campaign.py \
  --selection smoke \
  --task-id indoor_01__gps_bias_5m__a01
```

After reviewing that dry-run, execution requires a persistent campaign id:

```bash
python3 tools/dt_ids/attack_pilot_campaign.py \
  --execute \
  --campaign-id attack_four_maps_pilot_v1_YYYYMMDD \
  --selection smoke \
  --task-id indoor_01__gps_bias_5m__a01
```

The same command is resumable.  A terminal run already represented by
`attempt_result.json` is not rerun.  An interrupted/ABORTED attempt is retryable.
The full campaign has an additional guard:

```bash
python3 tools/dt_ids/attack_pilot_campaign.py \
  --execute \
  --campaign-id attack_four_maps_pilot_v1_YYYYMMDD \
  --selection full \
  --allow-full-campaign
```

Do not start the full campaign until all four smoke tasks have a retained KPI
CSV and `attributable=true`.

## Outputs

```text
laea_twin_tools/laea_logs/attack_pilots/<campaign-id>/
├── campaign_plan.json       # immutable catalogs, hashes and all 32 tasks
├── campaign_status.json     # completed/remaining/attributable counts
├── pilot_manifest.csv       # campaign-level labels and observed outcome/onset
├── runs/
│   └── <map>__<profile>__aNN/
│       ├── task_spec.json
│       ├── run_manifest.csv
│       ├── kpi_log_run_NNN.csv
│       ├── attempt_result.json
│       └── driver_invocation_NNN.log
└── system_logs/
```

`EXP_DELETE_ON_NON_SUCCESS=false` is mandatory for this campaign.  A run is
attributable only when the actual attack onset is observed, the mission survives
to that onset, and the retained KPI CSV exists.

## Validate observed injection effects

After retained attempts finish, independently verify their source-layer effects:

```bash
python3 tools/dt_ids/validate_attack_pilot_effects.py \
  --campaign-dir laea_twin_tools/laea_logs/attack_pilots/<campaign-id> \
  --out /tmp/<campaign-id>-effects.json \
  --markdown-out /tmp/<campaign-id>-effects.md
```

The validator processes only `completed + retained + attributable` attempts,
then independently checks task/manifest/KPI identity, time-base alignment,
actual onset, phase length, required columns, effect magnitude, and Cliff's
delta. Exit code `2` means invalid evidence; `3` means structurally valid
evidence whose injection effect was not verified.

This validator is evaluation-only. It may use simulator ground-truth columns
such as `px_gt`, `py_gt`, and `pz_gt`; these columns must never be used as
detector or model inputs.

## Frozen evaluation roles

For campaign `attack_four_maps_pilot_v1_20260729`, the analysis roles were
first registered in `reports/evaluation_protocol_v1.json` before cross-map
results were inspected:

- `indoor_01` attempt 1: calibration and feature-development evidence only.
- `indoor_01` attempt 2: alarm-policy validation only.
- both attempts from `indoor_02`, `lab_corridor_01`, and `lab_rooms_01`:
  the 24-run frozen-policy attack test.

The policy-development seed is 42. Candidate consecutive-window counts are
`3, 5, 7, 9, 11, 13, 15` at stride 10. Selection uses normal `val` plus the
four policy-validation attacks, then chooses the smallest candidate satisfying
all registered false-alarm, detection-rate, and latency constraints. The
selected count is frozen unchanged for seeds 42, 43, and 44 before the 24
cross-map attack-test tasks are evaluated.

Before the formal validation sweep, `reports/evaluation_protocol_v2.json`
anchored the SHA-256 of v1 and added the machine-readable selection method
`min_k_satisfying_all_gates_v1`. This technical amendment does not change any
role, task, candidate, threshold, or constraint.

The original `k=3..15` sweep subsequently failed closed because every
candidate exceeded the registered normal per-run false-alarm limit. The
failure and the explicitly adaptive validation reuse are recorded in
`reports/alarm_policy_adaptive_stage2_record_v1.json`.
`reports/evaluation_protocol_v3.json` changes only the Stage 2 candidates to
`k=17,19,21`; all roles, inputs, constraints, and the smallest-passing-k rule
remain unchanged. The `k=17,19,21` exploratory results were already observed
before v3 was registered. This is therefore post-hoc adaptive validation
tuning, not a prospective or confirmatory pre-registration claim.

`reports/evaluation_protocol_v4.json` leaves all v3 experiment semantics
unchanged and hardens only the evidence and disclosure layer. It binds
`reports/alarm_policy_adaptive_stage2_record_v2.json` plus portable byte
snapshots of all seven Stage 1 and three exploratory Stage 2 evaluations. The
evaluator verifies every file SHA-256, recomputes the decision metrics from
per-run/per-task evidence, and labels any resulting selection
`adaptive_post_hoc`. The untouched cross-map `attack_test` role remains the
confirmatory attack evaluation and cannot be opened without a frozen selection
artifact whose SHA-256, k, stride, deploy, strategy, and threshold all match.

Earlier exploratory sweeps exposed the current normal `test` split. Those
numbers are preliminary, not an unbiased final claim. Final thesis reporting
therefore requires a newly collected and locked supplemental normal holdout.
