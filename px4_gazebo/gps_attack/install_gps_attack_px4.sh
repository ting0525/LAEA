#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PX4_ROOT="${PX4_ROOT:-/home/tim/PX4-Autopilot}"
SITL_DIR="${PX4_ROOT}/Tools/sitl_gazebo"

if [[ ! -d "${SITL_DIR}" ]]; then
  echo "PX4 sitl_gazebo not found: ${SITL_DIR}" >&2
  echo "Set PX4_ROOT=/path/to/PX4-Autopilot and retry." >&2
  exit 1
fi

CMAKE_FILE="${SITL_DIR}/CMakeLists.txt"
PLUGIN_SRC="${SITL_DIR}/src/gazebo_gps_attack_plugin.cpp"

install -m 0644 "${SCRIPT_DIR}/gazebo_gps_attack_plugin.cpp" "${PLUGIN_SRC}"

# IMU and barometer source-attack plugins share the same command plane and
# attack_common headers; they live next to the GPS one in ${SITL_DIR}/src.
install -m 0644 "${SCRIPT_DIR}/../imu_attack/gazebo_imu_attack_plugin.cpp" \
  "${SITL_DIR}/src/gazebo_imu_attack_plugin.cpp"
install -m 0644 "${SCRIPT_DIR}/../baro_attack/gazebo_barometer_attack_plugin.cpp" \
  "${SITL_DIR}/src/gazebo_barometer_attack_plugin.cpp"

# Shared, dependency-free attack headers consumed by the plugins (they compile
# inside ${SITL_DIR}/src so the headers must sit next to them).
ATTACK_COMMON_DIR="${SCRIPT_DIR}/../attack_common"
install -m 0644 "${ATTACK_COMMON_DIR}/attack_window.h" "${SITL_DIR}/src/attack_window.h"
install -m 0644 "${ATTACK_COMMON_DIR}/attack_command_json.h" "${SITL_DIR}/src/attack_command_json.h"

if ! grep -q "add_library(gazebo_gps_attack_plugin" "${CMAKE_FILE}"; then
  cp -n "${CMAKE_FILE}" "${CMAKE_FILE}.laea_gps_attack.bak"
  sed -i "/add_library(gazebo_gps_plugin SHARED src\\/gazebo_gps_plugin.cpp)/a add_library(gazebo_gps_attack_plugin SHARED src/gazebo_gps_attack_plugin.cpp)" "${CMAKE_FILE}"
fi

if ! grep -q "^  gazebo_gps_attack_plugin$" "${CMAKE_FILE}"; then
  sed -i "/^  gazebo_gps_plugin$/a\\  gazebo_gps_attack_plugin" "${CMAKE_FILE}"
fi

# IMU attack plugin: build + install entry, mirroring the GPS pattern.
if ! grep -q "add_library(gazebo_imu_attack_plugin" "${CMAKE_FILE}"; then
  sed -i "/add_library(gazebo_imu_plugin SHARED src\\/gazebo_imu_plugin.cpp)/a add_library(gazebo_imu_attack_plugin SHARED src/gazebo_imu_attack_plugin.cpp)" "${CMAKE_FILE}"
fi
if ! grep -q "^  gazebo_imu_attack_plugin$" "${CMAKE_FILE}"; then
  sed -i "/^  gazebo_imu_plugin$/a\\  gazebo_imu_attack_plugin" "${CMAKE_FILE}"
fi

# Barometer attack plugin: build + install entry.
if ! grep -q "add_library(gazebo_barometer_attack_plugin" "${CMAKE_FILE}"; then
  sed -i "/add_library(gazebo_barometer_plugin SHARED src\\/gazebo_barometer_plugin.cpp)/a add_library(gazebo_barometer_attack_plugin SHARED src/gazebo_barometer_attack_plugin.cpp)" "${CMAKE_FILE}"
fi
if ! grep -q "^  gazebo_barometer_attack_plugin$" "${CMAKE_FILE}"; then
  sed -i "/^  gazebo_barometer_plugin$/a\\  gazebo_barometer_attack_plugin" "${CMAKE_FILE}"
fi

