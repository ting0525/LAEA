# Final normal-data collection plan

The final C1 normal-flight dataset is map-balanced and run-level auditable.

| Item | Final value |
|---|---:|
| Approved maps | indoor_01, indoor_02, lab_corridor_01, lab_rooms_01 |
| Quality-accepted normal runs per map | 25 |
| Total accepted normal runs | 100 |
| Per-map training split | 17 train / 4 validation / 4 test |
| Maximum raw attempts per map | 50 |
| Top-up execution unit | 5 attempts, then recompute the quality manifest |

The top-up runner preserves the current campaign directory and its persistent
run sequence. It writes separate per-pass audit cards under the map's
final_topups directory; it never overwrites the original collection card or
the initial batch progress file.

The guarded runner waits until the active four-map 20-round campaign has
completed before starting any top-up run. Its status file is
final_normal_collection_v1_status.json in the campaign root.

    setsid bash ./collect_normal_final_v1_topups.sh \
      ./laea_twin_tools/laea_logs/normal_four_maps_v1_20260728T031727Z \
      > ./laea_twin_tools/laea_logs/normal_four_maps_v1_20260728T031727Z/final_topup_console.log 2>&1 &

After it reports COMPLETED, build the immutable final registry:

    python3 tools/dt_ids/build_normal_campaign_registry.py \
      --campaign-dir ./laea_twin_tools/laea_logs/normal_four_maps_v1_20260728T031727Z \
      --out ./laea_twin_tools/laea_logs/normal_four_maps_v1_20260728T031727Z/final_normal_registry.json \
      --runs-per-map 25 --train-per-map 17 --val-per-map 4 --test-per-map 4 \
      --feature-set gps_derived --strict
