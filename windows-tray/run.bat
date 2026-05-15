@echo off
title Clawdmeter
cd /d "%~dp0"

echo Checking Python...
py --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=py
    goto :install_deps
)
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=python
    goto :install_deps
)
py3 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=py3
    goto :install_deps
)
python3 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=python3
    goto :install_deps
)
echo Python not found. Please install Python 3.10+ from https://python.org
echo IMPORTANT: During installation, check "Add Python to PATH"
pause
exit /b 1

:install_deps

echo Creating virtual environment...
if exist "venv\" (
    echo Removing old venv...
    rmdir /s /q venv
)
%PYTHON% -m venv venv
if %ERRORLEVEL% NEQ 0 (
    echo Failed to create venv
    pause
    exit /b 1
)

echo Installing dependencies...
call venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate venv
    pause
    exit /b 1
)

pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo Failed to install dependencies
    pause
    exit /b 1
)

echo Starting Clawdmeter...
python clawdmeter_tray.py
pause
