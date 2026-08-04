#!/usr/bin/env bash
# Collect normal flight data, alternating indoor_01 / indoor_02 (nosip), until 08:00 tomorrow.
set -u
cd /home/tim/laea/src/LAEA
STOP=$(date -d 'tomorrow 08:00' +%s)
BASE=/home/tim/laea/src/LAEA/laea_twin_tools/laea_logs/normal_overnight_$(date +%Y%m%dT%H%M%S)
mkdir -p "$BASE/indoor_01" "$BASE/indoor_02"
echo "$BASE" > /tmp/claude_collect/overnight_dir.txt
i=0
while [ "$(date +%s)" -lt "$STOP" ]; do
  if [ $((i % 2)) -eq 0 ]; then
    W=indoor_01; BOX=""
  else
    W=indoor_02
    BOX="EXP_BOX_X_MIN=-18 EXP_BOX_X_MAX=18 EXP_BOX_Y_MIN=-14 EXP_BOX_Y_MAX=16 EXP_BOX_Z_MIN=-0.1 EXP_BOX_Z_MAX=2.5"
  fi
  echo "######## iter=$i world=$W $(date '+%m-%d %H:%M') (stop at 08:00) ########"
  env $BOX TOTAL_ROUNDS=1 EXP_WORLD_NAME=$W EXP_TRANSPORT_MODE=nosip \
    LAEA_LOG_DIR="$BASE/$W" ATTACK_PROFILE=none \
    ENABLE_DITTO_BRIDGE=0 ENABLE_AIOTTALK_RTP=0 ENABLE_NOSIP_RTP=1 DISPLAY=:0 \
    bash ./run_aiottalk_batches_restart.sh || true
  i=$((i + 1))
done
echo "######## OVERNIGHT COLLECTION DONE at $(date) ########"
touch "$BASE/.done"
