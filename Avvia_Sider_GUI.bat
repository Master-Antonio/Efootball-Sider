@echo off
setlocal
title eFootball Sider Studio GUI
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m ui
    goto :end
)

if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" -m ui
    goto :end
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python -m ui
    goto :end
)

echo ==============================================================================
echo [ERROR] Python environment not found!
echo .venv / venv does not exist and 'python' was not found in system PATH.
echo ==============================================================================
pause

:end
