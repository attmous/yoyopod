cmake_minimum_required(VERSION 3.16)
project(yoyopod_lvgl_binding C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
option(
  YOYOPOD_LVGL_BUILD_SHARED
  "Build upstream LVGL as a shared library"
  ON
)
set(BUILD_SHARED_LIBS ${YOYOPOD_LVGL_BUILD_SHARED} CACHE BOOL "Build shared libraries" FORCE)

set(LVGL_SOURCE_DIR "" CACHE PATH "Path to a checked-out LVGL source tree")

if(NOT LVGL_SOURCE_DIR)
  message(FATAL_ERROR "LVGL_SOURCE_DIR must point to an LVGL checkout")
endif()

# YoYoPod does not use LVGL vector graphics or Lottie, so keep ThorVG off
# even if upstream desktop defaults enable it.
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "Disable LVGL ThorVG integration" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "Disable LVGL examples" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "Disable LVGL demos" FORCE)

add_subdirectory(${LVGL_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}/lvgl)

if(TARGET lvgl)
  target_include_directories(lvgl PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
  target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)
endif()

add_library(yoyopod_lvgl_shim SHARED lvgl_shim.c)
target_include_directories(
  yoyopod_lvgl_shim
  PRIVATE
    ${LVGL_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
)
target_compile_definitions(yoyopod_lvgl_shim PRIVATE LV_CONF_INCLUDE_SIMPLE)
target_link_libraries(yoyopod_lvgl_shim PRIVATE lvgl m)

set_target_properties(
  yoyopod_lvgl_shim
  PROPERTIES
    OUTPUT_NAME "yoyopod_lvgl_shim"
)
