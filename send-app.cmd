@echo off
chcp 65001 >nul
if "%~1"=="" (
  echo 请把整个 .papp 应用目录拖到这个文件上。
  pause
  exit /b 1
)
"%USERPROFILE%\miniconda3\python.exe" "%~dp0scripts\push-app.py" "%~1"
pause
