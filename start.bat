@echo off
rem FiloTrack launcher
rem   start.bat                -> starts the app (opens the browser)
rem   start.bat --port 8080    -> arguments are passed through to app.py
rem   start.bat test           -> runs the unit tests
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem --- Find a Python interpreter ---------------------------------------------
rem "where python" is not enough: the Windows Store stub WindowsApps\python.exe
rem is found on PATH but only prints "Python was not found" when run.
rem Each candidate is therefore actually executed and its version checked (3.10+).
set "PY="
call :try py -3
if not defined PY call :try python
if not defined PY call :try python3
if not defined PY (
    echo.
    echo ERROR: no working Python 3.10+ interpreter was found.
    echo   Install it from https://www.python.org/downloads/ and tick
    echo   "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

if /i "%~1"=="test" goto :tests

%PY% app.py %*
set "RC=%errorlevel%"
if not "%RC%"=="0" pause
exit /b %RC%

:tests
%PY% -m unittest discover -s tests -v
set "RC=%errorlevel%"
pause
exit /b %RC%

:try
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b 0
