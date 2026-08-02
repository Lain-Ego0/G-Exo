#----------------------------------------------------------------
# Generated CMake target import file for configuration "Release".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "kissfft::kissfft-float" for configuration "Release"
set_property(TARGET kissfft::kissfft-float APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(kissfft::kissfft-float PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_RELEASE "C"
  IMPORTED_LOCATION_RELEASE "${_IMPORT_PREFIX}/lib/libkissfft-float.a"
  )

list(APPEND _cmake_import_check_targets kissfft::kissfft-float )
list(APPEND _cmake_import_check_files_for_kissfft::kissfft-float "${_IMPORT_PREFIX}/lib/libkissfft-float.a" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
