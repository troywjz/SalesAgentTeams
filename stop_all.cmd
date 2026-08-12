@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_all.ps1"
if errorlevel 1 (
  echo.
  echo 关停未完全成功，请查看上方错误。
  pause
  exit /b 1
)
pause
