# Indian Stock Analyzer & Institutional Powerhouse — PowerShell Launcher
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    & ".\venv\Scripts\Activate.ps1"
}

python run.py $args