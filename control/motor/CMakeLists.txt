find_package(Threads REQUIRED)

add_library(gexo_rs02_motor STATIC
    rs02_motor.cpp
    rs02_motor_group.cpp
)

target_include_directories(gexo_rs02_motor
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
)

target_compile_features(gexo_rs02_motor PUBLIC cxx_std_17)
target_compile_options(gexo_rs02_motor PRIVATE -Wall -Wextra -Wpedantic)

add_executable(gexo_rs02_damping_demo rs02_damping_demo.cpp)
target_link_libraries(gexo_rs02_damping_demo PRIVATE gexo_rs02_motor)
target_compile_options(gexo_rs02_damping_demo PRIVATE -Wall -Wextra -Wpedantic)

add_executable(gexo_rs02_direction_demo rs02_direction_demo.cpp)
target_link_libraries(gexo_rs02_direction_demo PRIVATE
    gexo_rs02_motor
    Threads::Threads)
target_compile_options(gexo_rs02_direction_demo PRIVATE -Wall -Wextra -Wpedantic)

if(BUILD_TESTING)
    add_executable(gexo_rs02_protocol_test rs02_protocol_test.cpp)
    target_link_libraries(gexo_rs02_protocol_test PRIVATE gexo_rs02_motor)
    target_compile_options(gexo_rs02_protocol_test PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME gexo_rs02_protocol_test COMMAND gexo_rs02_protocol_test)
endif()
