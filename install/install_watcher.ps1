# ============================================================================
# KJ BridgeDeck Watcher — Windows installer
# Run as Administrator once, after the .exe has been built with PyInstaller.
#
# Installs two Scheduled Tasks:
#   1. "KJ BridgeDeck Watcher"     — runs the watcher .exe at user logon
#   2. "KJ BridgeDeck Brain Flush" — runs brain_flush.ps1 every 30 minutes
#
# Smoke-tests http://localhost:7171/health after launching the watcher.
# ============================================================================

$ErrorActionPreference = "Stop"

$repoRoot         = "$env:USERPROFILE\Documents\GitHub\kj-bridgedeck"
$watcherDir       = Join-Path $repoRoot "watcher"
$exePath          = Join-Path $watcherDir "dist\kj-bridgedeck-watcher.exe"
$brainFlushScript = Join-Path $repoRoot "install\brain_flush.ps1"

Write-Host ""
Write-Host "=== KJ BridgeDeck Watcher — Installer ===" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Prereq check -------------------------------------------------------
if (-not (Test-Path $exePath)) {
    Write-Host "Watcher .exe not built yet at:" -ForegroundColor Yellow
    Write-Host "    $exePath"
    Write-Host ""
    Write-Host "Build it first:"
    Write-Host "    cd $watcherDir"
    Write-Host "    pip install -r requirements.txt"
    Write-Host "    pip install pyinstaller"
    Write-Host "    pyinstaller watcher.spec"
    Write-Host ""
    Write-Host "Then re-run this installer." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $brainFlushScript)) {
    Write-Host "brain_flush.ps1 missing at $brainFlushScript" -ForegroundColor Red
    exit 1
}

# ---- 2. Admin rights -------------------------------------------------------
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This installer must run elevated (Administrator)." -ForegroundColor Red
    Write-Host "Right-click PowerShell -> 'Run as Administrator', then re-run:"
    Write-Host "    powershell -ExecutionPolicy Bypass -File $PSCommandPath"
    exit 1
}

# ---- 3. Scheduled Task: Watcher at logon -----------------------------------
$taskWatcher = "KJ BridgeDeck Watcher"
$action1   = New-ScheduledTaskAction -Execute $exePath -WorkingDirectory $watcherDir
$trigger1  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings1 = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskWatcher `
    -Action $action1 `
    -Trigger $trigger1 `
    -Settings $settings1 `
    -Description "KJ BridgeDeck session watcher (polls Claude Code, writes to Supabase, local API on :7171)" `
    -Force | Out-Null

Write-Host "[OK] Scheduled '$taskWatcher' at logon" -ForegroundColor Green

# ---- 4. Scheduled Task: Brain flush every 30 min ---------------------------
$taskFlush = "KJ BridgeDeck Brain Flush"
$action2 = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$brainFlushScript`""
$trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask `
    -TaskName $taskFlush `
    -Action $action2 `
    -Trigger $trigger2 `
    -Settings $settings1 `
    -Description "Flushes the CodeDeck memory queue to Brain every 30 minutes." `
    -Force | Out-Null

Write-Host "[OK] Scheduled '$taskFlush' every 30 minutes" -ForegroundColor Green

# ---- 5. Start the watcher now ---------------------------------------------
Write-Host ""
Write-Host "Starting watcher..." -ForegroundColor Cyan
Start-Process -FilePath $exePath -WorkingDirectory $watcherDir -WindowStyle Hidden

# ---- 6. Smoke test /health -------------------------------------------------
Start-Sleep -Seconds 3
$healthy = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:7171/health" `
            -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($healthy) {
    Write-Host "[OK] Watcher responding on http://localhost:7171/health" -ForegroundColor Green
    Write-Host ""
    Write-Host "Installation complete." -ForegroundColor Cyan
    Write-Host "  Watcher will auto-start at login."
    Write-Host "  Verify:  Invoke-WebRequest http://localhost:7171/health"
    Write-Host "  Stop:    Stop-ScheduledTask -TaskName `"$taskWatcher`""
    exit 0
} else {
    Write-Host "[WARN] Watcher did not answer /health within 10s." -ForegroundColor Yellow
    Write-Host "Check the Event Viewer and your .env for missing secrets."
    exit 2
}
