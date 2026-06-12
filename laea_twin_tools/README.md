# laea_twin_tools

Utilities for LAEA experiment orchestration, KPI logging, and dataset processing.

## What is included

- `scripts/experiment_manager.py`
  - Runs batch missions.
  - Starts/stops the KPI logger for each run.
  - Keeps logs only when mission succeeds (`finish exploration.` token).
- `scripts/slam_kpi_logger.py`
  - Records EKF output, GPS, IMU, magnetometer, barometer, RTP-depth quality features, and evaluation-only GT/error.
  - Writes `kpi_log_<run_id>.csv`.
- `scripts/summarize_missions.py`
  - Aggregates `kpi_log_*.csv` into `missions_summary.csv`.
- `scripts/label_missions.py`
  - Labels mission success from summary thresholds.
- Eclipse Ditto bridge has been moved to `laea_ditto_bridge/`.

## Logged training data

Each CSV row is one sampling time from the current mission:

| Group | Columns | Source |
|---|---|---|
| Metadata | `run_id`, `scenario`, `transport_mode`, `world_name`, `t` | `experiment_manager.py` and ROS simulated time |
| EKF output | `pos_*`, `vel_*`, `roll`, `pitch`, `yaw`, `odom_*_covariance_summary` | MAVROS local pose/velocity/odom |
| GPS | `gps_*`, `gps_fix`, `gps_sat`, `gps_position_covariance` | MAVROS raw GPS topics |
| IMU | `imu_q*`, `ang_vel_*`, `lin_acc_*` | `/mavros/imu/data` |
| Barometer / magnetometer | `mag_*`, `static_pressure`, `static_pressure_variance` | MAVROS IMU auxiliary topics |
| RTP depth | `depth_dt`, `depth_age_ms`, image statistics, stale/repeat features | `/rtp/depth/image_raw` |
| Evaluation only | `px_gt`, `py_gt`, `pz_gt`, `e_pos`, `mission_outcome` | Gazebo GT and manager result |

`odom_pose_covariance_summary`, `odom_twist_covariance_summary`, and `gps_position_covariance` are matrix traces: the sum of their diagonal variance values. `depth_near_ratio_1m` is the proportion of valid depth pixels at or below one meter.

`depth_age_ms` uses the image header timestamp when the RTP receiver preserves one. When decoded RTP output has a zero/new receiver-side header, it represents time since the last received frame rather than end-to-end network latency.

`mission_outcome` remains `RUNNING` while a flight is being collected. When the run ends, `experiment_manager.py` rewrites the file with `SUCCESS_FINISH`, `FAIL_SLAM`, `TIMEOUT_NO_FINISH`, or `ABORTED` for all rows.

Normal AIoTtalk RTP collection:

```bash
LAEA_LOG_DIR="$PWD/laea_twin_tools/laea_logs/aiottalk_normal_v2" \
EXP_SCENARIO=normal EXP_TRANSPORT_MODE=aiottalk_rtp EXP_WORLD_NAME=indoor_01 \
TOTAL_ROUNDS=10 ENABLE_RVIZ=0 \
  ./run_aiottalk_batches_restart.sh
```

Use `run_aiottalk_rtp.sh` for one mission only. The exploration node stays in
`FINISH` after a completed mission, so repeating `EXP_NUM_RUNS` in the same
ROS/PX4/Gazebo process does not produce independent training runs.

GPS source-attack visual inspection:

```bash
GPS_ATTACK_MODE=bias GPS_ATTACK_START_SEC=20 ENABLE_RVIZ=1 \
  ./run_gps_attack_slam.sh
```

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
