@echo off
chcp 65001 >nul
if not exist "%~dp0.env" (
  if not exist "%~dp0.env.example" (
    echo 缺少 .env.example，无法创建 .env。
    pause
    exit /b 1
  )
  copy /Y "%~dp0.env.example" "%~dp0.env" >nul
  if errorlevel 1 (
    echo 从 .env.example 创建 .env 失败。
    pause
    exit /b 1
  )
  echo 已从 .env.example 创建 .env；现有 .env 永远不会被覆盖。
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_project.ps1"
if errorlevel 1 (
  echo.
  echo 环境准备失败，请查看上方错误。
  pause
  exit /b 1
)
pause
