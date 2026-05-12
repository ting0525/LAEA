cmake_minimum_required(VERSION 3.27)
project(monitor_device)

set(AIRSIM_ROOT $ENV{HOME}/Airsim)
add_subdirectory("${AIRSIM_ROOT}/cmake/rpclib_wrapper" rpclib_wrapper)
add_subdirectory("${AIRSIM_ROOT}/cmake/AirLib" AirLib)
add_subdirectory("${AIRSIM_ROOT}/cmake/MavLinkCom" MavLinkCom)

set(AIoTtalk_plus_Lib_DIR $ENV{HOME}/handover/AIoTtalk/AIoTtalk_plus_Lib)
include(CMakePrintHelpers)
cmake_print_variables(AIoTtalk_plus_Lib_DIR)
include_directories(${AIoTtalk_plus_Lib_DIR}/3rd/uvgRTP/include)
include_directories(${AIoTtalk_plus_Lib_DIR}/3rd/Zdepth/include)
include_directories(${AIoTtalk_plus_Lib_DIR}/RTP/Codec/include)
include_directories(${AIoTtalk_plus_Lib_DIR}/RTP/include)
include_directories(${AIoTtalk_plus_Lib_DIR}/3rd/OtherTool/include)
include_directories(${AIoTtalk_plus_Lib_DIR}/3rd/uvgRTP/include)

set(EXE_NAME1 loam_aua)
set(EXE_NAME2 rtabmap_aua)

aux_source_directory(./src SRC)
include_directories(include)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "-g -Wall -Wextra -Wpedantic -Wstrict-null-sentinel -Wno-unused")
set(CXX_EXP_LIB "-nostdinc++ -I/usr/include/c++/8 -I/usr/include/x86_64-linux-gnu/c++/8 -nodefaultlibs 
-l/usr/lib/x86_64-linux-gnu/libc++.so -l/usr/lib/x86_64-linux-gnu/libc++abi.so
-lm -lc -lgcc_s -lgcc  
-lstdc++fs -fmax-errors=10")
set(RPC_LIB_INCLUDES " ${AIRSIM_ROOT}/external/rpclib/rpclib-2.3.0/include")
set(RPC_LIB rpc) # name of .a file with lib prefix
message(STATUS "found RPC_LIB_INCLUDES=${RPC_LIB_INCLUDES}")

find_package(Boost REQUIRED)
find_package(OpenCV REQUIRED)
find_package(PCL REQUIRED)

include_directories(
  include
  ${AIRSIM_ROOT}/AirLib/deps/eigen3
  ${AIRSIM_ROOT}/AirLib/include
  ${RPC_LIB_INCLUDES}
  ${AIRSIM_ROOT}/MavLinkCom/include
  ${AIRSIM_ROOT}/MavLinkCom/common_utils
  ${OpenCV_INCLUDE_DIRS}
  ${Boost_INCLUDE_DIRS}
  ${PCL_INCLUDE_DIRS}
)

# ROS libs
find_package(catkin REQUIRED COMPONENTS
    cv_bridge
    image_transport
    mavros_msgs
    message_generation
    nav_msgs
    # nodelet
    roscpp
    rospy
    sensor_msgs
    std_msgs
    geographic_msgs
    geometry_msgs
    std_srvs
    tf2
    tf2_ros
    tf2_sensor_msgs
    tf2_geometry_msgs
)
include_directories(${catkin_INCLUDE_DIRS})

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

find_package(PCL REQUIRED)
include_directories(${PCL_INCLUDE_DIRS})

find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

#message(STATUS "PATH: ${AIoTtalk_plus_Lib_DIR}")
add_executable(${EXE_NAME1} ./src/loam_aua.cpp)
add_executable(${EXE_NAME2} ./src/rtabmap_aua.cpp)

target_link_libraries(${EXE_NAME1} ${AIoTtalk_plus_Lib_DIR}/RTP/build/libRTP_static.a)
target_link_libraries(${EXE_NAME1} ${AIoTtalk_plus_Lib_DIR}/3rd/OtherTool/build/libOtherTool.a)
target_link_libraries(${EXE_NAME1} ${AIoTtalk_plus_Lib_DIR}/3rd/uvgRTP/build2/libuvgrtp.a)
target_link_libraries(${EXE_NAME1} ${AIoTtalk_plus_Lib_DIR}/3rd/Zdepth/libzdepth.a)
target_link_libraries(${EXE_NAME1} ${AIoTtalk_plus_Lib_DIR}/3rd/Zdepth/zstd/libzstd.a)

target_link_libraries(${EXE_NAME1} PkgConfig::LIBAV)
target_link_libraries(${EXE_NAME1} -lpthread)
target_link_libraries(${EXE_NAME1} ${OpenCV_LIBRARIES})

target_link_libraries(${EXE_NAME1} AirLib ${PCL_LIBS})
target_link_libraries(${EXE_NAME1} ${PCL_LIBRARIES})
target_link_libraries(${EXE_NAME1} ${catkin_LIBRARIES})

target_link_libraries(${EXE_NAME2} ${AIoTtalk_plus_Lib_DIR}/RTP/build/libRTP_static.a)
target_link_libraries(${EXE_NAME2} ${AIoTtalk_plus_Lib_DIR}/3rd/OtherTool/build/libOtherTool.a)
target_link_libraries(${EXE_NAME2} ${AIoTtalk_plus_Lib_DIR}/3rd/uvgRTP/build2/libuvgrtp.a)
target_link_libraries(${EXE_NAME2} ${AIoTtalk_plus_Lib_DIR}/3rd/Zdepth/libzdepth.a)
target_link_libraries(${EXE_NAME2} ${AIoTtalk_plus_Lib_DIR}/3rd/Zdepth/zstd/libzstd.a)

target_link_libraries(${EXE_NAME2} PkgConfig::LIBAV)
target_link_libraries(${EXE_NAME2} -lpthread)
target_link_libraries(${EXE_NAME2} ${OpenCV_LIBRARIES})

target_link_libraries(${EXE_NAME2} AirLib ${PCL_LIBS})
target_link_libraries(${EXE_NAME2} ${PCL_LIBRARIES})
target_link_libraries(${EXE_NAME2} ${catkin_LIBRARIES})
