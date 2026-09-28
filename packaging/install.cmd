@echo off
rem Double-click to install Wireless Limitless for the current user.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 pause
