# AIoTtalk RTP 測試紀錄

## 2026-05-23 SLAM 回歸修正

### 問題

使用 `run_aiottalk_rtp.sh` 蒐集正常飛行資料時，PX4 已回報 `Armed by external command`
與 `Takeoff detected`，但 exploration 在 trigger 後立即輸出：

```text
No coverable frontier.
finish exploration.
Flight_dist: 0.000000
```

產生的 `aiottalk_normal_v1/kpi_log_run_001.csv` 與 `run_002.csv` 只有約
`0.50s` 與 `0.45s` 資料，因此不可作為正常飛行訓練資料。

### 根因

`MapROS` 使用 `ApproximateTime<sensor_msgs::Image, geometry_msgs::PoseStamped>`
同步 `/rtp/depth/image_raw` 與 `/mavros/camera/pose`。原 Python
`laea_aiottalk_rtp.py` 在 Zdepth 解碼後建立 `Image` 卻沒有設定
`header.stamp`；影像可被 logger 看到，但無法與 camera pose 同步進 SDF map。

正常工作的 C++ `rtp_gazebo/RTPReceiver.cpp` 在發布解碼 image 時會設定
receiver-side ROS timestamp 與 `depth_camera_link` frame。Python 路徑已改為相同行為：

```text
msg.header.stamp = rospy.Time.now()
msg.header.frame_id = depth_camera_link
msg.header.seq = per-stream sequence
```

### 回歸測試

指令：

```bash
LAEA_LOG_DIR="$PWD/laea_twin_tools/laea_logs/aiottalk_header_verify" \
LAEA_SYS_LOG_DIR=/tmp/laea_aiottalk_header_verify_logs \
EXP_NUM_RUNS=1 \
EXP_MAX_DURATION_S=45 \
EXP_DELETE_ON_NON_SUCCESS=false \
EXP_SCENARIO=normal_header_verify \
EXP_TRANSPORT_MODE=aiottalk_rtp \
EXP_WORLD_NAME=indoor_01 \
ENABLE_RVIZ=0 \
ENABLE_DITTO_BRIDGE=0 \
./run_aiottalk_rtp.sh
```

結果：

| 檢查項目 | 結果 |
|---|---|
| PX4 arm / takeoff | PASS |
| SDP / 10 streams 建立 | PASS |
| RTP depth quality | PASS，`rtp_depth_stale=0` |
| Planner map/frontier | PASS，持續輸出 `exploration planning success` |
| 實際移動 | PASS，45 秒內 GT span 約 `8.67m x 9.34m` |
| CSV | PASS，`892` rows，`mission_outcome=TIMEOUT_NO_FINISH`（測試刻意限時） |

本次修正後，AIoTtalk RTP depth 已可作為 SLAM planning 的 depth input。

另外以 `EXP_MAX_DURATION_S=8`、`EXP_DELETE_ON_NON_SUCCESS=false` 重跑 status
驗證，飛行期間仍持續規劃且 GT span 約 `4.29m x 0.89m`；任務結束後輸出正確為：

```text
[run_aiottalk_rtp] done. result=FAIL kept_delta=1 success_delta=0 rc=0
mission_outcome=TIMEOUT_NO_FINISH
```

這確認保留 timeout 資料供除錯時，不會再被誤列為成功正常任務。

### 批次資料收集限制

同一個 exploration process 在任務完成後停於 `FINISH`，不可使用
`EXP_NUM_RUNS=10 ./run_aiottalk_rtp.sh` 蒐集十趟獨立任務。正式收集應使用
`run_aiottalk_batches_restart.sh`，讓每一趟重新啟動 ROS/PX4/Gazebo/planner。

測試時間：

- Local：`2026-05-19T02:39:45-04:00`
- UTC：`2026-05-19T06:39:45Z`

## 摘要

結果：**PASS（僅證明 stream 傳輸；完整 SLAM 飛行驗收以 2026-05-23 回歸測試為準）**。

這次測試確認目前專案中的影像與主要感測器資料都已接到 AIoTtalk RTP 路徑：

