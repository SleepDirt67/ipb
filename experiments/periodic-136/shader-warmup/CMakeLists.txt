cmake_minimum_required(VERSION 3.20)
project(ixray_shader_warmup LANGUAGES CXX)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/generate.py" "${ENGINE}" "${CMAKE_CURRENT_BINARY_DIR}/renderer.inc"
    COMMAND_ERROR_IS_FATAL ANY
)
add_executable(ixray_shader_warmup fixture.cpp)
target_include_directories(ixray_shader_warmup PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(ixray_shader_warmup PRIVATE cxx_std_20)
target_link_libraries(ixray_shader_warmup PRIVATE d3dcompiler d3d11)
