#!/usr/bin/env bash
# Complete the final normal-flight dataset without racing an active campaign.
#
# Final target: 25 independently quality-accepted normal runs per approved
# map (100 total). The original 20-round campaign remains immutable; this
# script appends uniquely numbered runs to the same map directories, writes
# per-pass audit cards, and recomputes the derived quality manifest.
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 CAMPAIGN_DIR [--dry-run]" >&2
  exit 2
fi

CAMPAIGN_DIR="$1"
DRY_RUN=false
if [ "$#" -eq 2 ]; then
  if [ "$2" != "--dry-run" ]; then
    echo "Only --dry-run is supported as the optional argument." >&2
    exit 2
  fi
  DRY_RUN=true
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_QUALITY_PER_MAP=25
MAX_TOTAL_ATTEMPTS_PER_MAP=50
ATTEMPTS_PER_PASS=5
WAIT_SECONDS=60
MAPS="indoor_01 indoor_02 lab_corridor_01 lab_rooms_01"
STATUS_FILE="$CAMPAIGN_DIR/final_normal_collection_v1_status.json"

if [ ! -d "$CAMPAIGN_DIR" ]; then
  echo "Campaign directory does not exist: $CAMPAIGN_DIR" >&2
  exit 2
fi

map_profile() {
  local world="$1"
  case "$world" in
    indoor_01)
      WORLD_FILE="/home/tim/PX4-Autopilot/Tools/sitl_gazebo/worlds/indoor_01.world"
      MAP_X=80; MAP_Y=80; MAP_Z=3
      X_MIN=-23; Y_MIN=-11; Z_MIN=-0.1; X_MAX=23; Y_MAX=11; Z_MAX=2.3
      MIN_TIME=300; MIN_DIST=200; MAX_DURATION=900
      ;;
    indoor_02)
      WORLD_FILE="/home/tim/PX4-Autopilot/Tools/sitl_gazebo/worlds/indoor_02.world"
      MAP_X=80; MAP_Y=80; MAP_Z=3
      X_MIN=-18; Y_MIN=-14; Z_MIN=-0.1; X_MAX=18; Y_MAX=16; Z_MAX=2.5
      MIN_TIME=300; MIN_DIST=200; MAX_DURATION=900
      ;;
    lab_corridor_01)
      WORLD_FILE="$SCRIPT_DIR/px4_gazebo/resource/sitl_gazebo/worlds/lab_corridor_01.world"
      MAP_X=30; MAP_Y=30; MAP_Z=4
      X_MIN=-11.5; Y_MIN=-11.5; Z_MIN=-0.1; X_MAX=11.5; Y_MAX=11.5; Z_MAX=2.5
      MIN_TIME=120; MIN_DIST=80; MAX_DURATION=600
      ;;
    lab_rooms_01)
      WORLD_FILE="$SCRIPT_DIR/px4_gazebo/resource/sitl_gazebo/worlds/lab_rooms_01.world"
      MAP_X=34; MAP_Y=30; MAP_Z=4
      X_MIN=-12.5; Y_MIN=-10.5; Z_MIN=-0.1; X_MAX=12.5; Y_MAX=10.5; Z_MAX=2.5
      MIN_TIME=150; MIN_DIST=100; MAX_DURATION=600
      ;;
    *)
      echo "Unsupported final-collection map: $world" >&2
      return 2
      ;;
  esac
  [ -f "$WORLD_FILE" ] || { echo "World file does not exist: $WORLD_FILE" >&2; return 2; }
}

initial_campaign_ready() {
  local world progress state
  [ -f "$CAMPAIGN_DIR/campaign_summary.json" ] || return 1
  for world in $MAPS; do
    progress="$CAMPAIGN_DIR/$world/batch_progress.json"
    if [ ! -f "$progress" ]; then
      return 1
    fi
    state="$(python3 - "$progress" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as source:
    print(json.load(source).get("state", ""))
PY
)"
    [ "$state" = "COMPLETED" ] || return 1
  done
}

quality_count() {
  local quality_path="$1"
  if [ ! -f "$quality_path" ]; then
    printf '0\n'
    return
  fi
  python3 - "$quality_path" <<'PY'
import csv
import sys
with open(sys.argv[1], newline="", encoding="utf-8") as source:
    print(sum(int(row.get("quality_ok", "0")) for row in csv.DictReader(source)))
PY
}

attempt_count() {
  local manifest_path="$1"
  if [ ! -f "$manifest_path" ]; then
    printf '0\n'
    return
  fi
  python3 - "$manifest_path" <<'PY'
import csv
import sys
with open(sys.argv[1], newline="", encoding="utf-8") as source:
    print(sum(1 for _ in csv.DictReader(source)))
PY
}

