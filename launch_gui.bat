@echo off
setlocal enabledelayedexpansion
title CorridorKey 2.0 Workbench
cd /d "%~dp0"

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python was not found in your system PATH.
    echo Please install Python 3.10, 3.11, or 3.12 from python.org and check Add Python to PATH.
    echo.
    pause
    exit /b 1
)

rem Fast check and auto-pull GUI updates if Git is available
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    if exist ".git" (
        git pull --ff-only origin main >nul 2>&1
    )
)

if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

"%PYTHON%" run_gui.py %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with code %ERRORLEVEL%.
    pause
)
