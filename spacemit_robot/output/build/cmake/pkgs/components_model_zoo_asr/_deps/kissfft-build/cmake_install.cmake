# Install script for directory: /home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src

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
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/lib/libkissfft-float.a")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/kissfft" TYPE FILE FILES
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src/kiss_fft.h"
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src/kissfft.hh"
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src/kiss_fftnd.h"
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src/kiss_fftndr.h"
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-src/kiss_fftr.h"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft/kissfft-float-static-targets.cmake")
    file(DIFFERENT _cmake_export_file_changed FILES
         "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft/kissfft-float-static-targets.cmake"
         "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build/CMakeFiles/Export/94098735959e389eabbc4f7bd7723935/kissfft-float-static-targets.cmake")
    if(_cmake_export_file_changed)
      file(GLOB _cmake_old_config_files "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft/kissfft-float-static-targets-*.cmake")
      if(_cmake_old_config_files)
        string(REPLACE ";" ", " _cmake_old_config_files_text "${_cmake_old_config_files}")
        message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft/kissfft-float-static-targets.cmake\" will be replaced.  Removing files [${_cmake_old_config_files_text}].")
        unset(_cmake_old_config_files_text)
        file(REMOVE ${_cmake_old_config_files})
      endif()
      unset(_cmake_old_config_files)
    endif()
    unset(_cmake_export_file_changed)
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft" TYPE FILE FILES "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build/CMakeFiles/Export/94098735959e389eabbc4f7bd7723935/kissfft-float-static-targets.cmake")
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft" TYPE FILE FILES "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build/CMakeFiles/Export/94098735959e389eabbc4f7bd7723935/kissfft-float-static-targets-release.cmake")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/kissfft" TYPE FILE FILES
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build/kissfft-config.cmake"
    "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build/kissfft-config-version.cmake"
    )
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
if(CMAKE_INSTALL_LOCAL_ONLY)
  file(WRITE "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_asr/_deps/kissfft-build/install_local_manifest.txt"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
endif()
