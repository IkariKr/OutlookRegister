@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "PS1_PATH=%ROOT_DIR%manager-ui\start-manager-ui.ps1"

if not exist "%PS1_PATH%" (
    echo [Error] Not found: "%PS1_PATH%"
    echo Please make sure the manager-ui folder exists.
    pause
    exit /b 1
)

cd /d "%ROOT_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [Error] start-manager-ui.ps1 exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
