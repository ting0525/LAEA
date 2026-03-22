# laea_ditto_bridge

Dedicated ROS package for uploading LAEA UAV states to Eclipse Ditto.

## Included

- `scripts/ditto_bridge.py`
  - Subscribes to local pose, velocity, GPS, and Gazebo GT topics.
  - Publishes `pose_local`, `gps`, and `slam` features to a Ditto Thing via HTTP API.
- `launch/ditto_bridge.launch`
  - Launch wrapper for configuring Ditto connection, Thing ID, and ROS topics.

## Default Ditto data model

- `thingId`: `laea:iris_0`
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

2. Ditto is running and reachable:

```bash
curl -u ditto:ditto http://localhost:8080/api/2/things?size=1
```

## Run

```bash
source /home/tim/laea/devel/setup.bash
roslaunch laea_ditto_bridge ditto_bridge.launch
```

Custom example:

```bash
roslaunch laea_ditto_bridge ditto_bridge.launch   thing_id:=laea:iris_0   publish_rate_hz:=2.0   base_url:=http://localhost:8080/api/2   username:=ditto   password:=ditto
```