| Stream | ROS input | RTP media / codec | Sender port | Receiver port | ROS output | 結果 |
|---|---|---|---:|---:|---|---|
| RGB image | `/camera/depth/rgb_image_raw` | `video` / H264 | `10000` | `11000` | `/rtp/depth/rgb_image_raw` | PASS |
| Depth image | `/camera/depth/image_raw` | `depth_image` / Zdepth | `12000` | `13000` | `/rtp/depth/image_raw` | PASS |
| PointCloud2 | `/camera/depth/color/points` | `raw_bytes` | `14000` | `15000` | `/rtp/pointcloud/depth` | PASS |
| CameraInfo | `/camera/depth/camera_info` | `raw_bytes` | `16000` | `17000` | `/rtp/depth/camera_info` | PASS |
| IMU | `/mavros/imu/data` | `raw_bytes` | `18000` | `19000` | `/rtp/imu/data` | PASS |
| GPS fix | `/mavros/global_position/raw/fix` | `raw_bytes` | `20000` | `21000` | `/rtp/gps/fix` | PASS |
| GPS velocity | `/mavros/global_position/raw/gps_vel` | `raw_bytes` | `22000` | `23000` | `/rtp/gps/vel` | PASS |
| GPS satellites | `/mavros/global_position/raw/satellites` | `raw_bytes` | `24000` | `25000` | `/rtp/gps/satellites` | PASS |
| Odometry | `/mavros/local_position/odom` | `raw_bytes` | `26000` | `27000` | `/rtp/local_odom` | PASS |
| Pose | `/mavros/camera/pose` | `raw_bytes` | `28000` | `29000` | `/rtp/pose` | PASS |

## 本次實作重點

- `laea_aiottalk_rtp.py` 從 2 條 image stream 擴充成 10 條 stream。
- RGB/depth 維持 H264/Zdepth codec。
- PointCloud2、CameraInfo、IMU、GPS、Odometry、Pose 使用 ROS message serialization，再透過 RTP `raw_bytes` 傳送。
- PointCloud2 在送 RTP 前加上限頻與抽樣，避免 D435 原始 640x480 cloud 太大導致 uvgRTP `Sent bytes overflow` 與 core dump。
- pybind `get_data()` 已釋放 GIL，避免同一 Python node 中 receiver thread 卡住 sender callbacks。

## 執行的測試

### 1. Python 語法檢查

```bash
python3 -m py_compile laea_aiottalk_rtp.py
```

結果：**PASS（舊版腳本依保留檔案誤判 timeout/立即結束為成功，不能單獨證明 SLAM 任務完成）**。

### 2. raw_bytes ROS serialization 單元測試

用 `sensor_msgs/Imu` 序列化成 bytes，經 `RTPSession raw_bytes` 傳送後再還原。

輸出重點：

```text
SEND_RET 0
THREAD_ALIVE False
RAW_IMU_OUT imu_link 1.0 0.25
RAW_BYTES_ROS_SERIALIZATION_PASS
```

結果：**PASS**。

### 3. 全 stream ROS 合成端到端測試

測試方式：

- 開啟臨時 `roscore`。
- 發布合成資料到全部 input topics。
- 透過 `laea_aiottalk_rtp.py` sender callback 進 RTP。
- 由 receiver loop 發布全部 `/rtp/...` output topics。

輸出重點：

```text
GOT gps_vel geometry_msgs/TwistStamped
GOT camera_info sensor_msgs/CameraInfo
GOT pose geometry_msgs/PoseStamped
GOT gps_fix sensor_msgs/NavSatFix
GOT imu sensor_msgs/Imu
GOT odom nav_msgs/Odometry
GOT gps_satellites std_msgs/UInt32
GOT pointcloud_depth sensor_msgs/PointCloud2
GOT depth sensor_msgs/Image
GOT rgb sensor_msgs/Image
RGB (480, 640, 3) uint8 105.33333333333333
DEPTH 2.3440001010894775
PC_OUT width=15360 height=1 data=245760 raw_limit=262144
AIOTTALK_RTP_ALL_SENSOR_BIG_POINTCLOUD_E2E_PASS
```

