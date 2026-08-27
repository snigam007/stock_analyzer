@echo off
chcp 65001 > nul
title Indian Stock Analyzer ^& Institutional Advisory Powerhouse
cd /d "%~dp0"

echo ===============================================================================
echo    INDIAN STOCK ANALYZER ^& INSTITUTIONAL POWERHOUSE LAUNCHER
echo ===============================================================================

REM Activate virtual environment if present
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

REM Run the single point launcher
python run.py %*

pause