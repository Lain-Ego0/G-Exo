# Install script for directory: /home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/home/gexo/spacemit_robot/output/staging")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "Release")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "1")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set path to fallback-tool for dependency-resolution.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/lib/libkaldi-native-fbank-core.a")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  include("/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kaldi-native-fbank-build/kaldi-native-fbank/csrc/CMakeFiles/kaldi-native-fbank-core.dir/install-cxx-module-bmi-Release.cmake" OPTIONAL)
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/kaldi-native-fbank/csrc" TYPE FILE FILES
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/feature-fbank.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/feature-functions.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/feature-mfcc.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/feature-raw-audio-samples.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/feature-window.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/istft.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/kaldi-math.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/log.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/mel-computations.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/online-feature.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/rfft.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/stft.h"
    "/home/gexo/.cache/thirdparty/kaldi-native-fbank/kaldi-native-fbank/csrc/whisper-feature.h"
    )
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
if(CMAKE_INSTALL_LOCAL_ONLY)
  file(WRITE "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/kaldi-native-fbank-build/kaldi-native-fbank/csrc/install_local_manifest.txt"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
endif()
