# ============================================================================
# KJ BridgeDeck — Brain memory queue flush
# Called by Windows Task Scheduler every 30 min.
#
# Install as scheduled task (run once as Jim):
#   $action = New-ScheduledTaskAction -Execute "pwsh" -Argument "-File C:\Users\Jim\Documents\GitHub\kj-bridgedeck\install\brain_flush.ps1"
#   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)
#   Register-ScheduledTask -TaskName "BridgeDeck-BrainFlush" -Action $action -Trigger $trigger -RunLevel Limited
# ============================================================================

$BRAIN_KEY = "jim-brain-kje-2026-kingjames"
$BRAIN_URL = "https://jim-brain-production.up.railway.app/codedeck/flush-memory-queue"
$LOG_PATH  = "$env:TEMP\bridgedeck_flush.log"

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

try {
    $response = Invoke-WebRequest `
        -Uri $BRAIN_URL `
        -Method POST `
        -Headers @{ "x-brain-key" = $BRAIN_KEY } `
        -UseBasicParsing `
        -TimeoutSec 30

    $statusLine = "[$ts] Flush OK: HTTP $($response.StatusCode)"
    Write-Host $statusLine
    Add-Content -Path $LOG_PATH -Value $statusLine
    exit 0
} catch {
    $statusLine = "[$ts] Flush FAILED: $($_.Exception.Message)"
    Write-Host $statusLine -ForegroundColor Red
    Add-Content -Path $LOG_PATH -Value $statusLine
    exit 1
}
