# dt_ids tools

Utilities for generating normal-flight datasets, run manifests, train/val/test splits, and GPS anomaly-detection features.

## Recommended preparation flow

### 1) Build a run manifest and quality flags

```bash
python3 tools/dt_ids/build_run_manifest.py \
  --input "/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip/kpi_log_run_*.csv" \
  --out data/run_manifest.csv
```

This creates one row per run with:
- `duration_s`, `num_rows`
- `gps_nan_ratio`, `gps_valid_ratio`
- `e_pos_mean`, `e_pos_p95`, `e_pos_max`
- `quality_ok`

### 2) Collect baseline normal-flight rows

```bash
python3 tools/dt_ids/collect_normal_dataset.py \
  --log-dir /home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip \
  --out data/normal_gps_baseline.csv \
  --feature-set gps_baseline \
  --max-e-pos 2.0 \
  --include-mission-id
```

## 1) Collect normal rows from `kpi_log_*.csv`

```bash
python3 tools/dt_ids/collect_normal_dataset.py \
  --log-dir /home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip \
  --out data/normal_gps_baseline.csv \
  --feature-set gps_baseline \
  --max-e-pos 2.0 \
  --include-mission-id
```

## 2) Build derived GPS features

```bash
python3 tools/dt_ids/build_gps_features.py \
  --input "/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip/kpi_log_run_*.csv" \
  --out data/normal_gps_features.csv \
  --drop-na
```

`build_gps_features.py` adds:
- `local_speed`, `gps_speed`, `speed_gap`, `vertical_speed_gap`
- `gps_heading`, `heading_gap`
- `local_step_m`, `gps_step_m`, `step_gap`
- `sat_change`, `sat_drop`, `fix_bad`, `dt`

## 3) Split datasets by run

Use `mission_id` to avoid leaking rows from the same run into both train and test.

```bash
python3 tools/dt_ids/split_dataset_by_run.py \
  --input data/normal_gps_baseline.csv \
  --manifest data/run_manifest.csv \
  --out-dir data/splits \
  --prefix normal_gps_baseline
```

This writes:
- `data/splits/normal_gps_baseline_train.csv`
- `data/splits/normal_gps_baseline_val.csv`
- `data/splits/normal_gps_baseline_test.csv`
- `data/splits/normal_gps_baseline_splits.csv`

## 4) Train a normal-only Isolation Forest

Train on the `gps_derived` split files and keep `t`, `mission_id`, `split`, and `label` out of model inputs.

```bash
python3 tools/dt_ids/train_isolation_forest.py \
  --train data/splits/normal_gps_features_train.csv \
  --val data/splits/normal_gps_features_val.csv \
  --test data/splits/normal_gps_features_test.csv \
  --out-dir data/models/iforest_gps_v1
```

Outputs:
- `isolation_forest.joblib`
- `feature_columns.json`
- `training_config.json`
- `score_summary.csv`

Add `--write-scored-csv` if you want per-row anomaly scores for inspection.

## Feature Reference

### Derived Features (`gps_derived`)

| Feature | Formula | Unit | Purpose | Notes |
|---|---|---|---|---|
| `local_speed` | `sqrt(vel_x^2 + vel_y^2 + vel_z^2)` | m/s | Local velocity magnitude | From local estimator |
| `gps_speed` | `sqrt(gps_vx^2 + gps_vy^2 + gps_vz^2)` | m/s | GNSS velocity magnitude | Compared with `local_speed` |
| `speed_gap` | `abs(local_speed - gps_speed)` | m/s | Velocity consistency check | Larger under spoof/drift |
| `vertical_speed_gap` | `abs(vel_z - gps_vz)` | m/s | Vertical consistency check | Sensitive to altitude anomalies |
| `heading_gap` | `abs(wrap_to_pi(gps_heading - yaw))` | rad | Heading consistency check | `gps_heading = atan2(gps_vy, gps_vx)` |
| `local_step_m` | `sqrt(diff(pos_x)^2 + diff(pos_y)^2 + diff(pos_z)^2)` | m | Per-step local displacement | Compared with `gps_step_m` |
| `gps_step_m` | Step distance from `gps_lat/lon/alt` | m | Per-step GNSS displacement | Equirectangular approximation |
| `step_gap` | `abs(gps_step_m - local_step_m)` | m | Step-wise position consistency | Detects slow drift/jumps |
| `sat_change` | `diff(gps_sat)` | count | Satellite count trend | Negative = dropping satellites |
| `sat_drop` | `max(-sat_change, 0)` | count | Satellite drop event magnitude | Keeps only drop side |
| `fix_bad` | `1 if gps_fix < gps_fix_threshold else 0` | 0/1 | GNSS quality flag | Default threshold is `2` |
| `dt` | `diff(t)` | s | Sampling interval quality | Detects timing irregularities |

### `gps_baseline` vs `gps_derived`

| Category | `gps_baseline` | `gps_derived` | Description |
|---|---|---|---|
| GPS position | `gps_lat`, `gps_lon`, `gps_alt` | Same | Raw GNSS coordinates |
| GPS velocity | `gps_vx`, `gps_vy`, `gps_vz` | Same | Raw GNSS velocities |
| GPS quality | `gps_fix`, `gps_sat` | Same | GNSS quality indicators |
| Local position | `pos_x`, `pos_y`, `pos_z` | Same | Local estimator position |
| Local velocity | `vel_x`, `vel_y`, `vel_z` | Same | Local estimator velocity |
| Attitude | `yaw` | Same | Yaw angle |
| Velocity consistency | - | `local_speed`, `gps_speed`, `speed_gap`, `vertical_speed_gap` | Compare local vs GNSS speed |
| Heading consistency | - | `heading_gap` | Compare GNSS heading vs yaw |
| Step consistency | - | `local_step_m`, `gps_step_m`, `step_gap` | Compare per-step movement |
| Signal degradation | - | `sat_change`, `sat_drop`, `fix_bad` | Detect GNSS quality deterioration |
| Timing stability | - | `dt` | Detect irregular sampling interval |
| Typical use | Baseline dataset collection | Anomaly detection training/inference | `gps_derived = gps_baseline + derived checks` |

## Notes

- Logs are now configured to write to `/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/nosip`.
- `label` is appended as `0` by default (normal samples).
- `collect_normal_dataset.py` can append `mission_id`; use this for by-run splitting.
