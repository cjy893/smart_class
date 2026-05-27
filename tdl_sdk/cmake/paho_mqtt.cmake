# paho.mqtt.c — MQTT client library
# Follows the same FetchContent pattern as thirdparty.cmake.
# Requires ARCHITECTURE to be set (by thirdparty.cmake, included before this file).
# Place the pre-built tarball at:
#   ${TOP_DIR}/oss/oss_release_tarball/${ARCHITECTURE}/paho_mqtt.tar.gz
# Tarball structure:
#   include/MQTTAsync.h ...
#   lib/libpaho-mqtt3as.so ...

include(FetchContent)

if (IS_LOCAL)
  set(PAHO_MQTT_URL ${3RD_PARTY_URL_PREFIX}${ARCHITECTURE}/paho_mqtt.tar.gz)
else()
  set(PAHO_MQTT_URL ${TOP_DIR}/oss/oss_release_tarball/${ARCHITECTURE}/paho_mqtt.tar.gz)
endif()

if(NOT IS_DIRECTORY "${BUILD_DOWNLOAD_DIR}/paho_mqtt-src")
  FetchContent_Declare(
    paho_mqtt
    URL ${PAHO_MQTT_URL}
  )
  FetchContent_MakeAvailable(paho_mqtt)
  message(STATUS "paho.mqtt.c downloaded to ${paho_mqtt_SOURCE_DIR}")
endif()

set(PAHO_MQTT_INCLUDE_DIR ${BUILD_DOWNLOAD_DIR}/paho_mqtt-src/include)
set(PAHO_MQTT_LIBRARY    ${BUILD_DOWNLOAD_DIR}/paho_mqtt-src/lib/libpaho-mqtt3as.so)
set(PAHO_MQTT_FOUND ON)

include_directories(${PAHO_MQTT_INCLUDE_DIR})
link_directories(${BUILD_DOWNLOAD_DIR}/paho_mqtt-src/lib)

install(DIRECTORY ${BUILD_DOWNLOAD_DIR}/paho_mqtt-src/lib/
        DESTINATION lib
        FILES_MATCHING PATTERN "*.so*")
