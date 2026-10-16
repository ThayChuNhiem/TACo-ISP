cmake_minimum_required(VERSION 3.16)
project(taco_ps_software CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -Wall -Wextra -pthread")

# Include directories
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/common
    ${CMAKE_CURRENT_SOURCE_DIR}/controller
)

# Optional HLS drivers directory passed via -DHLS_DRIVERS=<dir>
if(HLS_DRIVERS)
    include_directories(${HLS_DRIVERS})
    add_definitions(-DHAVE_HLS_DRIVERS)
endif()

# Find OpenCV (with pkg-config fallback if OpenCVConfig.cmake is absent)
find_package(OpenCV QUIET)
if(NOT OpenCV_FOUND)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(OpenCV opencv4)
    if(NOT OpenCV_FOUND)
        pkg_check_modules(OpenCV REQUIRED opencv)
    endif()
endif()
include_directories(${OpenCV_INCLUDE_DIRS})

# Controller Standalone Reference (No Xilinx dependencies)
add_executable(ctrl_ref controller/ctrl_ref.cpp)
target_link_libraries(ctrl_ref pthread)

# Target for P-TACo Proposed Application
# Linking VART, XIR, XRT (available on KV260 Petalinux/Ubuntu)
find_library(VART_RUNNER_LIB NAMES vart-runner vart-runner.so.3 vart-runner.so.3.0.0 HINTS /usr/lib /usr/lib64 /usr/local/lib)
find_library(VART_UTIL_LIB NAMES vart-util vart-util.so.3 vart-util.so.3.0.0 HINTS /usr/lib /usr/lib64 /usr/local/lib)
find_library(XIR_LIB NAMES xir xir.so.3 xir.so.3.0.0 HINTS /usr/lib /usr/lib64 /usr/local/lib)
find_library(XRT_CORE_LIB NAMES xrt_coreutil xrt_coreutil.so.2 HINTS /usr/lib /usr/lib64 /usr/local/lib)

set(VART_LIBS ${VART_RUNNER_LIB} ${XIR_LIB} ${XRT_CORE_LIB})
if(VART_UTIL_LIB)
    list(APPEND VART_LIBS ${VART_UTIL_LIB})
endif()

if(VART_RUNNER_LIB AND XIR_LIB)
    add_definitions(-DHAVE_VART=1)
    add_executable(taco_app app/taco_app.cpp)
    target_link_libraries(taco_app ${VART_LIBS} ${OpenCV_LIBS} pthread)

    add_executable(baseline_ba app/baseline_ba.cpp)
    target_link_libraries(baseline_ba ${VART_LIBS} ${OpenCV_LIBS} pthread)

    add_executable(baseline_ba3 app/baseline_ba3.cpp)
    target_link_libraries(baseline_ba3 ${VART_LIBS} ${OpenCV_LIBS} pthread)
else()
    message(WARNING "VART/XIR libraries not found on host. Building baseline_ba and ctrl_ref in simulation/host mode.")
    add_executable(baseline_ba app/baseline_ba.cpp)
    target_link_libraries(baseline_ba ${OpenCV_LIBS} pthread)
endif()
