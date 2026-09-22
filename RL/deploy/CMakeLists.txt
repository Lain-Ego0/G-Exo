cmake_minimum_required(VERSION 3.16)

project(gexo_rl_deploy LANGUAGES CXX)

include(CTest)

if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
  set(_gexo_deploy_standalone_default ON)
else()
  set(_gexo_deploy_standalone_default OFF)
endif()
option(GEXO_DEPLOY_BUILD_PROCESS "Build the standalone Deploy process shell"
       ${_gexo_deploy_standalone_default})
option(GEXO_DEPLOY_BUILD_TESTS "Build the Deploy runtime tests"
       ${BUILD_TESTING})

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(ONNXRUNTIME_ROOT "$ENV{ONNXRUNTIME_ROOT}" CACHE PATH
    "Root directory of the ONNX Runtime C/C++ SDK")
if(NOT ONNXRUNTIME_ROOT)
  message(FATAL_ERROR
    "ONNXRUNTIME_ROOT is not set. Pass -DONNXRUNTIME_ROOT=/path/to/onnxruntime "
    "or export ONNXRUNTIME_ROOT before configuring.")
endif()

find_path(ONNXRUNTIME_INCLUDE_DIR
  NAMES onnxruntime_cxx_api.h
  PATHS "${ONNXRUNTIME_ROOT}/include"
  NO_DEFAULT_PATH
  REQUIRED)
find_library(ONNXRUNTIME_LIBRARY
  NAMES onnxruntime
  PATHS "${ONNXRUNTIME_ROOT}/lib" "${ONNXRUNTIME_ROOT}/lib64"
  NO_DEFAULT_PATH
  REQUIRED)

if(NOT TARGET onnxruntime::onnxruntime)
  add_library(onnxruntime::onnxruntime UNKNOWN IMPORTED GLOBAL)
  set_target_properties(onnxruntime::onnxruntime PROPERTIES
    IMPORTED_LOCATION "${ONNXRUNTIME_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${ONNXRUNTIME_INCLUDE_DIR}")
endif()

find_package(jsoncpp CONFIG REQUIRED)

add_library(gexo_deploy STATIC
  src/gexo_deploy.cpp
  src/sha256.cpp)
target_include_directories(gexo_deploy PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>")
target_link_libraries(gexo_deploy PRIVATE
  onnxruntime::onnxruntime
  jsoncpp_lib)
target_compile_options(gexo_deploy PRIVATE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)

set(_gexo_ort_rpath "${ONNXRUNTIME_ROOT}/lib;${ONNXRUNTIME_ROOT}/lib64")
if(GEXO_DEPLOY_BUILD_PROCESS)
  add_executable(gexo_deploy_process src/main.cpp)
  target_link_libraries(gexo_deploy_process PRIVATE gexo_deploy)
  target_compile_options(gexo_deploy_process PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  set_target_properties(gexo_deploy_process PROPERTIES
    BUILD_RPATH "${_gexo_ort_rpath}")
endif()

if(BUILD_TESTING AND GEXO_DEPLOY_BUILD_TESTS)
  add_executable(gexo_deploy_runtime_test tests/runtime_test.cpp)
  target_link_libraries(gexo_deploy_runtime_test PRIVATE gexo_deploy jsoncpp_lib)
  target_include_directories(gexo_deploy_runtime_test PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src")
  target_compile_definitions(gexo_deploy_runtime_test PRIVATE
    GEXO_TEST_MODEL_DIRECTORY="${CMAKE_CURRENT_SOURCE_DIR}/models"
    GEXO_TEST_REPLAY_PATH="${CMAKE_CURRENT_SOURCE_DIR}/tests/reference_replay.json")
  target_compile_options(gexo_deploy_runtime_test PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  set_target_properties(gexo_deploy_runtime_test PROPERTIES
    BUILD_RPATH "${_gexo_ort_rpath}")
  add_test(NAME gexo_deploy_runtime COMMAND gexo_deploy_runtime_test)
endif()
