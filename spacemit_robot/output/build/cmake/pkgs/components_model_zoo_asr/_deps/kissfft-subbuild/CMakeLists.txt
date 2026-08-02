# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file Copyright.txt or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION 4.2.3)

# We name the project and the target for the ExternalProject_Add() call
# to something that will highlight to the user what we are working on if
# something goes wrong and an error message is produced.

project(kissfft-populate NONE)

include(ExternalProject)
ExternalProject_Add(kissfft-populate
                     "UPDATE_DISCONNECTED" "False" "URL" "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kissfft-febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip" "URL_HASH" "SHA256=497103e664168ebe39580b757adbe616f6cf85a16572af581ca7bc42d0ab13fd"
                    SOURCE_DIR          "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src"
                    BINARY_DIR          "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build"
                    CONFIGURE_COMMAND   ""
                    BUILD_COMMAND       ""
                    INSTALL_COMMAND     ""
                    TEST_COMMAND        ""
)
