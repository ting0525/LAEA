#!/usr/bin/env bash
# Sequentially collect one retained attack run per profile (nosip, delete=false).
set -u
cd /home/tim/laea/src/LAEA
BASE=/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/attack_multi_$(date +%Y%m%dT%H%M%S)
mkdir -p "$BASE"; echo "$BASE" > /tmp/claude_collect/attack_multi_dir.txt
for prof in gps_bias_high gps_velocity_bias_high imu_gyro_bias_high barometer_drift_high; do
  echo "######## ATTACK $prof ########"
  TOTAL_ROUNDS=1 EXP_WORLD_NAME=indoor_01 EXP_TRANSPORT_MODE=nosip \
    LAEA_PX4_SDF=iris_d435_lidar_gps_attack \
    ATTACK_PROFILE="$prof" ENABLE_MISSION_AWARE=1 EXP_DELETE_ON_NON_SUCCESS=false \
    EXP_MAX_DURATION_S=500 \
    LAEA_LOG_DIR="$BASE/$prof" \
    ENABLE_DITTO_BRIDGE=0 ENABLE_AIOTTALK_RTP=0 ENABLE_NOSIP_RTP=1 DISPLAY=:0 \
    bash ./run_aiottalk_batches_restart.sh || true
done
echo "######## ALL ATTACK SCENARIOS DONE ########"
touch "$BASE/.done"
