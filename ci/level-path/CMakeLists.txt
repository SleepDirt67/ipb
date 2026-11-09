cmake_minimum_required(VERSION 3.20)
project(IXRaySerialFrameReplay LANGUAGES CXX)

add_executable(level_search_replay fixture.cpp)
target_include_directories(level_search_replay PRIVATE . "${LEVEL_PATH_GENERATED}")
target_compile_features(level_search_replay PRIVATE cxx_std_20)

add_executable(collection_index_replay ../spawn-bind/fixture.cpp)
target_include_directories(collection_index_replay PRIVATE "${SPAWN_BIND_GENERATED}")
target_compile_features(collection_index_replay PRIVATE cxx_std_20)
