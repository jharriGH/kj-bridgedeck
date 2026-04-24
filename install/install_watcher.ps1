# ============================================================================
# KJ BridgeDeck Watcher — Windows installation (SCAFFOLD)
#
# Bridge-B will complete this script after the watcher code + PyInstaller spec
# are built. Expected final behavior:
#
#   1. Build/copy the watcher executable from watcher/dist/bridgedeck-watcher.exe
#   2. Copy it to $env:LOCALAPPDATA\BridgeDeck\
#   3. Copy .env from repo root (user must have filled it in)
#   4. Register a Windows Scheduled Task to run at user logon
#   5. Start it immediately via Start-ScheduledTask
#   6. Smoke-test localhost:7171/health
# ============================================================================

Write-Host "[Bridge-B] Watcher installation is not yet implemented."
Write-Host "[Bridge-B] Fill in this script after the watcher is built."
Write-Host ""
Write-Host "When complete, this script must:"
Write-Host "  1. Copy bridgedeck-watcher.exe to %LOCALAPPDATA%\BridgeDeck\"
Write-Host "  2. Register scheduled task 'BridgeDeck-Watcher' running at user logon"
Write-Host "  3. Start the task and confirm http://localhost:7171/health returns 200"
exit 0
