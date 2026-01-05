cmake_minimum_required(VERSION 3.10)
project(rtp)

# ========= Global compile settings =========
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ========= Paths =========
# RTPDevice_DIR 指向 LAEA 根目錄（你的原始設定）
set(RTPDevice_DIR "/home/tim/laea/src/LAEA")

# ========= Dependencies =========
find_package(catkin REQUIRED COMPONENTS
  roscpp
  rospy
  std_msgs
  visualization_msgs
  quadrotor_msgs
  cv_bridge
  message_filters
  sensor_msgs
  nav_msgs
  geometry_msgs
)

find_package(PCL REQUIRED)
message(STATUS "Using PCL version: ${PCL_VERSION}")

find_package(OpenCV REQUIRED)

find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET
  libavdevice
  libavfilter
  libavformat
  libavcodec
  libswresample
  libswscale
  libavutil
)

# ========= Public include dirs (export contract) =========
set(RTP_PUBLIC_INCLUDE_DIRS
  ${RTPDevice_DIR}/rtp/include
  ${RTPDevice_DIR}/rtp/Codec/include
)

# 這些是 rtp 內部需要但不一定要 export 給下游的 include（保守做法：先不 export）
set(RTP_PRIVATE_INCLUDE_DIRS
  ${RTPDevice_DIR}/rtp/src
  ${RTPDevice_DIR}/rtp/Codec/src
  ${RTPDevice_DIR}/3rd/uvgRTP/include
  ${RTPDevice_DIR}/3rd/uvgRTP/include/uvgRTP
  ${RTPDevice_DIR}/3rd/Zdepth/include
  ${RTPDevice_DIR}/3rd/Zdepth/zstd/include
)

# ========= Library target =========
add_library(rtp STATIC
  "${RTPDevice_DIR}/rtp/Codec/src/VideoCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/DepthImageCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/PointCloudCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/CameraInfoCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/MarkerCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/CommandCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/OdomCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/PoseCodec.cpp"
  "${RTPDevice_DIR}/rtp/Codec/src/Data.cpp"
  "${RTPDevice_DIR}/rtp/src/Stream.cpp"
  "${RTPDevice_DIR}/rtp/src/RTPSession.cpp"
)

target_include_directories(rtp
  PUBLIC
    ${RTP_PUBLIC_INCLUDE_DIRS}
    ${catkin_INCLUDE_DIRS}
    ${PCL_INCLUDE_DIRS}
    ${OpenCV_INCLUDE_DIRS}
  PRIVATE
    ${RTP_PRIVATE_INCLUDE_DIRS}
)

# 注意：rtp 是 STATIC library，本身不會被「連結成執行檔」
# 但把相依庫掛上去，能讓下游 target_link_libraries(... rtp) 時自動帶出必要相依（更乾淨）
target_link_libraries(rtp
  PUBLIC
    ${catkin_LIBRARIES}
    ${PCL_LIBRARIES}
    ${OpenCV_LIBS}
    PkgConfig::LIBAV
)

# ========= catkin export =========
# 讓下游套件只要 find_package(catkin COMPONENTS rtp) 就能拿到 include/lib
catkin_package(
  INCLUDE_DIRS ${RTP_PUBLIC_INCLUDE_DIRS}
  LIBRARIES rtp
  CATKIN_DEPENDS roscpp rospy std_msgs visualization_msgs quadrotor_msgs cv_bridge message_filters sensor_msgs nav_msgs geometry_msgs
  DEPENDS PCL OpenCV
)
