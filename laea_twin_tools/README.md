# laea_twin_tools

Utilities for LAEA experiment orchestration, KPI logging, and dataset processing.

## What is included

- `scripts/experiment_manager.py`
  - Runs batch missions.
  - Starts/stops the KPI logger for each run.
  - Keeps logs only when mission succeeds (`finish exploration.` token).
- `scripts/slam_kpi_logger.py`
  - Records GT/EST pose error, local velocity, GPS fix/velocity/satellites.
  - Writes `kpi_log_<run_id>.csv`.
- `scripts/summarize_missions.py`
  - Aggregates `kpi_log_*.csv` into `missions_summary.csv`.
- `scripts/label_missions.py`
  - Labels mission success from summary thresholds.
- Eclipse Ditto bridge has been moved to `laea_ditto_bridge/`.

## Prerequisites

1. ROS workspace is built:

```bash
cd /home/tim/laea
catkin_make
source devel/setup.bash
```

2. If you use Eclipse Ditto, see `../laea_ditto_bridge/README.md`.

## Troubleshooting

- KPI logger output missing:
  - Check `/mavros/local_position/pose` and `/mavros/global_position/raw/fix`.
- Mission summary looks wrong:
  - Confirm `kpi_log_*.csv` filenames and `laea_logs` path.
