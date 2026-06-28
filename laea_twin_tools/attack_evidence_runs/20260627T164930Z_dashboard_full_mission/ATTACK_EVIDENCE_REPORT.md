# LAEA Dashboard Attack Evidence Report

- Created: `2026-06-27T17:05:46.944083+00:00`
- Evidence root: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission`
- Runtime: `scan_mapping_explore_test`, world `indoor_01`, RViz off, Gazebo GUI off, Ditto off, RTP on, supervisor policy `none`.
- Non-success policy: CSV deleted on non-success; manifest/debug JSON retained for evidence.

## Dashboard fixes completed

- Removed the stale capability/status block that still described IMU/Barometer attacks as `profile_only` / pending.
- Profile catalog now reports the actual connected source injector: GPS, IMU, or barometer.
- Attack evidence panel is source-agnostic: GPS uses `gps_pos_res`, IMU uses `yaw_rate_res`, barometer uses `baro_res`; units are shown correctly.
- Attack evidence state is reset when a disabled/clear command is received, so the previous run does not leak into the next run display.
- Normal-run manual trigger error now says stock sensor model, not stock GPS-only model.

## Full-mission attack runs

| Profile | Attack | Outcome | Duration | Onset | CSV | Evidence metric | Max observed | Impact | Main diagnosis |
|---|---|---:|---:|---:|---:|---|---:|---:|---|
| `gps_bias_high` | 30 m east GPS position bias | `FAIL_SLAM` | `173.953000` s | `158.407` s | `deleted` | `gps_pos_res` | 30.139 m | `True` | localization_error_exceeded: e_pos 27.607m > threshold 10.000m; localization_error_hold: held 1.814s / required 1.000s |
| `imu_gyro_bias_high` | 0.8 rad/s IMU gyro Z bias | `FAIL_SLAM` | `168.852000` s | `158.37` s | `deleted` | `yaw_rate_res` | 0.914 rad/s | `True` | localization_error_exceeded: e_pos 37.992m > threshold 10.000m; localization_error_hold: held 1.805s / required 1.000s |
| `barometer_drift_high` | 3.0 m barometer altitude-equivalent drift | `FAIL_PREMATURE_FINISH` | `237.752000` s | `158.448` s | `deleted` | `baro_res` | 0.810 m | `True` | no_single_clear_cause_in_summary |

## Evidence artifacts

### gps_bias_high

- Manifest: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_run_manifest.csv`
- Debug: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_run_001_FAIL_SLAM.json`
- Samples: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_samples.jsonl`
- Trend plot: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_trend.png`
- Dashboard screenshot active: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_active.png`
- Dashboard screenshot final: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_final.png`
- Log excerpt: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/gps_bias_high_attack_log_excerpt.txt`

### imu_gyro_bias_high

- Manifest: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_run_manifest.csv`
- Debug: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_run_001_FAIL_SLAM.json`
- Samples: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_samples.jsonl`
- Trend plot: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_trend.png`
- Dashboard screenshot active: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_active.png`
- Dashboard screenshot impact: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_impact.png`
- Dashboard screenshot final: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_final.png`
- Log excerpt: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/imu_gyro_bias_high_attack_log_excerpt.txt`

### barometer_drift_high

- Manifest: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_run_manifest.csv`
- Debug: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_run_001_FAIL_PREMATURE_FINISH.json`
- Samples: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_samples.jsonl`
- Trend plot: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_trend.png`
- Dashboard screenshot active: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_active.png`
- Dashboard screenshot impact_verified: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_impact_verified.png`
- Dashboard screenshot final: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_final.png`
- Log excerpt: `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/barometer_drift_high_attack_log_excerpt.txt`

## Interpretation

- GPS and IMU high attacks both produced `FAIL_SLAM`, with localization error exceeding the 10 m failure threshold in debug summaries.
- Barometer high attack produced source-layer barometer residual evidence and ended as `FAIL_PREMATURE_FINISH`; this proves the barometer attack path is active, but the outcome classification should be reviewed if the expected effect is a direct altitude/SLAM failure.
- After all tests, no Gazebo/PX4/MAVROS/RViz/experiment residual nodes remained; only roscore, rosout, and dashboard were still running.

## Post-run process check

- `/home/tim/laea/src/LAEA/laea_twin_tools/attack_evidence_runs/20260627T164930Z_dashboard_full_mission/post_all_process_check.txt`
