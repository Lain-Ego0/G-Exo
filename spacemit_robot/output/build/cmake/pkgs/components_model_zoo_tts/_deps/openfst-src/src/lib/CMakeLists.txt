FILE(GLOB HEADER_FILES ../include/fst/*.h)


add_library(fst
  compat.cc
  flags.cc
  fst.cc
  properties.cc
  symbol-table.cc
  util.cc
  symbol-table-ops.cc
  mapped-file.cc
  weight.cc
  ${HEADER_FILES}
)

if(BUILD_SHARED_LIBS)
  target_compile_definitions(fst PRIVATE FST_BUILD_MAIN_LIB=1)
  target_compile_definitions(fst PUBLIC FST_BUILD_SHARED_LIBS=1)
endif()

# set_target_properties(fst PROPERTIES
#   SOVERSION "6"
# )
install(TARGETS fst
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  RUNTIME DESTINATION lib)
