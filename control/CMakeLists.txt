cmake_minimum_required(VERSION 3.16)

project(gexo_control LANGUAGES CXX)

include(CTest)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(GEXO_BUILD_DEPLOY "Build the ONNX deployment runtime" ON)
option(GEXO_BUILD_ROS2_MAIN "Build the ROS2 control node when ROS2 is available" ON)

add_subdirectory(motor)
if(GEXO_BUILD_DEPLOY)
  add_subdirectory(deploy)
endif()

if(BUILD_TESTING)
  add_executable(gexo_control_contract_test control_contract_test.cpp)
  target_include_directories(gexo_control_contract_test PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}")
  target_compile_options(gexo_control_contract_test PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
  add_test(NAME gexo_control_contract COMMAND gexo_control_contract_test)
endif()

find_package(ament_cmake QUIET)
if(GEXO_BUILD_ROS2_MAIN AND GEXO_BUILD_DEPLOY)
  find_package(ament_index_cpp QUIET)
  find_package(rclcpp QUIET)
  find_package(sensor_msgs QUIET)
  find_package(std_srvs QUIET)

  if(ament_cmake_FOUND AND ament_index_cpp_FOUND AND rclcpp_FOUND AND
     sensor_msgs_FOUND AND std_srvs_FOUND)
    add_executable(gexo_control_node main.cpp)
    target_link_libraries(gexo_control_node
      gexo_policy_runtime
      gexo_rs02_motor)
    ament_target_dependencies(gexo_control_node
      ament_index_cpp
      rclcpp
      sensor_msgs
      std_srvs)
    target_compile_options(gexo_control_node PRIVATE
      -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
    install(TARGETS gexo_control_node
      DESTINATION lib/${PROJECT_NAME})
  else()
    message(STATUS
      "ROS2 dependencies are unavailable; skipping gexo_control_node. "
      "The Deploy, policy and motor libraries remain buildable.")
  endif()
endif()

if(ament_cmake_FOUND)
  install(DIRECTORY deploy/models/
    DESTINATION share/${PROJECT_NAME}/models/rl_tcn)
  install(DIRECTORY deploy/tcn_pd/models/
    DESTINATION share/${PROJECT_NAME}/models/tcn_pd)
  install(DIRECTORY config launch
    DESTINATION share/${PROJECT_NAME})
  install(DIRECTORY imu_ros2
    DESTINATION share/${PROJECT_NAME})
  install(FILES README.md MAIN_DEMO_FRAMEWORK.md K3_DEPLOY.md UNFINISHED.md
                MODEL_MANIFEST.sha256
    DESTINATION share/${PROJECT_NAME})
  ament_package()
endif()
