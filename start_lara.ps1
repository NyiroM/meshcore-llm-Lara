# LARA Auto-Reply Bot - PowerShell Launcher
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "LARA - Auto-Reply Bot (PowerShell)" -ForegroundColor Cyan
Write-Host ""

Set-Location $PSScriptRoot

if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "[OK] Activating virtual environment..." -ForegroundColor Green
    & .venv\Scripts\Activate.ps1
    Write-Host ""
}

if (-not (Test-Path "lara_config.yaml")) {
    Write-Host "[X] ERROR: lara_config.yaml not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path "auto_reply_priv.py")) {
    Write-Host "[X] ERROR: auto_reply_priv.py not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[->] Starting script..." -ForegroundColor Cyan
Write-Host ""

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 3
    Start-Process "http://127.0.0.1:8766/status"
} | Out-Null

try {
    python auto_reply_priv.py
    $exitCode = $LASTEXITCODE
    
    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "[OK] Script finished successfully" -ForegroundColor Green
    } else {
        Write-Host "[X] Script exited with code: $exitCode" -ForegroundColor Red
    }
} catch {
    Write-Host "[X] Runtime error: $_" -ForegroundColor Red
    $exitCode = 1
}

Write-Host ""
Read-Host "Press Enter to exit"
exit $exitCode
