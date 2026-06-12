#!/usr/bin/env bash
# dump_rtp_samples.sh — 撈 RTP 兩個層級的資料
#
#   [A] Receiver layer  — 直接 sniff UDP/RTP 封包，看 seq/timestamp/SSRC/PT
#   [B] Decoded layer   — 從 /rtp/* topic 撈一筆真實 ROS 訊息
#
# 用法：
#   ./dump_rtp_samples.sh                  # 全部 stream，A + B 都跑
#   ./dump_rtp_samples.sh -o file.txt      # 同時存檔
#   ./dump_rtp_samples.sh --no-recv        # 只跑 decoded layer (不用 sudo)
#   ./dump_rtp_samples.sh --no-decoded     # 只跑 receiver layer

set -u

OUT=""
DO_RECV=1
DO_DECODED=1

while [ $# -gt 0 ]; do
  case "$1" in
    -o)            OUT="${2:-}"; shift 2 ;;
    --no-recv)     DO_RECV=0; shift ;;
    --no-decoded)  DO_DECODED=0; shift ;;
    *)             echo "unknown arg: $1"; exit 1 ;;
  esac
done

if [ -f /opt/ros/noetic/setup.bash ]; then
  source /opt/ros/noetic/setup.bash
fi
if [ -f /home/tim/laea/devel/setup.bash ]; then
  source /home/tim/laea/devel/setup.bash
fi

log() {
  if [ -n "${OUT}" ]; then
    printf '%s\n' "$*" | tee -a "${OUT}"
  else
    printf '%s\n' "$*"
  fi
}

# stream key → (receiver_port, ros_topic)
declare -A RECV_PORT=(
  [rgb]=11000 [depth]=13000 [pointcloud]=15000 [camera_info]=17000
  [imu]=19000 [gps_fix]=21000 [gps_vel]=23000 [gps_sat]=25000
  [odom]=27000 [pose]=29000
)
declare -A TOPIC=(
  [rgb]=/rtp/depth/rgb_image_raw
  [depth]=/rtp/depth/image_raw
  [pointcloud]=/rtp/pointcloud/depth
  [camera_info]=/rtp/depth/camera_info
  [imu]=/rtp/imu/data
  [gps_fix]=/rtp/gps/fix
  [gps_vel]=/rtp/gps/vel
  [gps_sat]=/rtp/gps/satellites
  [odom]=/rtp/local_odom
  [pose]=/rtp/pose
)
ORDER=(rgb depth pointcloud camera_info imu gps_fix gps_vel gps_sat odom pose)

RECV_DURATION="${RECV_DURATION:-3}"

[ -n "${OUT}" ] && : > "${OUT}"

log "=============================================="
log " LAEA RTP — Receiver + Decoded Sample Dump"
log " $(date)"
log "=============================================="

