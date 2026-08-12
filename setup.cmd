@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_project.ps1"
if errorlevel 1 (
  echo.
  echo 环境准备失败，请查看上方错误。
  pause
  exit /b 1
)
pause
