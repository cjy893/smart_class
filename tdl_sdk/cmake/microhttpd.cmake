# libmicrohttpd — lightweight HTTP server
# Follows the same FetchContent pattern as thirdparty.cmake.
# Requires ARCHITECTURE to be set (by thirdparty.cmake, included before this file).
# Place the pre-built tarball at:
#   ${TOP_DIR}/oss/oss_release_tarball/${ARCHITECTURE}/libmicrohttpd.tar.gz
# Tarball structure:
#   include/microhttpd.h
#   lib/libmicrohttpd.so ...

include(FetchContent)

if (IS_LOCAL)
  set(MICROHTTPD_URL ${3RD_PARTY_URL_PREFIX}${ARCHITECTURE}/libmicrohttpd.tar.gz)
else()
  set(MICROHTTPD_URL ${TOP_DIR}/oss/oss_release_tarball/${ARCHITECTURE}/libmicrohttpd.tar.gz)
endif()

if(NOT IS_DIRECTORY "${BUILD_DOWNLOAD_DIR}/libmicrohttpd-src")
  FetchContent_Declare(
    libmicrohttpd
    URL ${MICROHTTPD_URL}
  )
  FetchContent_MakeAvailable(libmicrohttpd)
  message(STATUS "libmicrohttpd downloaded to ${libmicrohttpd_SOURCE_DIR}")
endif()

set(MICROHTTPD_INCLUDE_DIR ${BUILD_DOWNLOAD_DIR}/libmicrohttpd-src/include)
set(MICROHTTPD_LIBRARY    ${BUILD_DOWNLOAD_DIR}/libmicrohttpd-src/lib/libmicrohttpd.so)
set(MICROHTTPD_FOUND ON)

include_directories(${MICROHTTPD_INCLUDE_DIR})
link_directories(${BUILD_DOWNLOAD_DIR}/libmicrohttpd-src/lib)

install(DIRECTORY ${BUILD_DOWNLOAD_DIR}/libmicrohttpd-src/lib/
        DESTINATION lib
        FILES_MATCHING PATTERN "*.so*")
