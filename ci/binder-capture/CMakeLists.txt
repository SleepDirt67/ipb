cmake_minimum_required(VERSION 3.21)
project(ixray_binder_capture_checks LANGUAGES C CXX)

add_executable(binder_capture_runtime_test runtime_test.c)
target_include_directories(binder_capture_runtime_test PRIVATE "${LUA_HEADERS}")
target_link_libraries(binder_capture_runtime_test PRIVATE "${LUA_IMPORT}")

add_executable(binder_capture_engine_test engine_test.cpp)
target_compile_features(binder_capture_engine_test PRIVATE cxx_std_17)
