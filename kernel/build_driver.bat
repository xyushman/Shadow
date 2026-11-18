@echo off
setlocal enabledelayedexpansion

echo ========================================
echo HideProcess - Kernel Driver Builder
echo ========================================

:: Check for WDK / CMake
if not defined WINDOWS_KITS_ROOT (
    echo [WARN] WINDOWS_KITS_ROOT not set. WDK may not be installed.
)

:: Paths
set "DRV_DIR=%~dp0kernel\HideProcess"
set "CLIENT_DIR=%~dp0kernel\userland"

echo.
echo [1/4] Building kernel driver...
pushd "%DRV_DIR%"
if not exist "build" mkdir build
cmake -S . -B build -A x64
if errorlevel 1 (
    echo [ERROR] CMake configure failed
    popd
    pause
    exit /b 1
)
cmake --build build --config Release
if errorlevel 1 (
    echo [ERROR] Driver build failed
    popd
    pause
    exit /b 1
)
popd

if exist "%DRV_DIR%\build\Release\HideProcess.sys" (
    echo [OK] Driver built: %DRV_DIR%\build\Release\HideProcess.sys
) else (
    echo [ERROR] HideProcess.sys not found
    pause
    exit /b 1
)

echo.
echo [2/4] Building userland client...
pushd "%CLIENT_DIR%"
cl /nologo /EHsc hide_client.cpp /Fe:hide_client.exe 2>nul
if errorlevel 1 (
    echo [WARN] cl.exe not found, trying g++
    g++ hide_client.cpp -o hide_client.exe 2>nul
)
popd

if exist "%CLIENT_DIR%\hide_client.exe" (
    echo [OK] Client built: %CLIENT_DIR%\hide_client.exe
) else (
    echo [WARN] Could not auto-compile hide_client.exe. Compile manually:
    echo         cl /nologo /EHsc hide_client.cpp /Fe:hide_client.exe
)

echo.
echo [3/4] Installing driver (requires Administrator)...
set "SYS_PATH=%DRV_DIR%\build\Release\HideProcess.sys"
sc stop hideprocess 2>nul
sc delete hideprocess 2>nul
sc create hideprocess binpath="%SYS_PATH%" type=kernel
if errorlevel 1 (
    echo [ERROR] Failed to create service. Run this script as Administrator.
    pause
    exit /b 1
)
sc start hideprocess
if errorlevel 1 (
    echo [ERROR] Failed to start driver
    pause
    exit /b 1
)
echo [OK] Driver service started.

echo.
echo [4/4] Ready to hide a process.
echo Usage: %CLIENT_DIR%\hide_client.exe <process_name>
echo Example: %CLIENT_DIR%\hide_client.exe python.exe
echo.
pause
