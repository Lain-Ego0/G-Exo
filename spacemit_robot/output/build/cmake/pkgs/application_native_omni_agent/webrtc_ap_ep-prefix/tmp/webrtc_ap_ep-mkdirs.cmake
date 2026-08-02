# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file LICENSE.rst or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION ${CMAKE_VERSION}) # this file comes with cmake

# If CMAKE_DISABLE_SOURCE_CHANGES is set to true and the source directory is an
# existing directory in our source tree, calling file(MAKE_DIRECTORY) on it
# would cause a fatal error, even though it would be a no-op.
if(NOT EXISTS "/home/gexo/.cache/thirdparty/webrtc-audio-processing")
  file(MAKE_DIRECTORY "/home/gexo/.cache/thirdparty/webrtc-audio-processing")
endif()
file(MAKE_DIRECTORY
  "/home/gexo/.cache/thirdparty/webrtc-audio-processing/build"
  "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix"
  "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix/tmp"
  "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix/src/webrtc_ap_ep-stamp"
  "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix/src"
  "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix/src/webrtc_ap_ep-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix/src/webrtc_ap_ep-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "/home/gexo/spacemit_robot/output/build/cmake/pkgs/application_native_omni_agent/webrtc_ap_ep-prefix/src/webrtc_ap_ep-stamp${cfgdir}") # cfgdir has leading slash
endif()
