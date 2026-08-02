include(CMakeFindDependencyMacro)
find_dependency(nlohmann_json)
find_dependency(Threads)
include("${CMAKE_CURRENT_LIST_DIR}/mcp-targets.cmake")
