cmake_minimum_required(VERSION 3.20)
project(HideProcessDriver C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Target architecture: x64 (kernel drivers require x64 on modern Windows).
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR AMD64)

add_library(HideProcess SHARED
    driver.c
    Offset.h
)

target_include_directories(HideProcess PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Kernel-mode compilation flags.
target_compile_options(HideProcess PRIVATE
    /kernel          # Compile as a kernel-mode driver
    /Zl              # Omit default library name
    /Gy              # Enable function-level linking
    /Gz              # Stdcall calling convention
    /GS-             # Disable security checks (kernel code)
    /wd4100          # Disable unreferenced formal parameter warnings
    /wd4214          # Disable bit field types other than int
    /wd4201          # Disable nameless struct/union warnings
)

target_compile_definitions(HideProcess PRIVATE
    _AMD64_
    _KERNEL_MODE
    NTDDK
)

# Link against the WDK kernel libraries.
if(WINDOWS_KITS_ROOT)
    set(WDK_LIB_DIR "${WINDOWS_KITS_ROOT}/lib/10.0/km/x64")
    if(EXISTS "${WDK_LIB_DIR}")
        target_link_directories(HideProcess PRIVATE ${WDK_LIB_DIR})
        target_link_libraries(HideProcess PRIVATE ntoskrnl.lib hal.lib)
    endif()
endif()

set_target_properties(HideProcess PROPERTIES
    OUTPUT_NAME HideProcess
    SUFFIX .sys
    LINKER_FLAGS "/DRIVER /SUBSYSTEM:NATIVE /ENTRY:DriverEntry"
)
