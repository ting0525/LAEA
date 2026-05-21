# GPS Source Attack for PX4 EKF2

This folder contains a LAEA-owned GPS source-attack plugin for PX4 SITL Gazebo.
It does not modify PX4's stock `gazebo_gps_plugin.cpp`; instead, it installs a
separate `libgazebo_gps_attack_plugin.so` and attack-only models.

## Install into PX4

```bash
cd ~/laea/src/LAEA
./px4_gazebo/gps_attack/install_gps_attack_px4.sh
cd ~/PX4-Autopilot
DONT_RUN=1 make px4_sitl gazebo
```

The installer writes:

- `Tools/sitl_gazebo/src/gazebo_gps_attack_plugin.cpp`
- `Tools/sitl_gazebo/models/gps_attack`
- `Tools/sitl_gazebo/models/iris_gps_attack`
- `Tools/sitl_gazebo/models/iris_d435_lidar_gps_attack`

It also adds `gazebo_gps_attack_plugin` to `Tools/sitl_gazebo/CMakeLists.txt`.

## Run

Baseline model:

```bash
LAEA_PX4_SDF=iris_d435_lidar ./run_aiottalk_rtp.sh
```

GPS bias attack:

```bash
GPS_ATTACK_MODE=bias \
GPS_ATTACK_START_SEC=30 \
GPS_ATTACK_EAST_BIAS_M=5 \
LAEA_PX4_SDF=iris_d435_lidar_gps_attack \
./run_aiottalk_rtp.sh
```

## Modes

| Mode | Effect |
|---|---|
| `none` | Publish stock GPS behavior. |
| `bias` | Ramp GPS position bias over `GPS_ATTACK_RAMP_SEC`. |
| `jump` | Apply an immediate GPS position jump. |
| `freeze` | Replay the first active GPS sample until the attack ends. |
| `noise` | Add runtime random position and velocity noise. |
| `velocity_bias` | Bias GPS velocity only. |

Environment variables override SDF defaults:

```bash
GPS_ATTACK_MODE=bias
GPS_ATTACK_START_SEC=30
GPS_ATTACK_END_SEC=90
GPS_ATTACK_RAMP_SEC=10
GPS_ATTACK_EAST_BIAS_M=5
GPS_ATTACK_NORTH_BIAS_M=0
GPS_ATTACK_UP_BIAS_M=0
GPS_ATTACK_JUMP_EAST_M=5
GPS_ATTACK_NOISE_POSITION_STD_M=2
GPS_ATTACK_VELOCITY_EAST_BIAS_MPS=1
```

This is a source-layer attack: the modified GPS message is delivered to PX4
before EKF2 produces `/mavros/local_position/odom` and `/mavros/local_position/pose`.
