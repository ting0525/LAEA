cmake_minimum_required(VERSION 3.27)
project(RTP)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

set (MODULE_NAME RTP)
set (AIoTtalk_plus_DIR "./")

find_package(Python 3.8 COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 REQUIRED)

cmake_path(GET CMAKE_CURRENT_SOURCE_DIR PARENT_PATH AIoTtalk_plus_DIR)
include(CMakePrintHelpers)
cmake_print_variables(AIoTtalk_plus_DIR)

add_subdirectory(${AIoTtalk_plus_DIR}/3rd/cvnp cvnp)
include_directories(${AIoTtalk_plus_DIR}/3rd/uvgRTP/include/)

find_package(PCL REQUIRED)
include_directories(${PCL_INCLUDE_DIRS})
include_directories(${AIoTtalk_plus_DIR}/3rd/Zdepth/include)
include_directories(${AIoTtalk_plus_DIR}/3rd/Zdepth/zstd/include)
include_directories(${AIoTtalk_plus_DIR}/3rd/OtherTool/include)

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
include_directories(${LIBAV_INCLUDE_DIRS})

find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

add_library(RTP_static STATIC)
target_sources(
    RTP_static PRIVATE 
    "Codec/src/VideoCodec.cpp"
    "Codec/src/DepthImageCodec.cpp"
    "Codec/src/PointCloudCodec.cpp"
    "Codec/src/DataWrapper.cpp"
    "src/RTPSession.cpp"
    "src/uvgrtp_callback.cpp"
    "src/Stream.cpp"
)

target_include_directories(RTP_static
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/Codec/include
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/Codec/src
)

target_link_libraries(RTP_static ${AIoTtalk_plus_DIR}/3rd/uvgRTP/build/libuvgrtp.a)
target_link_libraries(RTP_static ${AIoTtalk_plus_DIR}/3rd/Zdepth/libzdepth.a)
target_link_libraries(RTP_static ${AIoTtalk_plus_DIR}/3rd/Zdepth/zstd/libzstd.a)
target_link_libraries(RTP_static PkgConfig::LIBAV)
target_link_libraries(RTP_static -lpthread)
target_link_libraries(RTP_static ${PCL_LIBRARIES})
target_link_libraries(RTP_static ${OpenCV_LIBRARIES})

add_library(RTP SHARED)
target_sources(
    RTP PRIVATE 
    "Codec/src/VideoCodec.cpp"
    "Codec/src/DepthImageCodec.cpp"
    "Codec/src/PointCloudCodec.cpp"
    "Codec/src/DataWrapper.cpp"
    
    "src/RTPSession.cpp"
    "src/uvgrtp_callback.cpp"
    "src/Stream.cpp"
)

target_include_directories(RTP
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/Codec/include
PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/Codec/src
)

target_link_libraries(RTP ${AIoTtalk_plus_DIR}/3rd/uvgRTP/build2/libuvgrtp.a)
target_link_libraries(RTP ${AIoTtalk_plus_DIR}/3rd/Zdepth/libzdepth.a)
target_link_libraries(RTP ${AIoTtalk_plus_DIR}/3rd/Zdepth/zstd/libzstd.a)
target_link_libraries(RTP PkgConfig::LIBAV)
target_link_libraries(RTP -lpthread)
target_link_libraries(RTP ${PCL_LIBRARIES})
target_link_libraries(RTP ${OpenCV_LIBRARIES})
#target_link_libraries(RTP cvnp)


pybind11_add_module(MyTool_pybind11 SHARED ./pybind11/pybind11.cpp)
target_include_directories(MyTool_pybind11 PUBLIC ${LIBAV_INCLUDE_DIRS})

target_link_libraries(MyTool_pybind11 PRIVATE RTP)
target_link_libraries(MyTool_pybind11 PRIVATE ${PYTHON_LIBRARIES})
target_link_libraries(MyTool_pybind11 PRIVATE cvnp)