write_status() {
  local state="$1"
  python3 - "$STATUS_FILE" "$CAMPAIGN_DIR" "$state" "$TARGET_QUALITY_PER_MAP" "$MAX_TOTAL_ATTEMPTS_PER_MAP" "$ATTEMPTS_PER_PASS" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

path, campaign_dir, state, target, max_attempts, attempts_per_pass = sys.argv[1:]
payload = {
    "schema_version": 1,
    "campaign_dir": campaign_dir,
    "campaign_id": os.path.basename(campaign_dir),
    "state": state,
    "scenario": "normal",
    "transport_mode": "nosip",
    "approved_maps": ["indoor_01", "indoor_02", "lab_corridor_01", "lab_rooms_01"],
    "quality_target_per_map": int(target),
    "total_quality_target": int(target) * 4,
    "max_total_attempts_per_map": int(max_attempts),
    "attempts_per_topup_pass": int(attempts_per_pass),
    "final_split_per_map": {"train": 17, "val": 4, "test": 4},
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
}
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as target:
    json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
    target.write("\n")
os.replace(temporary, path)
PY
}

write_pass_card() {
  local path="$1" world="$2" pass="$3" attempts="$4" seed="$5" before_attempts="$6" before_quality="$7"
  local world_hash
  world_hash="$(sha256sum "$WORLD_FILE" | awk '{print $1}')"
  python3 - "$path" "$world" "$pass" "$attempts" "$seed" "$before_attempts" "$before_quality" \
    "$TARGET_QUALITY_PER_MAP" "$MAX_TOTAL_ATTEMPTS_PER_MAP" "$WORLD_FILE" "$world_hash" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

(
    path, world, pass_index, attempts, seed, attempts_before, quality_before,
    quality_target, max_attempts, world_file, world_sha256,
) = sys.argv[1:]
payload = {
    "schema_version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "kind": "final_normal_topup_pass",
    "world": world,
    "world_file": world_file,
    "world_sha256": world_sha256,
    "scenario": "normal",
    "transport_mode": "nosip",
    "attack_profile": "none",
    "mission_aware": False,
    "pass_index": int(pass_index),
    "attempts_requested": int(attempts),
    "seed_start": int(seed),
    "attempts_before": int(attempts_before),
    "quality_ok_before": int(quality_before),
    "quality_target": int(quality_target),
    "max_total_attempts": int(max_attempts),
}
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as target:
    json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
    target.write("\n")
os.replace(temporary, path)
PY
}

refresh_quality() {
  local dataset_dir="$1"
  python3 "$SCRIPT_DIR/tools/dt_ids/build_run_manifest.py" \
    --input "$dataset_dir/kpi_log_run_*.csv" \
    --out "$dataset_dir/quality_manifest.csv"
}

