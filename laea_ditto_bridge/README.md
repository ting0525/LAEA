# laea_ditto_bridge

Dedicated ROS package for uploading LAEA UAV states to Eclipse Ditto.

## L1 features

This package currently uploads L1 raw telemetry features:

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
- `imu`
  - `t`
  - `qx`, `qy`, `qz`, `qw`
  - `ang_vel_x`, `ang_vel_y`, `ang_vel_z`
  - `lin_acc_x`, `lin_acc_y`, `lin_acc_z`
- `nav_aux`
  - `t`
  - `state_connected`, `state_armed`, `state_guided`, `state_mode`, `state_system_status`
  - `vtol_state`, `landed_state`
  - `mag_x`, `mag_y`, `mag_z`
  - `static_pressure`, `static_pressure_variance`

Optional feature:

- `slam`
  - `t`
  - `px_gt`, `py_gt`, `pz_gt`
  - `px_est`, `py_est`, `pz_est`
  - `e_pos`

## Run

```bash
source /home/tim/laea/devel/setup.bash
roslaunch laea_ditto_bridge ditto_bridge.launch
```

Enable optional SLAM upload:

```bash
roslaunch laea_ditto_bridge ditto_bridge.launch enable_slam:=true
```
