@echo off
setlocal

echo ========================================
echo HideProcess - Hide a Process
echo ========================================

if "%1"=="" (
    echo Usage: %~nx0 <process_name>
    echo Example: %~nx0 python.exe
    echo Example: %~nx0 MyApplication.exe
    echo.
    pause
    exit /b 1
)

set "CLIENT_DIR=%~dp0kernel\userland"

if not exist "%CLIENT_DIR%\hide_client.exe" (
    echo [ERROR] hide_client.exe not found at %CLIENT_DIR%
    echo Build it first with build_driver.bat
    pause
    exit /b 1
)

echo [INFO] Sending hide request for: %1
"%CLIENT_DIR%\hide_client.exe" %1

if errorlevel 1 (
    echo [ERROR] Failed to send IOCTL. Is the driver running?
    echo Start it: sc start hideprocess
) else (
    echo [OK] Process should now be hidden from Task Manager.
)

pause
