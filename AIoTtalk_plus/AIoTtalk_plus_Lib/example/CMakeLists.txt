cmake_minimum_required(VERSION 3.27)

project(example)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

set (RTPDevice_DIR "./")
cmake_path(GET CMAKE_CURRENT_SOURCE_DIR PARENT_PATH RTPDevice_DIR)
include(CMakePrintHelpers)

aux_source_directory(./src SRC)
include_directories(include)

# Airsim path
set(AIRSIM_ROOT $ENV{HOME}/UAV/AirSim)
set(CMAKE_CXX_STANDARD 17)
add_subdirectory("${AIRSIM_ROOT}/cmake/rpclib_wrapper" rpclib_wrapper)
add_subdirectory("${AIRSIM_ROOT}/cmake/AirLib" AirLib)
add_subdirectory("${AIRSIM_ROOT}/cmake/MavLinkCom" MavLinkCom)

set(CMAKE_CXX_STANDARD 17)
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

include_directories(${RTPDevice_DIR}/RTP/include)
include_directories(${RTPDevice_DIR}/RTP/Codec/include)

include_directories(${RTPDevice_DIR}/3rd/Zdepth/include)
include_directories(${RTPDevice_DIR}/3rd/Zdepth/zstd/include)



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

add_library(AirsimClient STATIC ./src/AirsimClient.cpp)

set(SENDER_EXE sender)
set(RECEIVER_EXE receiver)

add_executable(${SENDER_EXE} ./src/sender.cpp)
add_executable(${RECEIVER_EXE} ./src/receiver.cpp)

target_link_libraries(${SENDER_EXE} ${RTPDevice_DIR}/RTP/build/libRTP.a)
target_link_libraries(${SENDER_EXE} ${RTPDevice_DIR}/3rd/uvgRTP/build/libuvgrtp.a)
target_link_libraries(${SENDER_EXE} ${RTPDevice_DIR}/3rd/Zdepth/libzdepth.a)
target_link_libraries(${SENDER_EXE} ${RTPDevice_DIR}/3rd/Zdepth/zstd/libzstd.a)
target_link_libraries(${SENDER_EXE} PkgConfig::LIBAV)
target_link_libraries(${SENDER_EXE} -lpthread)
target_link_libraries(${SENDER_EXE} ${OpenCV_LIBRARIES})
target_link_libraries(AirsimClient AirLib)
target_link_libraries(${SENDER_EXE} AirsimClient)
target_link_libraries(${SENDER_EXE} AirLib ${PCL_LIBS})
target_link_libraries(${SENDER_EXE} ${PCL_LIBRARIES})
target_link_libraries(${SENDER_EXE} ${catkin_LIBRARIES})


target_link_libraries(${RECEIVER_EXE} ${RTPDevice_DIR}/RTP/build/libRTP.a)
target_link_libraries(${RECEIVER_EXE} ${RTPDevice_DIR}/3rd/uvgRTP/build/libuvgrtp.a)
target_link_libraries(${RECEIVER_EXE} ${RTPDevice_DIR}/3rd/Zdepth/libzdepth.a)
target_link_libraries(${RECEIVER_EXE} ${RTPDevice_DIR}/3rd/Zdepth/zstd/libzstd.a)
target_link_libraries(${RECEIVER_EXE} PkgConfig::LIBAV)
target_link_libraries(${RECEIVER_EXE} -lpthread)
target_link_libraries(${RECEIVER_EXE} ${OpenCV_LIBRARIES})
target_link_libraries(${RECEIVER_EXE} ${PCL_LIBRARIES})
