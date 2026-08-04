#!/usr/bin/env bash
# Collect comparable, clean normal-flight data from the four approved LAEA maps.
#
# One map runs at a time because PX4/Gazebo/ROS use fixed local ports.  The
# runner retains only SUCCESS_FINISH logs; every map directory also keeps its
# run_manifest.csv, batch_progress.json, quality manifest, and collection card.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_ROOT="${LAEA_LOG_ROOT:-${SCRIPT_DIR}/laea_twin_tools/laea_logs}"
CAMPAIGN_ID="${CAMPAIGN_ID:-normal_four_maps_v1_$(date -u +%Y%m%dT%H%M%SZ)}"
CAMPAIGN_DIR="${LOG_ROOT}/${CAMPAIGN_ID}"
ROUNDS_PER_MAP="${ROUNDS_PER_MAP:-20}"
SLEEP_BETWEEN_ROUNDS="${SLEEP_BETWEEN_ROUNDS:-5}"
WORLD_LIST="${WORLD_LIST:-indoor_01 indoor_02 lab_corridor_01 lab_rooms_01}"

if ! [[ "${ROUNDS_PER_MAP}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ROUNDS_PER_MAP must be a positive integer, got: ${ROUNDS_PER_MAP}" >&2
  exit 2
fi

mkdir -p "${CAMPAIGN_DIR}/system_logs"
printf '%s\n' "${CAMPAIGN_DIR}" > "${CAMPAIGN_DIR}/campaign_path.txt"

write_card() {
  local dataset_dir="$1" world="$2" world_file="$3" max_duration="$4"
  local map_x="$5" map_y="$6" map_z="$7" x_min="$8" y_min="$9" z_min="${10}"
  local x_max="${11}" y_max="${12}" z_max="${13}" min_time="${14}" min_dist="${15}"
  local sha256
  sha256="$(sha256sum "${world_file}" | awk '{print $1}')"
  python3 - \
    "${dataset_dir}/collection_card.json" "${CAMPAIGN_ID}" "${world}" "${world_file}" "${sha256}" \
    "${ROUNDS_PER_MAP}" "${max_duration}" "${map_x}" "${map_y}" "${map_z}" \
    "${x_min}" "${y_min}" "${z_min}" "${x_max}" "${y_max}" "${z_max}" "${min_time}" "${min_dist}" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

(
    path, campaign_id, world, world_file, world_sha256, attempts_planned,
    max_duration_s, map_size_x, map_size_y, map_size_z,
    box_x_min, box_y_min, box_z_min, box_x_max, box_y_max, box_z_max,
    min_finish_time_s, min_finish_distance_m,
) = sys.argv[1:]

payload = {
    "schema_version": 1,
    "campaign_id": campaign_id,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "scenario": "normal",
    "acceptance_rule": "outcome=SUCCESS_FINISH and independent quality_ok=1",
    "attempts_planned": int(attempts_planned),
    "transport_mode": "nosip",
    "attack_profile": "none",
    "mission_aware": False,
    "world": {
        "name": world,
        "file": world_file,
        "sha256": world_sha256,
        "planner": {
            "map_size": [float(map_size_x), float(map_size_y), float(map_size_z)],
            "bounds": {
                "x": [float(box_x_min), float(box_x_max)],
                "y": [float(box_y_min), float(box_y_max)],
                "z": [float(box_z_min), float(box_z_max)],
            },
            "min_finish_time_s": float(min_finish_time_s),
            "min_finish_distance_m": float(min_finish_distance_m),
        },
    },
    "runtime": {
        "max_duration_s": float(max_duration_s),
        "delete_on_non_success": True,
        "ditto_bridge": False,
        "aiottalk_rtp": False,
        "nosip_rtp": True,
    },
}

temp_path = path + ".tmp"
with open(temp_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(temp_path, path)
PY
}

run_map() {
  local world="$1"
  local world_file map_x map_y map_z x_min y_min z_min x_max y_max z_max min_time min_dist max_duration

  case "${world}" in
    indoor_01)
      world_file="/home/tim/PX4-Autopilot/Tools/sitl_gazebo/worlds/indoor_01.world"
      map_x=80; map_y=80; map_z=3; x_min=-23; y_min=-11; z_min=-0.1; x_max=23; y_max=11; z_max=2.3; min_time=300; min_dist=200; max_duration=900
      ;;
    indoor_02)
      world_file="/home/tim/PX4-Autopilot/Tools/sitl_gazebo/worlds/indoor_02.world"
      map_x=80; map_y=80; map_z=3; x_min=-18; y_min=-14; z_min=-0.1; x_max=18; y_max=16; z_max=2.5; min_time=300; min_dist=200; max_duration=900
      ;;
    lab_corridor_01)
      world_file="${SCRIPT_DIR}/px4_gazebo/resource/sitl_gazebo/worlds/lab_corridor_01.world"
      map_x=30; map_y=30; map_z=4; x_min=-11.5; y_min=-11.5; z_min=-0.1; x_max=11.5; y_max=11.5; z_max=2.5; min_time=120; min_dist=80; max_duration=600
      ;;
    lab_rooms_01)
      world_file="${SCRIPT_DIR}/px4_gazebo/resource/sitl_gazebo/worlds/lab_rooms_01.world"
      map_x=34; map_y=30; map_z=4; x_min=-12.5; y_min=-10.5; z_min=-0.1; x_max=12.5; y_max=10.5; z_max=2.5; min_time=150; min_dist=100; max_duration=600
      ;;
    *)
      echo "Unsupported world in WORLD_LIST: ${world}" >&2
      return 2
      ;;
  esac

  if [ ! -f "${world_file}" ]; then
    echo "World file does not exist: ${world_file}" >&2
    return 2
  fi

  local dataset_dir="${CAMPAIGN_DIR}/${world}"
  mkdir -p "${dataset_dir}"
  write_card "${dataset_dir}" "${world}" "${world_file}" "${max_duration}" \
    "${map_x}" "${map_y}" "${map_z}" "${x_min}" "${y_min}" "${z_min}" \
    "${x_max}" "${y_max}" "${z_max}" "${min_time}" "${min_dist}"

  echo "========== ${world}: ${ROUNDS_PER_MAP} attempts =========="
  set +e
  env \
    TOTAL_ROUNDS="${ROUNDS_PER_MAP}" \
    SLEEP_BETWEEN_ROUNDS="${SLEEP_BETWEEN_ROUNDS}" \
    EXP_SCENARIO=normal \
    EXP_WORLD_NAME="${world}" \
    EXP_WORLD_FILE="${world_file}" \
    EXP_TRANSPORT_MODE=nosip \
    EXP_MAX_DURATION_S="${max_duration}" \
    EXP_MAP_SIZE_X="${map_x}" EXP_MAP_SIZE_Y="${map_y}" EXP_MAP_SIZE_Z="${map_z}" \
    EXP_BOX_X_MIN="${x_min}" EXP_BOX_Y_MIN="${y_min}" EXP_BOX_Z_MIN="${z_min}" \
    EXP_BOX_X_MAX="${x_max}" EXP_BOX_Y_MAX="${y_max}" EXP_BOX_Z_MAX="${z_max}" \
    EXP_MIN_FINISH_TIME_S="${min_time}" EXP_MIN_FINISH_DISTANCE_M="${min_dist}" \
    EXP_DELETE_ON_NON_SUCCESS=true \
    ATTACK_PROFILE=none ENABLE_MISSION_AWARE=0 \
    ENABLE_DITTO_BRIDGE=0 ENABLE_AIOTTALK_RTP=0 ENABLE_NOSIP_RTP=1 \
    ENABLE_RVIZ=0 ENABLE_GAZEBO_GUI=0 DISPLAY=:0 \
    LAEA_LOG_DIR="${dataset_dir}" \
    LAEA_SYS_LOG_DIR="${CAMPAIGN_DIR}/system_logs/${world}" \
    bash "${SCRIPT_DIR}/run_aiottalk_batches_restart.sh"
  local batch_rc=$?
  set -e

  set +e
  python3 "${SCRIPT_DIR}/tools/dt_ids/build_run_manifest.py" \
    --input "${dataset_dir}/kpi_log_run_*.csv" \
    --out "${dataset_dir}/quality_manifest.csv"
  local quality_rc=$?
  set -e

  python3 - "${dataset_dir}" "${world}" "${batch_rc}" "${quality_rc}" <<'PY'
