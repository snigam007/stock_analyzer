# One-Click Revert Script for Stock Analyzer UI
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "`n=======================================================" -ForegroundColor Yellow
Write-Host "  ↺ REVERTING UI TO ORIGINAL LEGACY CONFIGURATION" -ForegroundColor Yellow
Write-Host "=======================================================`n" -ForegroundColor Yellow

# Revert to main branch
git checkout main

Write-Host "`n✔ Successfully reverted to the main branch." -ForegroundColor Green
Write-Host "The application is restored to its original legacy state." -ForegroundColor Green
Write-Host "To switch back to the modern simplified UI anytime, run: git checkout feature/simplified-ui`n" -ForegroundColor Cyan
