# kissfft-config.ccmake accept the following components:
#
# SHARED/STATIC:
#     This components allows one to choose a shared/static kissfft library.
#     The default is selected by BUILD_SHARED_LIBS.
#     They are to be used exclusively. Using them together is an error.
#
#     example:
#         find_package(kissfft CONFIG REQUIRED COMPONENTS STATIC)
#
# simd/int16/int32/float/double:
#     This components allows one to choose the datatype.
#     When using this component, the target kissfft::kissfft becomes available.
#     When not using this component, you will have to choose the correct kissfft target.
#
#     example:
#         find_package(kissfft CONFIG REQUIRED)
#         # - kissfft::kissfft-float, kissfft::kissfft-int32_t/ ... are available (if they are installed)
#         # - kissfft::kissfft is not available,
#
#         find_package(kissfft CONFIG REQUIRED COMPONENTS int32_t)
#         # - kissfft::kissfft-float, kissfft::kissfft-int32_t/ ... are available (if they are installed)
#         # - kissfft::kissfft is available (as an alias for kissfft::kissfft-int32_t),


####### Expanded from @PACKAGE_INIT@ by configure_package_config_file() #######
####### Any changes to this file will be overwritten by the next CMake run ####
####### The input file was kissfft-config.cmake.in                            ########

get_filename_component(PACKAGE_PREFIX_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../" ABSOLUTE)

macro(set_and_check _var _file)
  set(${_var} "${_file}")
  if(NOT EXISTS "${_file}")
    message(FATAL_ERROR "File or directory ${_file} referenced by variable ${_var} does not exist !")
  endif()
endmacro()

macro(check_required_components _NAME)
  foreach(comp ${${_NAME}_FIND_COMPONENTS})
    if(NOT ${_NAME}_${comp}_FOUND)
      if(${_NAME}_FIND_REQUIRED_${comp})
        set(${_NAME}_FOUND FALSE)
      endif()
    endif()
  endforeach()
endmacro()

####################################################################################

cmake_minimum_required(VERSION 3.3)

# Set include glob of config files using SHARED/static component, BUILD_SHARED_LIBS by default
set(_kissfft_shared_detected OFF)
set(_kissfft_shared ${BUILD_SHARED_LIBS})
if("SHARED" IN_LIST kissfft_FIND_COMPONENTS)
    set(_kissfft_shared_detected ON)
    set(_kissfft_shared ON)
endif()
if("STATIC" IN_LIST kissfft_FIND_COMPONENTS)
    if(_kissfft_shared_detected)
        message(FATAL_ERROR "SHARED and STATIC components cannot be used together")
    endif()
    set(_kissfft_shared_detected ON)
    set(_kissfft_shared OFF)
endif()

if(_kissfft_shared)
    set(_kissfft_config_glob "kissfft-*-shared-targets.cmake")
else()
    set(_kissfft_config_glob "kissfft-*-static-targets.cmake")
endif()

# Load information for all configured kissfft
get_filename_component(_DIR "${CMAKE_CURRENT_LIST_FILE}" PATH)
file(GLOB CONFIG_FILES "${_DIR}/${_kissfft_config_glob}")
foreach(f ${CONFIG_FILES})
  include(${f})
endforeach()

# If a datatype component is passed, create kissfft::kissfft
set(_kissfft_datatype_detected)
foreach(_kissfft_datatype simd int16 int32 float double)
    if(_kissfft_datatype IN_LIST kissfft_FIND_COMPONENTS)
        if(_kissfft_datatype_detected)
            message(FATAL_ERROR "Cannot define datatype COMPONENT twice: ${_kissfft_datatype_detected} and ${_kissfft_datatype}")
        endif()
        set(_kissfft_datatype_detected ${_kissfft_datatype})
    endif()
endforeach()

if(_kissfft_datatype_detected)
    if(NOT TARGET kissfft::kissfft-${_kissfft_datatype_detected})
        message(FATAL_ERROR "kissfft with datatype=${_kissfft_datatype_detected} is not installed")
    endif()
    if(TARGET kissfft::kissfft)
        message(SEND_ERROR "kissfft::kissfft already exists. You cannot use 2 find_package's with datatype that are visible to eachother.")
    else()
        add_library(kissfft::kissfft INTERFACE IMPORTED)
        set_property(TARGET kissfft::kissfft PROPERTY INTERFACE_LINK_LIBRARIES kissfft::kissfft-${_kissfft_datatype_detected})
    endif()
endif()

set(kissfft_FOUND ON)
set(KISSFFT_VERSION 131.1.0)

