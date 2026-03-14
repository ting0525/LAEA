cmake_minimum_required(VERSION 3.16)
project(rtp_gazebo)

option(ENABLE_SIP "Enable SIP signaling via PJSIP" OFF)

if(ENABLE_SIP)
  add_definitions(-DENABLE_SIP)
  # 這裡放你原本的 PJSIP include_dir / link_libraries
  # include_directories(/path/to/pjproject/include)
  # target_link_libraries(RTPSender pjsua2 pjsua pj ...)
  # target_link_libraries(RTPReceiver pjsua2 pjsua pj ...)
endif()


# ==============================
# Compiler / Linker fundamentals
# ==============================
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# pjproject static libs are NOT PIE/PIC -> executables MUST be non-PIE
set(CMAKE_POSITION_INDEPENDENT_CODE OFF)
add_link_options(-no-pie)
add_link_options(-Wl,--no-as-needed)

# ==============================
# Paths
# ==============================
set(RTPDevice_DIR "/home/tim/laea/src/LAEA/rtp")
set(OTHER_PLUGIN_DIR "/home/tim/laea/src/LAEA/3rd")

# ==============================
# Catkin / ROS
# ==============================
find_package(catkin REQUIRED COMPONENTS
  roscpp
  rospy
  std_msgs
  visualization_msgs
  cv_bridge
  message_filters
  sensor_msgs
  quadrotor_msgs
  nav_msgs
  geometry_msgs
)

# ==============================
# Third-party
# ==============================
find_package(Boost REQUIRED)
find_package(OpenCV REQUIRED)
find_package(PCL REQUIRED)
find_package(gazebo REQUIRED)
find_package(OpenSSL REQUIRED)
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

# ==============================
# PJPROJECT (static)
# ==============================
set(PKG_CONFIG_USE_STATIC_LIBS ON)
pkg_check_modules(PJPROJECT REQUIRED libpjproject)

# ==============================
# Catkin package
# ==============================
catkin_package(
  INCLUDE_DIRS include
  CATKIN_DEPENDS roscpp std_msgs cv_bridge message_filters sensor_msgs
)

# ==============================
# Includes
# ==============================
include_directories(
  include
  ${catkin_INCLUDE_DIRS}
  ${Boost_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
  ${PCL_INCLUDE_DIRS}
  ${GAZEBO_INCLUDE_DIRS}

  ${RTPDevice_DIR}/include
  ${RTPDevice_DIR}/Codec/include
  ${OTHER_PLUGIN_DIR}/Zdepth/include
  ${OTHER_PLUGIN_DIR}/Zdepth/zstd/include
  ${OTHER_PLUGIN_DIR}/uvgRTP/include

  ${PJPROJECT_INCLUDE_DIRS}
)

link_directories(${PJPROJECT_LIBRARY_DIRS})
add_definitions(${PJPROJECT_CFLAGS_OTHER})

# ==============================
# Libraries
# ==============================
set(RTP_STATIC_LIB "${CATKIN_DEVEL_PREFIX}/lib/librtp.a")

set(COMMON_LIBS
  ${catkin_LIBRARIES}
  ${Boost_LIBRARIES}
  ${OpenCV_LIBRARIES}
  ${PCL_LIBRARIES}
  ${GAZEBO_LIBRARIES}

  ${RTP_STATIC_LIB}
  ${OTHER_PLUGIN_DIR}/uvgRTP/build/libuvgrtp.a
  ${OTHER_PLUGIN_DIR}/Zdepth/libzdepth.a
  ${OTHER_PLUGIN_DIR}/Zdepth/zstd/libzstd.a
  PkgConfig::LIBAV
)

# Based on: pkg-config --static --libs libpjproject
set(PJPROJECT_PRIVATE_LIBS
  # codec / third-party from pjproject
  srtp-x86_64-unknown-linux-gnu
  resample-x86_64-unknown-linux-gnu
  gsmcodec-x86_64-unknown-linux-gnu
  speex-x86_64-unknown-linux-gnu
  ilbccodec-x86_64-unknown-linux-gnu
  g7221codec-x86_64-unknown-linux-gnu
  webrtc-x86_64-unknown-linux-gnu

  # openssl
  ssl
  crypto

  # system
  uuid
  pthread
  m
  rt

  # ---- C++ runtime / ABI (MUST be last) ----
  stdc++
  supc++
  gcc_s
  unwind
)

# ==============================
# Targets
# ==============================
add_executable(RTPSender src/RTPSender.cpp)
add_executable(RTPReceiver src/RTPReceiver.cpp)
add_executable(Synchronizer src/Synchronizer.cpp)

add_dependencies(RTPSender rtp)
add_dependencies(RTPReceiver rtp)
add_dependencies(Synchronizer ${catkin_EXPORTED_TARGETS})

target_link_libraries(RTPSender
  ${COMMON_LIBS}
  -Wl,--start-group
  ${PJPROJECT_LIBRARIES}
  -Wl,--end-group
  ${PJPROJECT_PRIVATE_LIBS}
)

target_link_libraries(RTPReceiver
  ${COMMON_LIBS}
  -Wl,--start-group
  ${PJPROJECT_LIBRARIES}
  -Wl,--end-group
  ${PJPROJECT_PRIVATE_LIBS}
)

target_link_libraries(Synchronizer
  ${catkin_LIBRARIES}
)
