cmake_minimum_required(VERSION 3.22.1)
project(codex_runas_identity C)
# Executable ELF is intentionally packaged as an extracted APK native library.
add_executable(codex_runas_identity identity.c)
set_target_properties(codex_runas_identity PROPERTIES OUTPUT_NAME libcodex_runas_identity SUFFIX .so)
target_compile_features(codex_runas_identity PRIVATE c_std_11)
target_compile_options(codex_runas_identity PRIVATE -Wall -Wextra -Werror -fPIE -fstack-protector-strong)
target_link_options(codex_runas_identity PRIVATE -pie -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384)
