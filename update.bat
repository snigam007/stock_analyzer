@echo off
title Indian Stock Market Analyzer - Daily Update
cd /d "%~dp0"
echo ================================================
echo   Indian Stock Market Analyzer - Daily Update
echo   Checks database and downloads ONLY delta data
echo ================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found. Please run run.bat first.
    pause
    exit /b
)

call venv\Scripts\activate.bat
python update_daily.py

echo.
pause
