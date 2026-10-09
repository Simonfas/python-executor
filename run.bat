@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHONW="
set "PYTHON="
set "PYTHON_VERSION="
set "INSTALLED_VERSION="

echo Checking latest official Python version...
call :get_latest_python_version

if not defined PYTHON_VERSION (
    echo.
    echo Could not determine the latest official Python version from python.org.
    echo Check your internet connection and try again.
    echo.
    pause
    exit /b 1
)

echo Latest official Python: %PYTHON_VERSION%

call :find_python

if defined PYTHON (
    call :get_installed_python_version
)

if /I "%INSTALLED_VERSION%"=="%PYTHON_VERSION%" (
    echo Python %PYTHON_VERSION% is already installed.
) else (
    if defined INSTALLED_VERSION (
        echo Python %INSTALLED_VERSION% is installed, but %PYTHON_VERSION% is the latest official version.
    ) else (
        echo Python 3 was not found on this computer.
    )

    echo Installing Python %PYTHON_VERSION%...
    call :install_python

    if errorlevel 1 (
        echo.
        echo Python could not be installed automatically.
        echo Please install the latest Python manually from:
        echo https://www.python.org/downloads/windows/
        echo.
        pause
        exit /b 1
    )

    set "PYTHONW="
    set "PYTHON="
    set "INSTALLED_VERSION="
    call :find_python
    call :get_installed_python_version
)

if not defined PYTHON (
    echo.
    echo Python was installed, but python.exe could not be found.
    echo Try restarting Windows and run this file again.
    echo.
    pause
    exit /b 1
)

if not defined PYTHONW (
    echo.
    echo Python was installed, but pythonw.exe could not be found.
    echo Try restarting Windows and run this file again.
    echo.
    pause
    exit /b 1
)

echo Checking pip for updates...
"%PYTHON%" -m ensurepip --upgrade >nul 2>nul
"%PYTHON%" -m pip install --upgrade pip --disable-pip-version-check --no-cache-dir

if errorlevel 1 (
    echo Warning: pip could not be updated. Python Executor will continue.
) else (
    for /f "tokens=2" %%V in ('"%PYTHON%" -m pip --version 2^>nul') do echo pip %%V is ready.
)

:launch
start "" "%PYTHONW%" "%~dp0app.py"
exit /b 0


:get_latest_python_version
set "PYTHON_VERSION="

where powershell >nul 2>nul
if errorlevel 1 exit /b 1

for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; " ^
    "$html=(Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/downloads/windows/').Content; " ^
    "$m=[regex]::Match($html, 'Latest Python 3 Release - Python ([0-9]+\.[0-9]+\.[0-9]+)'); " ^
    "if(-not $m.Success){ throw 'Latest stable Python version was not found.' }; " ^
    "Write-Output $m.Groups[1].Value"`) do (
    set "PYTHON_VERSION=%%V"
)

if defined PYTHON_VERSION exit /b 0
exit /b 1


:get_installed_python_version
set "INSTALLED_VERSION="

if not defined PYTHON exit /b 1

for /f "usebackq delims=" %%V in (`"%PYTHON%" -c "import platform; print(platform.python_version())" 2^>nul`) do (
    set "INSTALLED_VERSION=%%V"
)

if defined INSTALLED_VERSION exit /b 0
exit /b 1


:find_python
set "PYTHONW="
set "PYTHON="

where py >nul 2>nul
if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
        if exist "%%I" (
            set "PYTHON=%%I"
            for %%J in ("%%I") do set "PYTHONW=%%~dpJpythonw.exe"
        )
    )

    if defined PYTHONW if exist "!PYTHONW!" exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
        if exist "%%I" (
            set "PYTHON=%%I"
            for %%J in ("%%I") do set "PYTHONW=%%~dpJpythonw.exe"
        )
    )

    if defined PYTHONW if exist "!PYTHONW!" exit /b 0
)

for /f "delims=" %%I in ('where pythonw 2^>nul') do (
    if exist "%%I" (
        set "PYTHONW=%%I"
        for %%J in ("%%I") do set "PYTHON=%%~dpJpython.exe"
        exit /b 0
    )
)

for /f "delims=" %%D in ('dir /b /ad /o-n "%LocalAppData%\Programs\Python\Python3*" 2^>nul') do (
    if exist "%LocalAppData%\Programs\Python\%%D\pythonw.exe" (
        set "PYTHONW=%LocalAppData%\Programs\Python\%%D\pythonw.exe"
        set "PYTHON=%LocalAppData%\Programs\Python\%%D\python.exe"
        exit /b 0
    )
)

for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\Python3*" 2^>nul') do (
    if exist "%ProgramFiles%\%%D\pythonw.exe" (
        set "PYTHONW=%ProgramFiles%\%%D\pythonw.exe"
        set "PYTHON=%ProgramFiles%\%%D\python.exe"
        exit /b 0
    )
)

exit /b 1


:install_python
where powershell >nul 2>nul
if errorlevel 1 (
    echo PowerShell is not available, so Python cannot be downloaded automatically.
    exit /b 1
)

where winget >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=1,2 delims=." %%A in ("%PYTHON_VERSION%") do set "PYTHON_MM=%%A.%%B"

    echo Trying a per-user installation with winget...
    winget install --id "Python.Python.!PYTHON_MM!" -e --scope user --silent --accept-source-agreements --accept-package-agreements

    if not errorlevel 1 (
        echo Python %PYTHON_VERSION% installation completed with winget.
        exit /b 0
    )

    echo winget could not install Python. Trying the official python.org installer...
)

set "PYTHON_INSTALLER=%TEMP%\python-%PYTHON_VERSION%-installer.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"

if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-arm64.exe"
)

if /I "%PROCESSOR_ARCHITECTURE%"=="x86" (
    if "%PROCESSOR_ARCHITEW6432%"=="" (
        set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%.exe"
    )
)

echo Downloading Python %PYTHON_VERSION% from python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; " ^
    "try { Invoke-WebRequest -UseBasicParsing -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'; exit 0 } " ^
    "catch { Write-Host $_.Exception.Message; exit 1 }"

if errorlevel 1 (
    if exist "%PYTHON_INSTALLER%" del /q "%PYTHON_INSTALLER%" >nul 2>nul
    exit /b 1
)

echo Installing Python %PYTHON_VERSION% for the current user...
start /wait "" "%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 InstallLauncherAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0 Shortcuts=0

set "INSTALL_RESULT=%ERRORLEVEL%"

if exist "%PYTHON_INSTALLER%" del /q "%PYTHON_INSTALLER%" >nul 2>nul

if "%INSTALL_RESULT%"=="0" (
    echo Python %PYTHON_VERSION% installation completed.
    exit /b 0
)

if "%INSTALL_RESULT%"=="3010" (
    echo Python %PYTHON_VERSION% installation completed. Windows requested a restart.
    exit /b 0
)

if "%INSTALL_RESULT%"=="1625" (
    echo.
    echo ERROR 1625: Windows blocked the Python installer by system policy.
    echo.
    echo Python Executor already tried both:
    echo   - winget with --scope user
    echo   - the official python.org installer as a per-user installation
    echo.
    echo This is a Windows policy restriction, not a Python Executor error.
    echo Check Windows Security, App Control, Group Policy, or organization policies.
    echo If this is your own PC, you can also try running run.bat as Administrator.
    echo.
    exit /b 1625
)

echo Python installer returned exit code %INSTALL_RESULT%.
exit /b %INSTALL_RESULT%