import csv
import json
import os
import sys

dataset_dir, world, batch_rc, quality_rc = sys.argv[1:]
manifest_path = os.path.join(dataset_dir, "run_manifest.csv")
quality_path = os.path.join(dataset_dir, "quality_manifest.csv")

attempts = successes = 0
if os.path.isfile(manifest_path):
    with open(manifest_path, newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            attempts += 1
            successes += int(row.get("outcome") == "SUCCESS_FINISH" and row.get("log_retained", "").lower() == "true")

quality_ok = 0
if os.path.isfile(quality_path):
    with open(quality_path, newline="", encoding="utf-8") as source:
        quality_ok = sum(int(row.get("quality_ok", "0")) for row in csv.DictReader(source))

payload = {
    "world": world,
    "attempts_completed": attempts,
    "success_finish_retained": successes,
    "quality_ok": quality_ok,
    "batch_exit_code": int(batch_rc),
    "quality_manifest_exit_code": int(quality_rc),
}
path = os.path.join(dataset_dir, "collection_result.json")
temp_path = path + ".tmp"
with open(temp_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(temp_path, path)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
}

for world in ${WORLD_LIST}; do
  run_map "${world}"
done

python3 - "${CAMPAIGN_DIR}" "${CAMPAIGN_ID}" <<'PY'
import glob
import json
import os
import sys
from datetime import datetime, timezone

campaign_dir, campaign_id = sys.argv[1:]
results = []
for path in sorted(glob.glob(os.path.join(campaign_dir, "*", "collection_result.json"))):
    with open(path, encoding="utf-8") as source:
        results.append(json.load(source))

payload = {
    "campaign_id": campaign_id,
    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    "maps": results,
    "totals": {
        "attempts_completed": sum(item["attempts_completed"] for item in results),
        "success_finish_retained": sum(item["success_finish_retained"] for item in results),
        "quality_ok": sum(item["quality_ok"] for item in results),
    },
}
path = os.path.join(campaign_dir, "campaign_summary.json")
temp_path = path + ".tmp"
with open(temp_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(temp_path, path)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

echo "Collection campaign completed: ${CAMPAIGN_DIR}"
