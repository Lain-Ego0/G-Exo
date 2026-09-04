cmake_minimum_required(VERSION 3.16)

project(gexo_tcn_pd_deploy LANGUAGES CXX)

include(CTest)

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
  PATHS "${ONNXRUNTIME_ROOT}/include"
  NO_DEFAULT_PATH
  REQUIRED)
find_library(ONNXRUNTIME_LIBRARY
  NAMES onnxruntime
  PATHS "${ONNXRUNTIME_ROOT}/lib" "${ONNXRUNTIME_ROOT}/lib64"
  NO_DEFAULT_PATH
  REQUIRED)

add_library(onnxruntime::onnxruntime UNKNOWN IMPORTED)
set_target_properties(onnxruntime::onnxruntime PROPERTIES
  IMPORTED_LOCATION "${ONNXRUNTIME_LIBRARY}"
  INTERFACE_INCLUDE_DIRECTORIES "${ONNXRUNTIME_INCLUDE_DIR}")

find_package(jsoncpp CONFIG REQUIRED)

add_library(gexo_tcn_pd_deploy STATIC
  src/gexo_tcn_pd_deploy.cpp
  src/sha256.cpp)
target_include_directories(gexo_tcn_pd_deploy PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>")
target_link_libraries(gexo_tcn_pd_deploy PRIVATE
  onnxruntime::onnxruntime
  jsoncpp_lib)
target_compile_options(gexo_tcn_pd_deploy PRIVATE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)

add_executable(gexo_tcn_pd_deploy_process src/main.cpp)
target_link_libraries(gexo_tcn_pd_deploy_process PRIVATE gexo_tcn_pd_deploy)
target_compile_options(gexo_tcn_pd_deploy_process PRIVATE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)

set(_gexo_ort_rpath "${ONNXRUNTIME_ROOT}/lib;${ONNXRUNTIME_ROOT}/lib64")
set_target_properties(gexo_tcn_pd_deploy_process PROPERTIES
  BUILD_RPATH "${_gexo_ort_rpath}")

if(BUILD_TESTING)
  add_executable(gexo_tcn_pd_smoke_test tools/smoke_test.cpp)
  target_link_libraries(gexo_tcn_pd_smoke_test PRIVATE
    gexo_tcn_pd_deploy
    jsoncpp_lib)
  target_include_directories(gexo_tcn_pd_smoke_test PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src")
  target_compile_definitions(gexo_tcn_pd_smoke_test PRIVATE
    GEXO_SMOKE_MODEL_DIRECTORY="${CMAKE_CURRENT_SOURCE_DIR}/models"
    GEXO_SMOKE_REPLAY_PATH="${CMAKE_CURRENT_SOURCE_DIR}/tests/reference_replay.json")
  target_compile_options(gexo_tcn_pd_smoke_test PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  set_target_properties(gexo_tcn_pd_smoke_test PROPERTIES
    BUILD_RPATH "${_gexo_ort_rpath}")

  add_executable(gexo_tcn_pd_deploy_runtime_test tests/runtime_test.cpp)
  target_link_libraries(gexo_tcn_pd_deploy_runtime_test PRIVATE
    gexo_tcn_pd_deploy
    jsoncpp_lib)
  target_include_directories(gexo_tcn_pd_deploy_runtime_test PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src")
  target_compile_definitions(gexo_tcn_pd_deploy_runtime_test PRIVATE
    GEXO_TEST_MODEL_DIRECTORY="${CMAKE_CURRENT_SOURCE_DIR}/models"
    GEXO_TEST_REPLAY_PATH="${CMAKE_CURRENT_SOURCE_DIR}/tests/reference_replay.json")
  target_compile_options(gexo_tcn_pd_deploy_runtime_test PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  set_target_properties(gexo_tcn_pd_deploy_runtime_test PROPERTIES
    BUILD_RPATH "${_gexo_ort_rpath}")
  add_test(NAME gexo_tcn_pd_deploy_runtime
           COMMAND gexo_tcn_pd_deploy_runtime_test)
  add_test(NAME gexo_tcn_pd_local_smoke
           COMMAND gexo_tcn_pd_smoke_test
                   "${CMAKE_CURRENT_SOURCE_DIR}/models"
                   "${CMAKE_CURRENT_SOURCE_DIR}/tests/reference_replay.json"
                   20)
endif()
