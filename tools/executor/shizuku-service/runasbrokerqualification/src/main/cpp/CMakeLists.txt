cmake_minimum_required(VERSION 3.22.1)
project(codex_runas_broker_bootstrap C)
get_filename_component(STAGE "${CMAKE_CURRENT_SOURCE_DIR}/../../../../build/runasbrokerqualification-v1/stage-r2" REALPATH)
get_filename_component(PYTHON_HEADERS "${CMAKE_CURRENT_SOURCE_DIR}/../../../../../../../downloads/runas-python-20260908/prefix/include" REALPATH)
add_executable(codex_runas_broker_bootstrap bootstrap.c)
set_target_properties(codex_runas_broker_bootstrap PROPERTIES OUTPUT_NAME libcodex_runas_broker_bootstrap SUFFIX .so BUILD_RPATH "$ORIGIN")
target_include_directories(codex_runas_broker_bootstrap PRIVATE "${STAGE}" "${PYTHON_HEADERS}")
target_compile_features(codex_runas_broker_bootstrap PRIVATE c_std_11)
target_compile_options(codex_runas_broker_bootstrap PRIVATE -Wall -Wextra -Werror -fPIE -fstack-protector-strong)
target_link_directories(codex_runas_broker_bootstrap PRIVATE "${STAGE}/jniLibs/arm64-v8a")
target_link_libraries(codex_runas_broker_bootstrap PRIVATE crypto_python)
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/runas-rpath.rsp" CONTENT "-rpath\n$ORIGIN\n")
# Windows CMake's Ninja command quoting doubles a literal dollar in link
# flags. A linker response file preserves the ELF token byte-for-byte.
target_link_options(codex_runas_broker_bootstrap PRIVATE -pie "-Wl,@${CMAKE_CURRENT_BINARY_DIR}/runas-rpath.rsp"
    -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384)