GPS_ATTACK_MODEL_DIR="${SITL_DIR}/models/gps_attack"
mkdir -p "${GPS_ATTACK_MODEL_DIR}"
install -m 0644 "${SCRIPT_DIR}/models/gps_attack/model.config" "${GPS_ATTACK_MODEL_DIR}/model.config"
install -m 0644 "${SCRIPT_DIR}/models/gps_attack/gps_attack.sdf" "${GPS_ATTACK_MODEL_DIR}/gps_attack.sdf"

IRIS_SRC="${SITL_DIR}/models/iris/iris.sdf"
IRIS_ATTACK_DIR="${SITL_DIR}/models/iris_gps_attack"
if [[ ! -f "${IRIS_SRC}" ]]; then
  echo "Missing PX4 iris model: ${IRIS_SRC}" >&2
  exit 1
fi
mkdir -p "${IRIS_ATTACK_DIR}"
sed \
  -e "s/<model name='iris'>/<model name='iris_gps_attack'>/" \
  -e 's#<uri>model://gps</uri>#<uri>model://gps_attack</uri>#' \
  -e 's#libgazebo_imu_plugin.so#libgazebo_imu_attack_plugin.so#' \
  -e 's#libgazebo_barometer_plugin.so#libgazebo_barometer_attack_plugin.so#' \
  "${IRIS_SRC}" > "${IRIS_ATTACK_DIR}/iris_gps_attack.sdf"
cat > "${IRIS_ATTACK_DIR}/model.config" <<'MODEL_CONFIG'
<?xml version="1.0"?>
<model>
  <name>Iris GPS Attack</name>
  <version>1.0</version>
  <sdf version="1.6">iris_gps_attack.sdf</sdf>
  <author>
    <name>LAEA</name>
  </author>
  <description>Iris model with GPS routed through the LAEA GPS attack plugin.</description>
</model>
MODEL_CONFIG

COMPOSITE_SRC="${SITL_DIR}/models/iris_d435_lidar/iris_d435_lidar.sdf"
if [[ ! -f "${COMPOSITE_SRC}" ]]; then
  COMPOSITE_SRC="${SCRIPT_DIR}/../resource/sitl_gazebo/models/iris_d435_lidar/iris_d435_lidar.sdf"
fi
COMPOSITE_ATTACK_DIR="${SITL_DIR}/models/iris_d435_lidar_gps_attack"
if [[ ! -f "${COMPOSITE_SRC}" ]]; then
  echo "Missing iris_d435_lidar model source." >&2
  exit 1
fi
mkdir -p "${COMPOSITE_ATTACK_DIR}"
sed \
  -e "s/<model name='iris_d435_lidar'>/<model name='iris_d435_lidar_gps_attack'>/" \
  -e 's#<uri>model://iris</uri>#<uri>model://iris_gps_attack</uri>#' \
  -e 's#<parent>iris::base_link</parent>#<parent>iris_gps_attack::base_link</parent>#g' \
  "${COMPOSITE_SRC}" > "${COMPOSITE_ATTACK_DIR}/iris_d435_lidar_gps_attack.sdf"
cat > "${COMPOSITE_ATTACK_DIR}/model.config" <<'MODEL_CONFIG'
<?xml version="1.0"?>
<model>
  <name>Iris D435 LiDAR GPS Attack</name>
  <version>1.0</version>
  <sdf version="1.6">iris_d435_lidar_gps_attack.sdf</sdf>
  <author>
    <name>LAEA</name>
  </author>
  <description>LAEA Iris D435 LiDAR model using GPS source-attack input for PX4 EKF2.</description>
</model>
MODEL_CONFIG

echo "Installed GPS attack plugin and models into ${SITL_DIR}"
echo
echo "Build with:"
echo "  cd ${PX4_ROOT}"
echo "  DONT_RUN=1 make px4_sitl gazebo"
echo
echo "Run LAEA with GPS attack model:"
echo "  LAEA_PX4_SDF=iris_d435_lidar_gps_attack GPS_ATTACK_MODE=bias GPS_ATTACK_START_SEC=30 GPS_ATTACK_EAST_BIAS_M=5 ./run_aiottalk_rtp.sh"
