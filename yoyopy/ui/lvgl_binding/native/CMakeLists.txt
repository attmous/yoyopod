cmake_minimum_required(VERSION 3.16)
project(yoyopy_lvgl_binding C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(LVGL_SOURCE_DIR "" CACHE PATH "Path to a checked-out LVGL source tree")

if(NOT LVGL_SOURCE_DIR)
  message(FATAL_ERROR "LVGL_SOURCE_DIR must point to an LVGL checkout")
endif()

set(LV_BUILD_EXAMPLES OFF CACHE BOOL "Disable LVGL examples" FORCE)
set(LV_BUILD_DEMOS OFF CACHE BOOL "Disable LVGL demos" FORCE)

add_subdirectory(${LVGL_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}/lvgl)

if(TARGET lvgl)
  target_include_directories(lvgl PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
  target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)
endif()

add_library(yoyopy_lvgl_shim SHARED lvgl_shim.c)
target_include_directories(
  yoyopy_lvgl_shim
  PRIVATE
    ${LVGL_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
)
target_compile_definitions(yoyopy_lvgl_shim PRIVATE LV_CONF_INCLUDE_SIMPLE)
target_link_libraries(yoyopy_lvgl_shim PRIVATE lvgl m)

set_target_properties(
  yoyopy_lvgl_shim
  PROPERTIES
    OUTPUT_NAME "yoyopy_lvgl_shim"
)
