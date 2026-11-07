@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0spawn_path_capture.ps1"
if errorlevel 1 pause
