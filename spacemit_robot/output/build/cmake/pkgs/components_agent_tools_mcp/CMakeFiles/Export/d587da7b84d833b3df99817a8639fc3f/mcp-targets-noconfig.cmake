#----------------------------------------------------------------
# Generated CMake target import file.
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "mcp::mcp_static" for configuration ""
set_property(TARGET mcp::mcp_static APPEND PROPERTY IMPORTED_CONFIGURATIONS NOCONFIG)
set_target_properties(mcp::mcp_static PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_NOCONFIG "CXX"
  IMPORTED_LOCATION_NOCONFIG "${_IMPORT_PREFIX}/lib/libmcp.a"
  )

list(APPEND _cmake_import_check_targets mcp::mcp_static )
list(APPEND _cmake_import_check_files_for_mcp::mcp_static "${_IMPORT_PREFIX}/lib/libmcp.a" )

# Import target "mcp::mcp_shared" for configuration ""
set_property(TARGET mcp::mcp_shared APPEND PROPERTY IMPORTED_CONFIGURATIONS NOCONFIG)
set_target_properties(mcp::mcp_shared PROPERTIES
  IMPORTED_LOCATION_NOCONFIG "${_IMPORT_PREFIX}/lib/libmcp.so.1.0.0"
  IMPORTED_SONAME_NOCONFIG "libmcp.so.1"
  )

list(APPEND _cmake_import_check_targets mcp::mcp_shared )
list(APPEND _cmake_import_check_files_for_mcp::mcp_shared "${_IMPORT_PREFIX}/lib/libmcp.so.1.0.0" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
