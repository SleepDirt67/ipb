cmake_minimum_required(VERSION 3.20)
project(ixray_pacing_checks LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_executable(ixray_pacing_marks markers.cpp)
target_link_libraries(ixray_pacing_marks PRIVATE user32)
add_executable(test_pacing test_pacing.cpp PacingDiagnostics.cpp)
target_compile_definitions(test_pacing PRIVATE IXRAY_PACING_STANDALONE NOMINMAX)
target_link_libraries(test_pacing PRIVATE advapi32)

target_include_directories(test_pacing PRIVATE standalone)

# Match the engine header target; available runtime APIs are resolved dynamically.
target_compile_definitions(test_pacing PRIVATE _WIN32_WINNT=0x0601 WINVER=0x0601)

target_compile_options(test_pacing PRIVATE /Zi)
target_link_options(test_pacing PRIVATE /DEBUG:FULL /OPT:REF /OPT:ICF)
