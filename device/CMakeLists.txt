# Edge Compute Device — Smart Classroom Device-Side Application
# Builds inside TDL SDK sample framework.
# Usage: BUILD_OPTION=sample cmake ... && make

cmake_minimum_required(VERSION 3.16.3)
project(edge_compute_device)

# ---- Include paths ----
# TDL SDK headers (relative to sample_video conventions).
set(DEVICE_INC
    ${CMAKE_CURRENT_SOURCE_DIR}/../../include
    ${CMAKE_CURRENT_SOURCE_DIR}/../../include/cvi_tdl_app
    ${CMAKE_CURRENT_SOURCE_DIR}/../../modules/core
    ${CMAKE_CURRENT_SOURCE_DIR}/../../modules/core/core
    ${CMAKE_CURRENT_SOURCE_DIR}/../../modules/core/utils
    ${CMAKE_CURRENT_SOURCE_DIR}/../../modules/lib/cvi_kit
    # Middleware SDK headers (from parent scope).
    ${MIDDLEWARE_SDK_ROOT}/include
    ${MIDDLEWARE_SDK_ROOT}/sample/common
    ${MIDDLEWARE_SDK_ROOT}/component/isp/common
    # Project internal headers.
    ${CMAKE_CURRENT_SOURCE_DIR}
    # Sample utility headers.
    ${CMAKE_CURRENT_SOURCE_DIR}/../..
    ${CMAKE_CURRENT_SOURCE_DIR}/../../sample_video
    # RTSP header (needed by middleware_utils.h even when not using RTSP).
    ${CVI_RTSP_INCLUDE}
)

include_directories(${DEVICE_INC})

# ---- Source files ----
set(DEVICE_SOURCES
    edge_compute_device.cpp
    app.cpp
    config.cpp
    task_queue.cpp
    inference_engine.cpp
    mqtt_client.cpp
    http_server.cpp
    gpio_handler.cpp
    mmf_pipeline.cpp
    offline_cache.cpp
    heartbeat.cpp
)

# Middleware utility sources (shared with sample_video samples).
set(MW_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/../../sample_video/middleware_utils.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../sample_video/sample_utils.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_platform.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_sys.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_vi.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_isp.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_vpss.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_venc.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_bin.c
    ${MIDDLEWARE_SDK_ROOT}/sample/common/sample_common_peripheral.c
)

# ---- Link directories ----
link_directories(${CMAKE_INSTALL_PREFIX}/lib)

# ---- Build executable ----
add_executable(${PROJECT_NAME} ${DEVICE_SOURCES} ${MW_SOURCES})

# ---- Platform-specific middleware libraries ----
# Mirrors the library setup from sample_video/CMakeLists.txt.
if(${CVI_PLATFORM} STREQUAL "SOPHON")
    set(MW_LIBS
        ${MIDDLEWARE_SDK_ROOT}/lib/libsys.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvi.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvpss.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvenc.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvdec.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvo.so
        ${MIDDLEWARE_SDK_ROOT}/lib/librgn.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libgdc.so
        ${MIDDLEWARE_SDK_ROOT}/lib/3rd/libini.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libsns_full.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libisp.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libawb.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libae.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libaf.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libisp_algo.so
    )
elseif(${CONFIG_DUAL_OS} STREQUAL "ON")
    set(MW_LIBS
        ${MIDDLEWARE_SDK_ROOT}/lib/libsys.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvi.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvo.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvpss.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libgdc.so
        ${MIDDLEWARE_SDK_ROOT}/lib/librgn.so
        ${MIDDLEWARE_SDK_ROOT}/lib/3rd/libini.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libmsg.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libcvilink.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libsys.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvenc.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvdec.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin_isp.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libisp.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libae.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libawb.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libaf.so
        ${MLIR_SDK_ROOT}/lib/libz.so
    )
else()
    set(MW_LIBS
        ${MIDDLEWARE_SDK_ROOT}/lib/libsys.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvi.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvo.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvpss.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libgdc.so
        ${MIDDLEWARE_SDK_ROOT}/lib/librgn.so
        ${MIDDLEWARE_SDK_ROOT}/lib/3rd/libini.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libsns_full.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libsample.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libisp.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvdec.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libvenc.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libawb.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libae.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libaf.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin_isp.so
        ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin.so
        ${MLIR_SDK_ROOT}/lib/libz.so
    )
    if("${MW_VER}" STREQUAL "v2")
        if(${CVI_PLATFORM} STRLESS "SOPHON")
            set(MW_LIBS
                ${MIDDLEWARE_SDK_ROOT}/lib/libsys.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libvi.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libvo.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libvpss.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libgdc.so
                ${MIDDLEWARE_SDK_ROOT}/lib/librgn.so
                ${MIDDLEWARE_SDK_ROOT}/lib/3rd/libini.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libsns_full.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libsample.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libisp.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libvdec.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libvenc.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libawb.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libae.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libaf.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin_isp.so
                ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_bin.so
                ${MLIR_SDK_ROOT}/lib/libz.so
            )
        endif()
        set(MW_LIBS ${MW_LIBS} ${MIDDLEWARE_SDK_ROOT}/lib/libmisc.so)
    else()
        set(MW_LIBS ${MW_LIBS} ${MIDDLEWARE_SDK_ROOT}/lib/libcvi_vcodec.so)
    endif()
    if (NOT "${CVI_PLATFORM}" STREQUAL "CV183X")
        set(MW_LIBS ${MW_LIBS} ${MIDDLEWARE_SDK_ROOT}/lib/libisp_algo.so)
    endif()
endif()

# ---- Link ----
# Note: paho.mqtt.c and libmicrohttpd are optional.
# They are enabled when the corresponding cmake modules find them.
# HAS_PAHO_MQTT / HAS_MICROHTTPD are set automatically by cmake/paho_mqtt.cmake and cmake/microhttpd.cmake.

set(EXTRA_LIBS "")

if(PAHO_MQTT_FOUND)
    set(EXTRA_LIBS ${EXTRA_LIBS} paho-mqtt3a)
    message(STATUS "edge_compute_device: MQTT enabled")
else()
    message(FATAL_ERROR "paho.mqtt.c not found. Set -DPAHO_MQTT_URL=<url> or -DPAHO_MQTT_SOURCE_DIR=<path>")
endif()

if(MICROHTTPD_FOUND)
    set(EXTRA_LIBS ${EXTRA_LIBS} microhttpd)
    message(STATUS "edge_compute_device: HTTP server enabled")
else()
    message(FATAL_ERROR "libmicrohttpd not found. Set -DMICROHTTPD_URL=<url> or -DMICROHTTPD_SOURCE_DIR=<path>")
endif()

target_link_libraries(${PROJECT_NAME}
    cvi_tdl
    pthread
    atomic
    ${EXTRA_LIBS}
    ${MW_LIBS}
    ${MLIR_LIBS}
    ${OPENCV_LIBS}
    ${IVE_LIBS}
    ${CVI_RTSP_LIBPATH}
)

# ---- Install ----
install(TARGETS ${PROJECT_NAME} DESTINATION bin)
