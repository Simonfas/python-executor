@echo off
setlocal EnableExtensions

set "APP_PID=%~1"
set "PYTHON_MM=%~2"
set "APP_DIR=%~3"

if "%APP_PID%"=="" exit /b 1
if "%PYTHON_MM%"=="" exit /b 1
if "%APP_DIR%"=="" set "APP_DIR=%~dp0"

echo.
echo Python Executor - Python Uninstaller
echo ====================================
echo.
echo Waiting for Python Executor to close...

:wait_for_app
tasklist /FI "PID eq %APP_PID%" 2>nul | find "%APP_PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto :wait_for_app
)

echo Removing executor virtual environments...
if exist "%APP_DIR%\.executor_envs" (
    rmdir /s /q "%APP_DIR%\.executor_envs" 2>nul
)

echo Removing user Python libraries for Python %PYTHON_MM%...
for /f "tokens=1,2 delims=." %%A in ("%PYTHON_MM%") do set "PYTAG=%%A%%B"

if defined APPDATA (
    if exist "%APPDATA%\Python\Python%PYTAG%" (
        rmdir /s /q "%APPDATA%\Python\Python%PYTAG%" 2>nul
    )
)

echo Removing pip cache...
if defined LOCALAPPDATA (
    if exist "%LOCALAPPDATA%\pip\Cache" (
        rmdir /s /q "%LOCALAPPDATA%\pip\Cache" 2>nul
    )
)

echo Uninstalling Python %PYTHON_MM%...

set "UNINSTALL_OK=0"

where winget >nul 2>nul
if not errorlevel 1 (
    winget uninstall --id "Python.Python.%PYTHON_MM%" -e --silent --accept-source-agreements
    if not errorlevel 1 set "UNINSTALL_OK=1"
)

if "%UNINSTALL_OK%"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_python.ps1" -PythonMajorMinor "%PYTHON_MM%"
    if not errorlevel 1 set "UNINSTALL_OK=1"
)

echo.
if "%UNINSTALL_OK%"=="1" (
    echo Python %PYTHON_MM%, pip, user libraries and executor environments were removed.
) else (
    echo Python could not be fully uninstalled automatically.
    echo You may need to remove Python %PYTHON_MM% from Windows Settings ^> Apps ^> Installed apps.
)

echo.
echo NOTE: Running run.bat again will automatically install Python again.
echo.
pause
exit /b 0
