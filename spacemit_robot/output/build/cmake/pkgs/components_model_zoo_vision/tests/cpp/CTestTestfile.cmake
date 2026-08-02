# CMake generated Testfile for 
# Source directory: /home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp
# Build directory: /home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(vision_mpp_frame_api "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_mpp_frame_api_test")
set_tests_properties(vision_mpp_frame_api PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;92;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_mpp_nv12_layout "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_mpp_nv12_layout_test")
set_tests_properties(vision_mpp_nv12_layout PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;105;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_opencl_geometry "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_opencl_geometry_test")
set_tests_properties(vision_opencl_geometry PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;118;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_preprocess_backend "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_preprocess_backend_test")
set_tests_properties(vision_preprocess_backend PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;131;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_preprocess_dispatcher "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_preprocess_dispatcher_test")
set_tests_properties(vision_preprocess_dispatcher PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;146;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_cpu_image_preprocessor "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_cpu_image_preprocessor_test")
set_tests_properties(vision_cpu_image_preprocessor PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;158;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_embed_opencl_source "/usr/bin/cmake" "-DVISION_SOURCE_DIR=/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/../.." "-DTEST_OUTPUT_DIR=/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/embed_opencl_test" "-P" "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/../../tests/cmake/embed_opencl_test.cmake")
set_tests_properties(vision_embed_opencl_source PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;163;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_opencl_optional_build "/usr/bin/cmake" "-DVISION_SOURCE_DIR=/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/../.." "-DTEST_OUTPUT_DIR=/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/opencl_optional_build" "-DOpenCV_DIR=/opt/opencv-spacemit/lib/cmake/opencv4" "-DSPACEMIT_DIR=" "-P" "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/../../tests/cmake/opencl_optional_build_test.cmake")
set_tests_properties(vision_opencl_optional_build PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;172;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_cpp_runtime_profile "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_cpp_runtime_profile")
set_tests_properties(vision_cpp_runtime_profile PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;243;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
add_test(vision_preprocess_backend_scope "/home/gexo/spacemit_robot/output/build/cmake/pkgs/components_model_zoo_vision/tests/cpp/vision_preprocess_backend_scope_test")
set_tests_properties(vision_preprocess_backend_scope PROPERTIES  _BACKTRACE_TRIPLES "/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;244;add_test;/home/gexo/spacemit_robot/components/model_zoo/vision/tests/cpp/CMakeLists.txt;0;")
