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

# Find OpenCV
find_package(OpenCV REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

# Controller Standalone Reference (No Xilinx dependencies)
add_executable(ctrl_ref controller/ctrl_ref.cpp)

# Target for P-TACo Proposed Application
# Linking VART, XIR, XRT (available on KV260 Petalinux/Ubuntu)
find_library(VART_RUNNER_LIB vart-runner)
find_library(XIR_LIB xir)
find_library(XRT_CORE_LIB xrt_coreutil)

if(VART_RUNNER_LIB AND XIR_LIB)
    add_executable(taco_app app/taco_app.cpp)
    target_link_libraries(taco_app ${VART_RUNNER_LIB} ${XIR_LIB} ${XRT_CORE_LIB} ${OpenCV_LIBS} pthread)

    add_executable(baseline_ba app/baseline_ba.cpp)
    target_link_libraries(baseline_ba ${VART_RUNNER_LIB} ${XIR_LIB} ${XRT_CORE_LIB} ${OpenCV_LIBS} pthread)

    add_executable(baseline_ba3 app/baseline_ba3.cpp)
    target_link_libraries(baseline_ba3 ${VART_RUNNER_LIB} ${XIR_LIB} ${XRT_CORE_LIB} ${OpenCV_LIBS} pthread)
else()
    message(WARNING "VART/XIR libraries not found on host. Only building host tests/references.")
endif()
