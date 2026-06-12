# LAEA 啟動流程

## 前置確認

```bash
# ROS workspace 已編譯
ls ~/laea/devel/setup.bash

# PX4 路徑存在
ls ~/PX4-Autopilot/launch/single_vehicle_spawn_sdf.launch

# 需要 X display（Gazebo / rviz 都是 GUI）
echo $DISPLAY   # 應顯示 :0 之類的值
```

---

## 一、批次實驗（主要用途）

### 啟動（背景持續跑）

```bash
cd ~/laea/src/LAEA

DISPLAY=:0 screen -dmS laea_batches -L -Logfile /tmp/laea_batches.log \
  ./run_nosip_batches_restart.sh
```

預設跑 **100 rounds**，每 round 跑一次完整探索任務後自動重啟。

### 自訂 rounds

```bash
TOTAL_ROUNDS=10 DISPLAY=:0 screen -dmS laea_batches -L -Logfile /tmp/laea_batches.log \
  ./run_nosip_batches_restart.sh
```

---

## 二、單次實驗

```bash
cd ~/laea/src/LAEA
DISPLAY=:0 ./run_nosip_depth.sh
```

成功完成後 exit 0，任務失敗或超時則 exit 2。

---

## 三、監控

```bash
# 進入 screen session 看即時輸出（Ctrl-A D 離開，不會中斷）
screen -r laea_batches

# 只看 log 不進 screen
tail -f /tmp/laea_batches.log

# 各元件的獨立 log
tail -f /tmp/laea_nosip_logs/px4_gazebo.log
tail -f /tmp/laea_nosip_logs/controller.log
tail -f /tmp/laea_nosip_logs/explore.log
tail -f /tmp/laea_nosip_logs/ditto_bridge.log
tail -f /tmp/laea_nosip_logs/mapping.log

# 最後一個 round 的結果
cat ~/laea/src/LAEA/laea_twin_tools/laea_logs/nosip/last_round_status.env

# 已收集的 KPI log 數量
ls ~/laea/src/LAEA/laea_twin_tools/laea_logs/nosip/kpi_log_run_*.csv | wc -l
```

---

## 四、停止

```bash
# 停止 batch wrapper
screen -S laea_batches -X quit

# 強制清掉所有 ROS / Gazebo / PX4 殘留 process（batch wrapper 結束後也可手動執行）
rosnode kill -a 2>/dev/null || true
pkill -f roslaunch || true
pkill -f gzserver  || true
pkill -f gzclient  || true
pkill -f px4       || true
pkill -f mavros    || true
pkill -f roscore   || true
pkill -f rosmaster || true
```

---

## 五、環境變數（覆寫預設值）

### `run_nosip_batches_restart.sh`

| 變數 | 預設 | 說明 |
|---|---|---|
| `TOTAL_ROUNDS` | `100` | 總 round 數 |
| `SLEEP_BETWEEN_ROUNDS` | `5` | 每 round 間隔（秒） |

### `run_nosip_depth.sh`

| 變數 | 預設 | 說明 |
|---|---|---|
| `EXP_MAX_DURATION_S` | `900.0` | 單次任務上限（秒） |
| `EXP_NUM_RUNS` | `1` | 每次啟動跑幾趟 |
| `EXP_FAIL_ERROR_M` | `10.0` | 判定失敗的位置誤差閾值（公尺） |
| `EXP_DELETE_ON_NON_SUCCESS` | `true` | 失敗時是否刪除 KPI log |
| `ENABLE_RVIZ` | `1` | 是否啟動 rviz（headless 設 `0`） |
| `ENABLE_DITTO_BRIDGE` | `1` | 是否上傳遙測至 Eclipse Ditto |
| `DITTO_ENABLE_SLAM` | `false` | Ditto bridge 是否包含 SLAM 誤差 |
| `LAEA_LOG_DIR` | `laea_twin_tools/laea_logs/nosip` | KPI log 輸出目錄 |

### 使用範例

```bash
# headless + 縮短上限 + 只跑 5 rounds
TOTAL_ROUNDS=5 ENABLE_RVIZ=0 EXP_MAX_DURATION_S=300 \
  DISPLAY=:0 screen -dmS laea_test -L -Logfile /tmp/laea_test.log \
  ./run_nosip_batches_restart.sh
```

---

## 六、Log 位置整理

| 內容 | 路徑 |
|---|---|
| batch wrapper 輸出 | `/tmp/laea_batches.log` |
| 各元件系統 log | `/tmp/laea_nosip_logs/*.log` |
| KPI 資料（每 run 一個 CSV） | `laea_twin_tools/laea_logs/nosip/kpi_log_run_*.csv` |
| 最後 round 結果 | `laea_twin_tools/laea_logs/nosip/last_round_status.env` |

---

## 七、啟動順序（`run_nosip_depth.sh` 內部）

1. `px4_gazebo` — Gazebo 模擬環境 + PX4 SITL + MAVROS
2. `controller` — 幾何飛行控制器
3. `ditto_bridge` — 遙測上傳至 Eclipse Ditto（可關閉）
4. `rtp_receiver` / `rtp_sender` — RTP 影像收發（無 SIP/IoTtalk 模式）
5. `mapping` — Octomap 地圖建構
6. `explore` — LAEA 探索演算法
7. `rviz` — 視覺化（可關閉）
8. 設定 OFFBOARD 模式 → Arm 無人機
9. `experiment_manager.py` — 前景執行，監控任務完成或超時
