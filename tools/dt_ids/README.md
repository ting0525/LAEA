# dt_ids tools

Utilities for generating normal-flight datasets and GPS anomaly-detection features.

## 1) Collect normal rows from `kpi_log_*.csv`

```bash
python3 tools/dt_ids/collect_normal_dataset.py \
  --log-dir /home/tim/laea/src/LAEA/laea_twin_tools/laea_logs \
  --out data/normal_gps_baseline.csv \
  --feature-set gps_baseline \
  --max-e-pos 2.0
```

## 2) Build derived GPS features

```bash
python3 tools/dt_ids/build_gps_features.py \
  --input "/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/kpi_log_*.csv" \
  --out data/normal_gps_features.csv \
  --drop-na
```

`build_gps_features.py` adds:
- `local_speed`, `gps_speed`, `speed_gap`, `vertical_speed_gap`
- `gps_heading`, `heading_gap`
- `local_step_m`, `gps_step_m`, `step_gap`
- `sat_change`, `sat_drop`, `fix_bad`, `dt`

## Notes

- Logs are now configured to write to `/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs`.
- `label` is appended as `0` by default (normal samples).
