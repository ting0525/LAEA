#!/usr/bin/env bash
# GPS-bias sensitivity sweep: one retained run per magnitude (nosip, delete=false).
set -u
cd /home/tim/laea/src/LAEA
BASE=/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/sweep_gps_$(date +%Y%m%dT%H%M%S)
mkdir -p "$BASE"; echo "$BASE" > /tmp/claude_collect/sweep_gps_dir.txt
for prof in gps_bias_2m gps_bias_3m gps_bias_5m gps_bias_8m gps_bias_12m; do
  echo "######## SWEEP $prof $(date '+%H:%M') ########"
  TOTAL_ROUNDS=1 EXP_WORLD_NAME=indoor_01 EXP_TRANSPORT_MODE=nosip \
    LAEA_PX4_SDF=iris_d435_lidar_gps_attack \
    ATTACK_PROFILE="$prof" ENABLE_MISSION_AWARE=1 EXP_DELETE_ON_NON_SUCCESS=false \
    EXP_MAX_DURATION_S=400 \
    LAEA_LOG_DIR="$BASE/$prof" \
    ENABLE_DITTO_BRIDGE=0 ENABLE_AIOTTALK_RTP=0 ENABLE_NOSIP_RTP=1 DISPLAY=:0 \
    bash ./run_aiottalk_batches_restart.sh || true
done
echo "######## GPS SWEEP DONE $(date) ########"
touch "$BASE/.done"
