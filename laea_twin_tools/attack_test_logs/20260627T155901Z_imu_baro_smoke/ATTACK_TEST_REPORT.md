# LAEA source-layer attack smoke test

Test time: 2026-06-27 15:59 UTC  
Repo HEAD: `2f89cba`  
Scope: GPS / IMU / barometer source-layer attack pipeline smoke test. This is not a full SLAM mission success-rate test.

## Result

Overall attack functionality: PASS

Evidence:

- GPS bias attack changed `/mavros/global_position/raw/fix` by about `30.12 m` east.
- IMU gyro-bias attack changed `/mavros/imu/data.angular_velocity.z` by about `+0.606 rad/s`.
- Barometer drift attack changed `/mavros/imu/static_pressure` by about `-34.46 Pa`, consistent with a 3 m altitude-equivalent pressure offset.
- `attack_gazebo_bridge` started and relayed `/laea/attack/command_json` to Gazebo transport.
- No PX4 / Gazebo / MAVROS / attack bridge process remained after cleanup.

Issue observed:

- `roslaunch` logs showed `Segmentation fault (core dumped)` during shutdown in both runtime runs. The attack measurements completed successfully before shutdown, so this does not block the attack-functionality result, but it should be tracked separately as a Gazebo/PX4 shutdown-cleanup issue.
- Gazebo plugin `gzmsg` active lines were not visible in the `roslaunch` stdout log. Functional sensor deltas were therefore used as the primary evidence.

## Static checks

Recorded in `static_checks.log`.

Confirmed:

- `attack_profiles.yaml` contains 8 profiles:
  - `gps_bias_low`
  - `gps_bias_high`
  - `gps_velocity_bias_low`
  - `gps_velocity_bias_high`
  - `imu_gyro_bias_low`
  - `imu_gyro_bias_high`
  - `barometer_drift_low`
  - `barometer_drift_high`
- Dashboard live attack whitelist contains `gps`, `imu`, and `barometer`.
- Attack-capable model is `iris_d435_lidar_gps_attack`.
- Repo plugin sources and installed PX4 SITL sources have matching hashes:
  - IMU attack plugin matched.
  - Barometer attack plugin matched.
  - Shared `attack_window.h` matched.
  - Shared `attack_command_json.h` matched.
- PX4 Gazebo `.so` files exist:
  - `libgazebo_gps_attack_plugin.so`
  - `libgazebo_imu_attack_plugin.so`
  - `libgazebo_barometer_attack_plugin.so`
- `iris_gps_attack.sdf` uses:
  - `libgazebo_imu_attack_plugin.so`
  - `libgazebo_barometer_attack_plugin.so`
- Bash/Python syntax checks passed.
- `git diff --check` passed.

## Build checks

Recorded in:

- `px4_attack_plugin_build.log`
- `catkin_make_px4_gazebo_laea_twin_tools.log`
- `catkin_make_summary.log`

Result:

- PX4 Gazebo attack plugin targets rebuilt or confirmed up-to-date.
- `catkin_make --pkg px4_gazebo laea_twin_tools` returned `0`.

## Runtime smoke test

Recorded in:

- `effect_px4_gazebo.log`
- `effect_attack_bridge.log`
- `effect_measurements_stdout.log`
- `effect_measurements.json`
- `effect_summary.log`

Runtime setup:

- Started headless PX4/Gazebo with `LAEA_PX4_SDF=iris_d435_lidar_gps_attack`.
- Started `attack_gazebo_bridge`.
- Published direct commands to `/laea/attack/command_json`.
- Measured sensor output from MAVROS topics before and during each attack.

Measured values:

| Attack | Baseline | During attack | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| IMU `gyro_bias_high`, z axis | `-0.000098 rad/s` | `0.606337 rad/s` | `+0.606435 rad/s` | PASS |
| Barometer `drift_high` | `95606.071 Pa` | `95571.613 Pa` | `-34.459 Pa` | PASS |
| GPS `bias_high`, east | baseline fix | shifted fix | `+30.121 m east` | PASS |

Notes:

- IMU requested vector was `[0.0, 0.0, 0.8] rad/s`; observed MAVROS delta was `+0.606 rad/s`. This confirms the injected signal propagates to MAVROS, though PX4/MAVROS processing attenuates or filters the exact raw magnitude.
- Barometer requested scalar was `3.0 m`; expected pressure shift near `-rho*g*3 ~= -36 Pa`. Observed `-34.46 Pa`, consistent with the implemented model.
- GPS requested vector was `[30.0, 0.0, 0.0] m`; observed `+30.12 m` east, consistent with the requested attack.

## Follow-up

Recommended fixes or follow-up checks:

1. Update Dashboard capability text for `IMU / Barometer attack`; it still says the Gazebo injectors are pending even though they are now present.
2. Investigate Gazebo/PX4 shutdown `Segmentation fault (core dumped)` separately. It appears during teardown, not during measurement.
3. Run one full SLAM mission per attack profile after this smoke test if the next goal is mission-level impact rather than sensor-level injection verification.