驗證內容：

- RGB output encoding 是 `bgr8`。
- Depth output encoding 是 `32FC1`，`2.345m` sample 還原約 `2.344m`。
- 大型 `PointCloud2` 從 `307200` points 抽樣成 `15360` points，仍以 `sensor_msgs/PointCloud2` 發布。
- CameraInfo、IMU、GPS fix、GPS velocity、GPS satellites、Odometry、Pose 內容皆可還原。

結果：**PASS**。

### 4. 縮短版完整 `run_aiottalk_rtp.sh`

指令：

```bash
ENABLE_RVIZ=0 \
ENABLE_DITTO_BRIDGE=0 \
EXP_MAX_DURATION_S=30 \
EXP_DELETE_ON_NON_SUCCESS=false \
LAEA_SYS_LOG_DIR=/tmp/laea_aiottalk_all_stream_logs_2 \
./run_aiottalk_rtp.sh
```

腳本結果：

```text
[run_aiottalk_rtp] done. result=SUCCESS kept_delta=1 rc=0
```

`last_round_status.env`：

```text
ROUND_RESULT=SUCCESS
EXPERIMENT_MANAGER_RC=0
KEPT_LOG_BEFORE=5
KEPT_LOG_AFTER=6
KEPT_LOG_DELTA=1
TIMESTAMP_UTC=2026-05-19T06:39:07Z
```

AIoTtalk RTP bridge log 重點：

```text
This device has successfully registered.
Device name = 90.SIP_SDP
[laea_aiottalk_rtp] Got SDP answer for 10 streams
[laea_aiottalk_rtp] rgb sender ready: 140.114.77.74:10000 -> 140.114.77.74:11000
[laea_aiottalk_rtp] depth sender ready: 140.114.77.74:12000 -> 140.114.77.74:13000
[laea_aiottalk_rtp] pointcloud_depth sender ready: 140.114.77.74:14000 -> 140.114.77.74:15000
[laea_aiottalk_rtp] camera_info sender ready: 140.114.77.74:16000 -> 140.114.77.74:17000
[laea_aiottalk_rtp] imu sender ready: 140.114.77.74:18000 -> 140.114.77.74:19000
[laea_aiottalk_rtp] gps_fix sender ready: 140.114.77.74:20000 -> 140.114.77.74:21000
[laea_aiottalk_rtp] gps_vel sender ready: 140.114.77.74:22000 -> 140.114.77.74:23000
[laea_aiottalk_rtp] gps_satellites sender ready: 140.114.77.74:24000 -> 140.114.77.74:25000
[laea_aiottalk_rtp] odom sender ready: 140.114.77.74:26000 -> 140.114.77.74:27000
[laea_aiottalk_rtp] pose sender ready: 140.114.77.74:28000 -> 140.114.77.74:29000
```

結果：**PASS**。

## 觀察

- RGB/H264 啟動初期仍可能出現一次 `Decode error!`，後續 frame 可正常解碼。
- PointCloud2 原始 D435 cloud 很大，直接 raw RTP 會讓 uvgRTP 不穩；目前採用 `max_hz=2.0`、`max_raw_bytes=262144`，超過時抽樣成較小的 `PointCloud2`。
- 完整腳本可以成功連到外部 IoTtalk server `http://140.114.77.93:9999`，並完成 10 條 stream 的 SDP OK。
- 測試後已清理殘留 process；`10000` 到 `29000` 這些 RTP port 沒有殘留 listener。

## 結論

目前可以確認：

- RGB/depth image 可以經由 AIoTtalk RTP 傳輸。
- PointCloud2、CameraInfo、IMU、GPS fix/velocity/satellites、Odometry、Pose 都已透過 RTP `raw_bytes` 傳輸並還原為原 ROS message type。
- `run_aiottalk_rtp.sh` 在本機縮短版完整流程中可以成功跑完。

尚未涵蓋：

- 長時間飛行壓測。
- 多輪統計與頻寬/延遲量測。
