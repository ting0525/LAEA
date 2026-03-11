# laea_twin_tools

Utilities for LAEA experiment orchestration, KPI logging, dataset processing, and Eclipse Ditto sync.

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
- `scripts/ditto_bridge.py`
  - Pushes live UAV sensor states to Eclipse Ditto via HTTP API.

## Ditto bridge data model

Default Thing:

- `thingId`: `laea:iris_0`

Default features and properties:

- `pose_local`
  - `t`
  - `pos_x`, `pos_y`, `pos_z`
  - `vel_x`, `vel_y`, `vel_z`
  - `yaw`
- `gps`
  - `t`
  - `gps_lat`, `gps_lon`, `gps_alt`
  - `gps_vx`, `gps_vy`, `gps_vz`
  - `gps_fix`, `gps_sat`
- `slam`
  - `t`
  - `px_gt`, `py_gt`, `pz_gt`
  - `px_est`, `py_est`, `pz_est`
  - `e_pos`

## Prerequisites

1. ROS workspace is built:

```bash
cd /home/tim/laea
catkin_make
source devel/setup.bash
```

2. Ditto is running (official docker deployment):

```bash
# in your Ditto clone
cd deployment/docker
docker-compose up -d
```

3. Verify Ditto API is reachable:

```bash
curl -u ditto:ditto http://localhost:8080/api/2/things?size=1
```

## Run Ditto bridge

Start your UAV simulation stack first (PX4 + MAVROS + topics), then start bridge:

```bash
source /home/tim/laea/devel/setup.bash
roslaunch laea_twin_tools ditto_bridge.launch
```

Custom example:

```bash
roslaunch laea_twin_tools ditto_bridge.launch \
  thing_id:=laea:iris_0 \
  publish_rate_hz:=2.0 \
  base_url:=http://localhost:8080/api/2 \
  username:=ditto \
  password:=ditto
```

## Verify synced twin data

Fetch whole Thing:

```bash
curl -u ditto:ditto \
  http://localhost:8080/api/2/things/laea%3Airis_0
```

Fetch only one feature:

```bash
curl -u ditto:ditto \
  http://localhost:8080/api/2/things/laea%3Airis_0/features/slam
```

## Full workflow example

Terminal 1: run mission stack

```bash
cd /home/tim/laea/src/LAEA
./run_nosip_depth.sh
```

Terminal 2: run Ditto bridge

```bash
source /home/tim/laea/devel/setup.bash
roslaunch laea_twin_tools ditto_bridge.launch
```

Terminal 3: observe Ditto state

```bash
watch -n 1 "curl -s -u ditto:ditto http://localhost:8080/api/2/things/laea%3Airis_0/features/slam"
```

## Troubleshooting

- `waiting for local pose topic`:
  - Check `/mavros/local_position/pose` exists.
- Thing creation fails:
  - Check Ditto credentials.
  - If your setup enforces custom policy, pass `policy_id:=<namespace:policyId>`.
- Ditto unreachable:
  - Check `base_url` and reverse proxy port (`8080` by default in local docker setup).
