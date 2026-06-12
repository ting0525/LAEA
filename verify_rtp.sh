#!/usr/bin/env bash
# verify_rtp.sh — 在 SLAM 進行中執行，展示 AIoTtalk+ RTP 串流確實在傳輸
#
# 用法：
#   ./verify_rtp.sh              # 跑完整檢查（topic + UDP 封包）
#   ./verify_rtp.sh --quick      # 只看 topic Hz，不抓封包（不需要 sudo）

set -u

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

if [ -f /opt/ros/noetic/setup.bash ]; then
  source /opt/ros/noetic/setup.bash
fi
if [ -f /home/tim/laea/devel/setup.bash ]; then
  source /home/tim/laea/devel/setup.bash
fi

echo "=============================================="
echo " LAEA RTP Stream Verification"
echo " $(date)"
echo "=============================================="

# ---------- 1. RTP topic 拓樸 ----------
echo
echo "[1/3] /rtp/* topics (來自 AIoTtalk+ RTP bridge):"
echo "----------------------------------------------"
rostopic list 2>/dev/null | grep ^/rtp/ | sort
n=$(rostopic list 2>/dev/null | grep -c ^/rtp/)
echo "→ 共 ${n} 條 RTP topic"

# ---------- 2. 每條 stream 的資料率 ----------
echo
echo "[2/3] 每條 stream 的 Hz（每條取樣 3 秒）："
echo "----------------------------------------------"
TOPICS=(
  "/rtp/depth/rgb_image_raw"   # RGB (H264)
  "/rtp/depth/image_raw"       # Depth (Zdepth)
  "/rtp/pointcloud/depth"      # PointCloud2
  "/rtp/depth/camera_info"     # CameraInfo
  "/rtp/imu/data"              # IMU
  "/rtp/gps/fix"               # GPS fix
  "/rtp/gps/vel"               # GPS velocity
  "/rtp/gps/satellites"        # GPS satellites
  "/rtp/local_odom"            # local odometry
  "/rtp/pose"                  # pose
)

for t in "${TOPICS[@]}"; do
  hz=$(timeout 3 rostopic hz "${t}" 2>/dev/null \
        | grep -m1 "average rate" | awk '{print $3}')
  if [ -z "${hz}" ]; then
    printf "  %-32s  %s\n" "${t}" "no data"
  else
    printf "  %-32s  %s Hz\n" "${t}" "${hz}"
  fi
done

# ---------- 3. UDP 封包（最強證據）----------
if [ "${QUICK}" = "0" ]; then
  echo
  echo "[3/3] UDP RTP 封包擷取 (port 10000-29000, lo, 3 秒)："
  echo "----------------------------------------------"
  if ! command -v tcpdump >/dev/null 2>&1; then
    echo "  tcpdump 未安裝，跳過。安裝：sudo apt install tcpdump"
  else
    sudo -n true 2>/dev/null
    if [ $? -ne 0 ]; then
      echo "  需要 sudo 權限抓封包，請輸入密碼："
    fi
    sudo timeout 3 tcpdump -ni lo -q 'udp portrange 10000-29000' 2>/dev/null \
      | awk '{print}' | head -20
    echo "  ..."
    pkt=$(sudo timeout 3 tcpdump -ni lo -q 'udp portrange 10000-29000' 2>/dev/null | wc -l)
    echo "→ 3 秒內擷取到 ${pkt} 筆 UDP 封包（>0 即代表 RTP 真的在網路上跑）"
  fi
else
  echo
  echo "[3/3] (--quick 模式，跳過 UDP 封包擷取)"
fi

echo
echo "=============================================="
echo " 結論：上面三項皆有數字 → RTP 串流運作正常"
echo "=============================================="
