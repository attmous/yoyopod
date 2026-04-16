cmake_minimum_required(VERSION 3.16)

project(yoyopod_liblinphone_shim C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_path(
  LINPHONE_INCLUDE_DIR
  NAMES linphone/core.h
  PATHS
    /usr/include
)

find_library(
  LINPHONE_LIBRARY
  NAMES linphone liblinphone
  PATHS
    /usr/lib
    /usr/lib/arm-linux-gnueabihf
    /usr/lib/aarch64-linux-gnu
    /usr/local/lib
)

if(NOT LINPHONE_INCLUDE_DIR)
  message(FATAL_ERROR "Could not find linphone/core.h. Install liblinphone-dev.")
endif()

if(NOT LINPHONE_LIBRARY)
  message(FATAL_ERROR "Could not find liblinphone shared library.")
endif()

add_library(yoyopod_liblinphone_shim SHARED liblinphone_shim.c)

target_include_directories(
  yoyopod_liblinphone_shim
  PRIVATE
    ${LINPHONE_INCLUDE_DIR}
)

target_link_libraries(
  yoyopod_liblinphone_shim
  PRIVATE
    ${LINPHONE_LIBRARY}
    pthread
)

if(UNIX AND NOT APPLE)
  target_link_libraries(yoyopod_liblinphone_shim PRIVATE m)
endif()