# ───────────────────────────────────────────────────────────────
# [A] RECEIVER LAYER — RTP packets on the receiver UDP port
# ───────────────────────────────────────────────────────────────
if [ "${DO_RECV}" = "1" ]; then
  log ""
  log "[A] Receiver layer — RTP header on each receiver port (${RECV_DURATION}s)"
  log "================================================================"

  have_tshark=0; have_tcpdump=0
  command -v tshark  >/dev/null 2>&1 && have_tshark=1
  command -v tcpdump >/dev/null 2>&1 && have_tcpdump=1

  if [ "${have_tshark}" = "0" ] && [ "${have_tcpdump}" = "0" ]; then
    log "  需要 tshark 或 tcpdump：sudo apt install tshark"
  else
    for key in "${ORDER[@]}"; do
      port="${RECV_PORT[$key]}"
      log ""
      log "▶ ${key}  (UDP :${port})"
      log "  ─────────────────────────────"
      if [ "${have_tshark}" = "1" ]; then
        # 把 port 強制當 RTP 解析，列出 RTP header 欄位
        sudo timeout "${RECV_DURATION}" tshark -ni lo \
          -d "udp.port==${port},rtp" \
          -Y "rtp && udp.dstport==${port}" \
          -T fields -E header=y -E separator=, \
          -e frame.time_relative \
          -e rtp.p_type -e rtp.ssrc -e rtp.seq -e rtp.timestamp \
          -e rtp.marker -e udp.length \
          2>/dev/null | head -6 \
          | while IFS= read -r line; do log "  ${line}"; done
        pkt=$(sudo timeout "${RECV_DURATION}" tshark -ni lo \
                -Y "udp.dstport==${port}" -T fields -e frame.number \
                2>/dev/null | wc -l)
        log "  → ${pkt} UDP packets in ${RECV_DURATION}s"
      else
        sudo timeout "${RECV_DURATION}" tcpdump -ni lo -q "udp dst port ${port}" \
          2>/dev/null | head -4 \
          | while IFS= read -r line; do log "  ${line}"; done
        pkt=$(sudo timeout "${RECV_DURATION}" tcpdump -ni lo -q "udp dst port ${port}" \
              2>/dev/null | wc -l)
        log "  → ${pkt} UDP packets in ${RECV_DURATION}s"
      fi
    done
  fi
fi

# ───────────────────────────────────────────────────────────────
# [B] DECODED LAYER — payload after RTP decode, on /rtp/* topics
# ───────────────────────────────────────────────────────────────
if [ "${DO_DECODED}" = "1" ]; then
  log ""
  log ""
  log "[B] Decoded layer — sample payload from /rtp/* topics"
  log "================================================================"

  sample() {
    local topic="$1" filter="${2:-}" noarr="${3:-}"
    log ""
    log "▶ ${topic}"
    log "  ─────────────────────────────"
    local raw
    if [ -n "${noarr}" ]; then
      raw=$(timeout 5 rostopic echo -n 1 --noarr "${topic}" 2>/dev/null)
    else
      raw=$(timeout 5 rostopic echo -n 1 "${topic}" 2>/dev/null)
    fi
    if [ -z "${raw}" ]; then
      log "  (no data within 5s)"
      return
    fi
    if [ -n "${filter}" ]; then
      echo "${raw}" | grep -E "${filter}" \
        | while IFS= read -r line; do log "  ${line}"; done
    else
      echo "${raw}" | while IFS= read -r line; do log "  ${line}"; done
    fi
  }

  # 純數值類：完整印
  sample "${TOPIC[imu]}"     'orientation:|angular_velocity:|linear_acceleration:|x:|y:|z:|w:'
  sample "${TOPIC[gps_fix]}" 'latitude|longitude|altitude|status'
  sample "${TOPIC[gps_vel]}" 'twist:|linear:|angular:|x:|y:|z:'
  sample "${TOPIC[gps_sat]}" 'data:'
  sample "${TOPIC[pose]}"    'position:|orientation:|x:|y:|z:|w:|frame_id'
  sample "${TOPIC[odom]}"    'position:|orientation:|linear:|angular:|x:|y:|z:|w:|frame_id'

  # 影像 / 點雲：只看 header + metadata
  sample "${TOPIC[rgb]}"         'frame_id|height|width|encoding|step|is_bigendian' noarr
  sample "${TOPIC[depth]}"       'frame_id|height|width|encoding|step'              noarr
  sample "${TOPIC[camera_info]}" 'frame_id|height|width|distortion_model|K:|P:'     noarr
  sample "${TOPIC[pointcloud]}"  'frame_id|height|width|point_step|row_step|is_dense|name:' noarr
fi

log ""
log "=============================================="
log " [A] = RTP receiver 端真正收到的 UDP/RTP 封包"
log " [B] = decode 後 publish 到 ROS 的實際資料"
log " 兩者皆有數字 = 從 socket → decode → publish 全鏈路 OK"
[ -n "${OUT}" ] && log " 已存檔：${OUT}"
log "=============================================="
