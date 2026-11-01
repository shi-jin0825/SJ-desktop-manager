@echo off
rem ============================================================
rem  MoMo Desktop Manager - launcher (double-click to start)
rem  Auto-detects a usable Python; no path editing needed.
rem
rem  Lookup order:
rem    1) env vars MOMO_PYTHON / PYTHONW
rem    2) the "py -3" launcher (ships with python.org installs)
rem    3) pythonw.exe / python.exe on PATH
rem    4) common install dirs (%LOCALAPPDATA%\Programs\Python, C:\Python3x, D:\Python3x)
rem    5) bundled portable runtime\runtime\pythonw.exe
rem
rem  No Python at all? Install it from https://www.python.org/downloads/
rem  (tick "Add python.exe to PATH"), or just use the packaged exe
rem  in dist\ (built with: python tools\build_exe.py)
rem ============================================================
setlocal
set "APP=%~dp0main.py"
set "PYW="

rem 1) explicit override wins
if defined MOMO_PYTHON if exist "%MOMO_PYTHON%" set "PYW=%MOMO_PYTHON%"
if not defined PYW if defined PYTHONW if exist "%PYTHONW%" set "PYW=%PYTHONW%"

rem 2..5) fall back to auto-detection
if not defined PYW call :from_py_launcher
if not defined PYW call :from_path
if not defined PYW call :from_install_dir
if not defined PYW if exist "%~dp0runtime\pythonw.exe" set "PYW=%~dp0runtime\pythonw.exe"

if not defined PYW goto :no_python

echo [OK] Using %PYW%
start "" "%PYW%" "%APP%"
exit /b 0

rem ---------------- detection helpers ----------------
:from_py_launcher
for /f "usebackq delims=" %%P in (`py -3 -c "import sys,os;print(os.path.join(sys.prefix,'pythonw.exe'))" 2^>nul`) do (
    if not defined PYW if exist "%%P" set "PYW=%%P"
)
exit /b 0

:from_path
for %%C in (pythonw.exe python.exe) do (
    if not defined PYW (
        for /f "usebackq delims=" %%P in (`where %%C 2^>nul`) do (
            if not defined PYW if exist "%%P" set "PYW=%%P"
        )
    )
)
exit /b 0

:from_install_dir
for %%D in ("%LOCALAPPDATA%\Programs\Python" "C:\Program Files\Python" "C:" "D:") do (
    if not defined PYW (
        for /d %%V in ("%%~D\Python3*") do (
            if not defined PYW if exist "%%~V\pythonw.exe" set "PYW=%%~V\pythonw.exe"
        )
    )
)
exit /b 0

:no_python
echo.
echo [ERROR] Python not found.
echo.
echo Pick one:
echo   1. Install Python - https://www.python.org/downloads/
echo      tick "Add python.exe to PATH", then double-click this file again.
echo   2. Use the packaged exe in dist\ (build it with: python tools\build_exe.py)
echo.
pause
exit /b 1
