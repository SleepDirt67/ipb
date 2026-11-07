@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0capture.ps1" -Mode Baseline
pause
