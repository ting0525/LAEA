# LAEA 攻擊模擬現況

更新日期：2026-06-22

## 已接通並實測

| 攻擊 | Dashboard profile | 注入位置 | 參數 | 現況 |
|---|---|---|---|---|
| GPS 位置偏移（低） | `gps_bias_low` | Gazebo GPS sensor → PX4 EKF2 | `[10, 0, 0]` m，2 秒 ramp | 大幅展示；可能觸發 FAIL_SLAM |
| GPS 位置偏移（高） | `gps_bias_high` | Gazebo GPS sensor → PX4 EKF2 | `[30, 0, 0]` m，0.5 秒 ramp | 極端展示；預期快速失敗 |
| GPS 速度偏移（低） | `gps_velocity_bias_low` | Gazebo GPS sensor → PX4 EKF2 | `[3, 0, 0]` m/s，1 秒 ramp | 大幅展示；超過 CRITICAL 門檻 |
| GPS 速度偏移（高） | `gps_velocity_bias_high` | Gazebo GPS sensor → PX4 EKF2 | `[8, 0, 0]` m/s，0.5 秒 ramp | 極端展示；預期快速失穩 |

Dashboard 實驗固定載入 `iris_d435_lidar_gps_attack`。攻擊未啟用時會輸出正常 GPS；收到 Dashboard 指令後，才會在 PX4 EKF2 前修改 GPS 資料。

以上是刻意放大的展示級強度。Low 也可能超過 10 m 任務失敗門檻；High
則是故意讓問題在數秒內明顯出現的極端測試。觸發後應立即觀察 Terminal
或截圖。

## Mission State 四個面向

| 面向 | 代表意義 | 目前使用的指標 |
|---|---|---|
| Localization | 無人機是否知道自己在哪裡，且不同定位來源是否一致 | GPS 與 EKF 位置差、GPS 與 EKF 速度差、IMU yaw rate 差、氣壓高度差 |
| Perception | 無人機是否持續取得可信的環境資訊 | Depth frame age、有效深度比例、重複畫面比例 |
| Planner | 規劃器是否持續產生可追蹤的飛行命令 | Command age、tracking error、stall duration |
| Flight safety | 無人機目前的運動是否接近不安全狀態 | Roll/pitch 傾斜角、三維速度 |

GPS 攻擊的直接目標是 Localization。當錯誤定位讓無人機追錯方向、速度增加
或無法追蹤規劃路徑時，Planner 和 Flight safety 才可能接著惡化。
Perception 主要反映 depth/RTP 狀態，因此 GPS 攻擊時維持 NORMAL 是合理
結果，不代表攻擊沒有成功。

每個面向顯示：

- `NORMAL`：目前指標低於 degraded 門檻。
- `DEGRADED`：至少一項指標超過警戒門檻。
- `CRITICAL`：至少一項指標超過嚴重門檻。
- `score`：該面向最嚴重指標相對於 degraded 門檻的倍率；通常 `1.0`
  附近代表開始進入 DEGRADED，但 CRITICAL 仍以各指標自己的 critical
  threshold 判定。

## 尚未完成

| 攻擊 | 現況 |
|---|---|
| IMU gyro bias | YAML profile 已定義，但 Gazebo source-layer injector 尚未接通 |
| Barometer drift | YAML profile 已定義，但 Gazebo source-layer injector 尚未接通 |
| GPS jump / noise / freeze | GPS plugin 具備程式能力，但尚未加入正式 Dashboard profile 與逐項驗證 |

因此，目前對外可明確宣稱的是「GPS 位置偏移與 GPS 速度偏移攻擊」。IMU、氣壓計及其他 GPS 模式不可描述成已完成。

## 截圖數據

- GPS 位置偏移：[laea_gps_attack_evidence_live.png](/home/tim/Pictures/laea_gps_attack_evidence_live.png)
- GPS 速度偏移：[laea_gps_velocity_attack_evidence_live.png](/home/tim/Pictures/laea_gps_velocity_attack_evidence_live.png)

這兩張是調高強度前的路徑驗證截圖；注入架構仍相同，但其中顯示的 3 m
與 1 m/s 已不是目前 profile 數值。

正式截圖應同時包含：

1. `EXPERIMENT RUNNING` 與 `DATA LIVE`
2. `ROS → Gazebo bridge ONLINE`
3. 攻擊來源、模式、強度及向量
4. Gazebo Ground truth 與 PX4 EKF position
5. Baseline、Current、Peak drift
6. `DRIFT INCREASE OBSERVED`
7. Mission State 與 residual summary

## Dashboard 截圖流程

1. 啟動單次實驗，Supervisor policy 選 `none`。
2. 等待 PX4 進入 `OFFBOARD` 且 Armed。
3. 在攻擊控制區選擇 GPS profile 並觸發。
4. 等待數據結果顯示 `DRIFT INCREASE OBSERVED`。
5. 按「數據模式」，或開啟 `http://127.0.0.1:12346/?evidence=1`。
6. 在實驗仍執行時截圖。

數據模式的漂移值定義為 PX4 EKF local position 與 Gazebo model ground
truth 的 XY 平面距離。它證明攻擊指令不只被發布，也已造成估測位置偏離
真值。

## Terminal 即時監控

Dashboard 與實驗啟動後，開啟另一個 Terminal：

```bash
cd /home/tim/laea/src/LAEA
./run_attack_monitor.sh
```

請在 Dashboard 觸發攻擊前先啟動監控器，這樣才能保存正確的攻擊前
baseline drift。

畫面會即時顯示攻擊模式、注入向量、攻擊階段、Gazebo 真值、PX4 EKF
位置、定位漂移、Mission State，以及 `ATTACK IMPACT OBSERVED` 判定。

需要保留逐行文字 log 時：

```bash
./run_attack_monitor.sh --plain --verbose | tee attack_result.log
```

定位漂移採用 XY 平面距離，與 Dashboard 數據模式相同。Z 軸在目前模擬
座標鏈中帶有固定 frame offset，因此只顯示、不納入攻擊影響門檻。
