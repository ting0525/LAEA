cmake_minimum_required(VERSION 3.27)

project(OtherTool)
# Change to the Airsim directory
set(AIRSIM_ROOT $ENV{HOME}/Airsim)
add_subdirectory("${AIRSIM_ROOT}/cmake/rpclib_wrapper" rpclib_wrapper)
add_subdirectory("${AIRSIM_ROOT}/cmake/AirLib" AirLib)
add_subdirectory("${AIRSIM_ROOT}/cmake/MavLinkCom" MavLinkCom)

set(3rd_lib_DIR "./")
cmake_path(GET CMAKE_CURRENT_SOURCE_DIR PARENT_PATH 3rd_lib_DIR)
include(CMakePrintHelpers)
cmake_print_variables(3rd_lib_DIR)

set(CMAKE_CXX_STANDARD 17)
#set(CMAKE_CXX_FLAGS "-Wall -Wextra -Wpedantic -Wstrict-null-sentinel -Wno-unused")
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

# Zdepth Libs
include_directories(${3rd_lib_DIR}/Zdepth/include)
include_directories(${3rd_lib_DIR}/Zdepth/zstd/include)

find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

find_package(CURL REQUIRED)
include_directories($(CURL_INCLUDE_DIRS))

add_library(OtherTool STATIC)
target_sources(
    OtherTool PRIVATE 
    "src/AirsimClient.cpp"
)

target_include_directories(OtherTool
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src
)


