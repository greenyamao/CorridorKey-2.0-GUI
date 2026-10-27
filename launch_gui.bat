@echo off
setlocal enabledelayedexpansion
title CorridorKey 2.0 Workbench
cd /d "%~dp0"

REM 0. Automatically sync latest GUI updates from GitHub if git is present
if exist ".git" (
    where git >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        git pull --ff-only origin main >nul 2>&1
    )
)

set "PYTHON="

REM 1. Check existing local venv
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "exit(0)" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "PYTHON=venv\Scripts\python.exe"
    ) else (
        echo [Warning] Detected broken or relocated local venv. Rebuilding...
        rmdir /s /q "venv" >nul 2>&1
    )
)

REM 2. Check existing portable Python environment
if not defined PYTHON (
    if exist "python_embedded\python.exe" (
        "python_embedded\python.exe" -m pip --version >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "PYTHON=python_embedded\python.exe"
        )
    )
)

REM 3. If neither exists, attempt creating venv from a compatible system Python [3.10 - 3.12]
if not defined PYTHON (
    where python >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        python -c "import sys; v = sys.version_info; assert v.major == 3 and 10 <= v.minor and v.minor <= 12" >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo [Setup] Creating isolated local environment [venv]...
            python -m venv venv
            if exist "venv\Scripts\python.exe" (
                set "PYTHON=venv\Scripts\python.exe"
            )
        )
    )
)

REM 4. If still not defined, auto-configure Portable Python 3.11
if not defined PYTHON (
    if not exist "python_embedded\python.exe" (
        echo [Setup] Compatible Python was not detected on your system.
        echo [Setup] Automatically downloading lightweight Portable Python 3.11 [~12 MB]...
        
        if not exist "python_embedded" mkdir "python_embedded"
        
        curl -f -L -o "python_embedded\python-embed.zip" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
        if !ERRORLEVEL! NEQ 0 (
            echo [Error] Failed to download portable Python. Please check your internet connection.
            pause
            exit /b 1
        )
        
        echo [Setup] Extracting portable runtime...
        tar -xf "python_embedded\python-embed.zip" -C "python_embedded"
        del "python_embedded\python-embed.zip" >nul 2>&1
        
        REM Enable site-packages, engine, and pywin32 in embeddable python
        echo python311.zip> "python_embedded\python311._pth"
        echo .>> "python_embedded\python311._pth"
        echo ..>> "python_embedded\python311._pth"
        echo ..\engine>> "python_embedded\python311._pth"
        echo Lib\site-packages>> "python_embedded\python311._pth"
        echo Lib\site-packages\win32>> "python_embedded\python311._pth"
        echo Lib\site-packages\win32\lib>> "python_embedded\python311._pth"
        echo import site>> "python_embedded\python311._pth"
    )
    
    REM Verify or bootstrap pip into portable runtime
    "python_embedded\python.exe" -m pip --version >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo [Setup] Bootstrapping pip into portable runtime...
        curl -f -L -o "python_embedded\get-pip.py" "https://bootstrap.pypa.io/get-pip.py"
        "python_embedded\python.exe" "python_embedded\get-pip.py" --no-warn-script-location >nul 2>&1
        del "python_embedded\get-pip.py" >nul 2>&1
    )
    
    set "PYTHON=python_embedded\python.exe"
)

REM 5. Launch application using the isolated environment
"%PYTHON%" run_gui.py %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with code %ERRORLEVEL%.
    pause
)
