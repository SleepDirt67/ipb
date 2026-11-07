cmake_minimum_required(VERSION 3.20)
project(ixray_stack_hotpaths LANGUAGES CXX)

find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(generated "${CMAKE_CURRENT_BINARY_DIR}/functions.inc")
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/generate.py" "${ENGINE}" "${generated}"
    COMMAND_ERROR_IS_FATAL ANY
)
add_executable(ixray_stack_hotpaths differential.cpp)
target_include_directories(ixray_stack_hotpaths PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(ixray_stack_hotpaths PRIVATE cxx_std_20)
