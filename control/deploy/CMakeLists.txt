cmake_minimum_required(VERSION 3.16)

project(gexo_deploy LANGUAGES CXX)

include(CTest)

option(GEXO_DEPLOY_BUILD_TESTS "Build Deploy runtime tests" ${BUILD_TESTING})

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(ONNXRUNTIME_ROOT "$ENV{ONNXRUNTIME_ROOT}" CACHE PATH
    "Root directory of the ONNX Runtime C/C++ SDK")
if(NOT ONNXRUNTIME_ROOT AND
   EXISTS "/home/lenovo/third_party/onnxruntime-linux-x64-1.23.0/include/onnxruntime_cxx_api.h")
  set(ONNXRUNTIME_ROOT
      "/home/lenovo/third_party/onnxruntime-linux-x64-1.23.0"
      CACHE PATH "Root directory of the ONNX Runtime C/C++ SDK" FORCE)
endif()

find_path(ONNXRUNTIME_INCLUDE_DIR
  NAMES onnxruntime_cxx_api.h
  HINTS "${ONNXRUNTIME_ROOT}/include"
  PATH_SUFFIXES "" onnxruntime onnxruntime/core/session
  REQUIRED)
find_library(ONNXRUNTIME_LIBRARY
  NAMES onnxruntime
  HINTS "${ONNXRUNTIME_ROOT}/lib" "${ONNXRUNTIME_ROOT}/lib64"
        "${ONNXRUNTIME_ROOT}/lib/riscv64-linux-gnu"
  REQUIRED)

if(NOT TARGET onnxruntime::onnxruntime)
  add_library(onnxruntime::onnxruntime UNKNOWN IMPORTED GLOBAL)
  set_target_properties(onnxruntime::onnxruntime PROPERTIES
    IMPORTED_LOCATION "${ONNXRUNTIME_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${ONNXRUNTIME_INCLUDE_DIR}")
endif()

find_package(jsoncpp CONFIG REQUIRED)

add_library(gexo_deploy STATIC
  gexo_deploy.cpp
  sha256.cpp)
target_include_directories(gexo_deploy PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>")
target_link_libraries(gexo_deploy PRIVATE
  onnxruntime::onnxruntime
  jsoncpp_lib)
target_compile_options(gexo_deploy PRIVATE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
set(_gexo_deploy_ort_rpath
    "${ONNXRUNTIME_ROOT}/lib;${ONNXRUNTIME_ROOT}/lib64")

if(BUILD_TESTING AND GEXO_DEPLOY_BUILD_TESTS)
  add_executable(gexo_deploy_runtime_test runtime_test.cpp)
  target_link_libraries(gexo_deploy_runtime_test PRIVATE gexo_deploy jsoncpp_lib)
  target_compile_definitions(gexo_deploy_runtime_test PRIVATE
    GEXO_TEST_MODEL_DIRECTORY="${CMAKE_CURRENT_SOURCE_DIR}/models"
    GEXO_TEST_REPLAY_PATH="${CMAKE_CURRENT_SOURCE_DIR}/reference_replay.json")
  target_compile_options(gexo_deploy_runtime_test PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  set_target_properties(gexo_deploy_runtime_test PROPERTIES
    BUILD_RPATH "${_gexo_deploy_ort_rpath}")
  add_test(NAME gexo_deploy_runtime COMMAND gexo_deploy_runtime_test)
endif()

add_subdirectory(tcn_pd)

add_library(gexo_policy_runtime STATIC policy_runtime.cpp)
target_include_directories(gexo_policy_runtime PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>"
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/..>")
target_link_libraries(gexo_policy_runtime PUBLIC
  gexo_deploy
  gexo_tcn_pd_deploy)
target_compile_options(gexo_policy_runtime PRIVATE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)

if(BUILD_TESTING)
  add_executable(gexo_policy_runtime_test policy_runtime_test.cpp)
  target_link_libraries(gexo_policy_runtime_test PRIVATE gexo_policy_runtime)
  target_compile_definitions(gexo_policy_runtime_test PRIVATE
    GEXO_RL_TCN_MODEL_DIRECTORY="${CMAKE_CURRENT_SOURCE_DIR}/models"
    GEXO_TCN_PD_MODEL_DIRECTORY="${CMAKE_CURRENT_SOURCE_DIR}/tcn_pd/models")
  target_compile_options(gexo_policy_runtime_test PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  add_test(NAME gexo_policy_runtime COMMAND gexo_policy_runtime_test)
endif()
