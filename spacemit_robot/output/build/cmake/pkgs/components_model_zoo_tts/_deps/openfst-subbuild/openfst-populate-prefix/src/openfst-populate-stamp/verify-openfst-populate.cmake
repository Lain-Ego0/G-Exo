# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file LICENSE.rst or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION ${CMAKE_VERSION}) # this file comes with cmake

if("/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_tts/openfst-sherpa-onnx-2024-06-13.tar.gz" STREQUAL "")
  message(FATAL_ERROR "LOCAL can't be empty")
endif()

if(NOT EXISTS "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_tts/openfst-sherpa-onnx-2024-06-13.tar.gz")
  message(FATAL_ERROR "File not found: /home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_tts/openfst-sherpa-onnx-2024-06-13.tar.gz")
endif()

if("SHA256" STREQUAL "")
  message(WARNING "File cannot be verified since no URL_HASH specified")
  return()
endif()

if("f10a71c6b64d89eabdc316d372b956c30c825c7c298e2f20c780320e8181ffb6" STREQUAL "")
  message(FATAL_ERROR "EXPECT_VALUE can't be empty")
endif()

message(VERBOSE "verifying file...
     file='/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_tts/openfst-sherpa-onnx-2024-06-13.tar.gz'")

file("SHA256" "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_tts/openfst-sherpa-onnx-2024-06-13.tar.gz" actual_value)

if(NOT "${actual_value}" STREQUAL "f10a71c6b64d89eabdc316d372b956c30c825c7c298e2f20c780320e8181ffb6")
  message(FATAL_ERROR "error: SHA256 hash of
  /home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_tts/openfst-sherpa-onnx-2024-06-13.tar.gz
does not match expected value
  expected: 'f10a71c6b64d89eabdc316d372b956c30c825c7c298e2f20c780320e8181ffb6'
    actual: '${actual_value}'
")
endif()

message(VERBOSE "verifying file... done")
