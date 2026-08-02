# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file LICENSE.rst or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION ${CMAKE_VERSION}) # this file comes with cmake

if("/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip" STREQUAL "")
  message(FATAL_ERROR "LOCAL can't be empty")
endif()

if(NOT EXISTS "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip")
  message(FATAL_ERROR "File not found: /home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip")
endif()

if("SHA256" STREQUAL "")
  message(WARNING "File cannot be verified since no URL_HASH specified")
  return()
endif()

if("497103e664168ebe39580b757adbe616f6cf85a16572af581ca7bc42d0ab13fd" STREQUAL "")
  message(FATAL_ERROR "EXPECT_VALUE can't be empty")
endif()

message(VERBOSE "verifying file...
     file='/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip'")

file("SHA256" "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip" actual_value)

if(NOT "${actual_value}" STREQUAL "497103e664168ebe39580b757adbe616f6cf85a16572af581ca7bc42d0ab13fd")
  message(FATAL_ERROR "error: SHA256 hash of
  /home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip
does not match expected value
  expected: '497103e664168ebe39580b757adbe616f6cf85a16572af581ca7bc42d0ab13fd'
    actual: '${actual_value}'
")
endif()

message(VERBOSE "verifying file... done")
