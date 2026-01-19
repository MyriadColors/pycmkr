cmake_minimum_required(VERSION 3.10)
project(MinimalProject LANGUAGES C)

set(CMAKE_C_STANDARD 23)

add_executable(main main.c)
add_executable(unit_tests unit_tests.c)