run_topups_for_map() {
  local world="$1" map_index="$2"
  local dataset_dir quality_path manifest_path quality attempts remaining rounds pass_index batch_id batch_dir seed
  map_profile "$world"
  dataset_dir="$CAMPAIGN_DIR/$world"
  quality_path="$dataset_dir/quality_manifest.csv"
  manifest_path="$dataset_dir/run_manifest.csv"
  [ -f "$dataset_dir/run_seq.txt" ] || { echo "Missing persistent run sequence: $dataset_dir/run_seq.txt" >&2; return 2; }

  refresh_quality "$dataset_dir"
  quality="$(quality_count "$quality_path")"
  attempts="$(attempt_count "$manifest_path")"
  printf '[final-normal] %s: quality=%s/%s attempts=%s/%s\n' \
    "$world" "$quality" "$TARGET_QUALITY_PER_MAP" "$attempts" "$MAX_TOTAL_ATTEMPTS_PER_MAP"

  mkdir -p "$dataset_dir/final_topups"
  pass_index="$(find "$dataset_dir/final_topups" -mindepth 1 -maxdepth 1 -type d -name 'pass_*' -printf '%f\n' \
    | sed 's/^pass_//' \
    | awk 'BEGIN { maximum = 0 } /^[0-9]+$/ && $1 + 0 > maximum { maximum = $1 + 0 } END { print maximum + 1 }')"
  while [ "$quality" -lt "$TARGET_QUALITY_PER_MAP" ] && [ "$attempts" -lt "$MAX_TOTAL_ATTEMPTS_PER_MAP" ]; do
    remaining=$(( MAX_TOTAL_ATTEMPTS_PER_MAP - attempts ))
    rounds="$ATTEMPTS_PER_PASS"
    if [ "$remaining" -lt "$rounds" ]; then
      rounds="$remaining"
    fi
    batch_id="$(printf 'pass_%03d' "$pass_index")"
    batch_dir="$dataset_dir/final_topups/$batch_id"
    seed=$(( 1000 + map_index * 100 + pass_index * 10 ))
    mkdir -p "$batch_dir"
    write_pass_card "$batch_dir/collection_card.json" "$world" "$pass_index" "$rounds" "$seed" "$attempts" "$quality"

    if [ "$DRY_RUN" = true ]; then
      printf '[dry-run] %s would run %s attempts with seeds %s..%s\n' \
        "$world" "$rounds" "$seed" $(( seed + rounds - 1 ))
      break
    fi

    env \
      TOTAL_ROUNDS="$rounds" \
      SLEEP_BETWEEN_ROUNDS=5 \
      ROUND_STATUS_FILE="$batch_dir/last_round_status.env" \
      BATCH_PROGRESS_FILE="$batch_dir/batch_progress.json" \
      BATCH_INCREMENT_SEED=true \
      ATTACK_SEED="$seed" \
      EXP_SCENARIO=normal \
      EXP_WORLD_NAME="$world" \
      EXP_WORLD_FILE="$WORLD_FILE" \
      EXP_TRANSPORT_MODE=nosip \
      EXP_MAX_DURATION_S="$MAX_DURATION" \
      EXP_MAP_SIZE_X="$MAP_X" EXP_MAP_SIZE_Y="$MAP_Y" EXP_MAP_SIZE_Z="$MAP_Z" \
      EXP_BOX_X_MIN="$X_MIN" EXP_BOX_Y_MIN="$Y_MIN" EXP_BOX_Z_MIN="$Z_MIN" \
      EXP_BOX_X_MAX="$X_MAX" EXP_BOX_Y_MAX="$Y_MAX" EXP_BOX_Z_MAX="$Z_MAX" \
      EXP_MIN_FINISH_TIME_S="$MIN_TIME" EXP_MIN_FINISH_DISTANCE_M="$MIN_DIST" \
      EXP_DELETE_ON_NON_SUCCESS=true \
      ATTACK_PROFILE=none ENABLE_MISSION_AWARE=0 \
      ENABLE_DITTO_BRIDGE=0 ENABLE_AIOTTALK_RTP=0 ENABLE_NOSIP_RTP=1 \
      ENABLE_RVIZ=0 ENABLE_GAZEBO_GUI=0 DISPLAY=:0 \
      LAEA_LOG_DIR="$dataset_dir" \
      LAEA_SYS_LOG_DIR="$CAMPAIGN_DIR/system_logs/final_topup_v1/$world/$batch_id" \
      bash "$SCRIPT_DIR/run_aiottalk_batches_restart.sh"

    refresh_quality "$dataset_dir"
    quality="$(quality_count "$quality_path")"
    attempts="$(attempt_count "$manifest_path")"
    printf '[final-normal] %s after %s: quality=%s/%s attempts=%s/%s\n' \
      "$world" "$batch_id" "$quality" "$TARGET_QUALITY_PER_MAP" "$attempts" "$MAX_TOTAL_ATTEMPTS_PER_MAP"
    pass_index=$(( pass_index + 1 ))
  done
}

if [ "$DRY_RUN" = true ]; then
  printf '[dry-run] final target: %s quality-accepted normal runs per map (100 total)\n' "$TARGET_QUALITY_PER_MAP"
  for world in $MAPS; do
    dataset_dir="$CAMPAIGN_DIR/$world"
    quality="$(quality_count "$dataset_dir/quality_manifest.csv")"
    attempts="$(attempt_count "$dataset_dir/run_manifest.csv")"
    printf '[dry-run] %s: current quality=%s, current attempts=%s, maximum additional attempts=%s\n' \
      "$world" "$quality" "$attempts" $(( MAX_TOTAL_ATTEMPTS_PER_MAP - attempts ))
  done
  exit 0
fi

trap 'write_status INTERRUPTED; exit 130' INT TERM
trap 'write_status FAILED; exit 1' ERR
write_status WAITING_FOR_INITIAL
until initial_campaign_ready; do
  echo "[final-normal] initial campaign is still active; checking again in $WAIT_SECONDS seconds."
  sleep "$WAIT_SECONDS"
done

write_status RUNNING
map_index=0
for world in $MAPS; do
  run_topups_for_map "$world" "$map_index"
  map_index=$(( map_index + 1 ))
done

all_ready=true
for world in $MAPS; do
  quality="$(quality_count "$CAMPAIGN_DIR/$world/quality_manifest.csv")"
  if [ "$quality" -lt "$TARGET_QUALITY_PER_MAP" ]; then
    all_ready=false
  fi
done

if [ "$all_ready" = true ]; then
  write_status COMPLETED
  echo "[final-normal] final target met: 25 quality-accepted normal runs per map."
else
  write_status INSUFFICIENT
  echo "[final-normal] attempt cap reached before every map met the final target." >&2
  exit 3
fi
