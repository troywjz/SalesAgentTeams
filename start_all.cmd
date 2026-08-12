@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_all.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请查看上方错误和 .runtime 日志。
  pause
  exit /b 1
)
pause
