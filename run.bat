@echo off
rem ================================================
rem  SJ Desktop Manager - launcher
rem  Double-click this file to start the app.
rem  If your Python is not at D:\Python313, edit PYW.
rem ================================================
setlocal
set "PYW=D:\Python313\pythonw.exe"

if not exist "%PYW%" (
    echo [ERROR] pythonw.exe not found: %PYW%
    echo Edit this .bat and set PYW to your pythonw.exe path.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0main.py"
exit /b 0
