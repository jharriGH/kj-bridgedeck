# ============================================================================
# KJ BridgeDeck — Piper TTS Installer
#
# Downloads Piper Windows binary + en_US-ryan-high voice model,
# unpacks them under bin/piper/, and prints the paths to drop into
# kjcodedeck.settings (voice.piper_binary_path + voice.piper_model_path).
#
# Run from the repo root:
#   pwsh install/install_piper.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

$piperVersion     = "2023.11.14-2"
$piperZipUrl      = "https://github.com/rhasspy/piper/releases/download/$piperVersion/piper_windows_amd64.zip"

$repoRoot         = Split-Path -Parent $PSScriptRoot
$installDir       = Join-Path $repoRoot "bin\piper"
$voicesDir        = Join-Path $installDir "voices"

$voiceOnnxUrl     = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx"
$voiceConfigUrl   = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json"

Write-Host "[Piper] Preparing install directory at $installDir"
New-Item -Path $installDir -ItemType Directory -Force | Out-Null
New-Item -Path $voicesDir  -ItemType Directory -Force | Out-Null

$zipPath = Join-Path $installDir "piper.zip"
Write-Host "[Piper] Downloading binary from $piperZipUrl"
Invoke-WebRequest -Uri $piperZipUrl -OutFile $zipPath -UseBasicParsing

Write-Host "[Piper] Extracting binary..."
Expand-Archive -Path $zipPath -DestinationPath $installDir -Force
Remove-Item $zipPath

$piperExe = Join-Path $installDir "piper\piper.exe"
if (-not (Test-Path $piperExe)) {
    # Some releases unzip without the nested piper/ folder.
    $alt = Join-Path $installDir "piper.exe"
    if (Test-Path $alt) {
        $piperExe = $alt
    } else {
        Write-Error "[Piper] Could not locate piper.exe after extraction under $installDir"
        exit 1
    }
}

Write-Host "[Piper] Downloading voice model en_US-ryan-high..."
$onnxPath   = Join-Path $voicesDir "en_US-ryan-high.onnx"
$configPath = Join-Path $voicesDir "en_US-ryan-high.onnx.json"
Invoke-WebRequest -Uri $voiceOnnxUrl   -OutFile $onnxPath   -UseBasicParsing
Invoke-WebRequest -Uri $voiceConfigUrl -OutFile $configPath -UseBasicParsing

Write-Host ""
Write-Host "[Piper] Smoke-test..."
$testWav = Join-Path $installDir "test.wav"
"The bridge is online." | & $piperExe --model $onnxPath --output_file $testWav
if (Test-Path $testWav) {
    Write-Host "[Piper] Generated $testWav ($((Get-Item $testWav).Length) bytes)"
}

Write-Host ""
Write-Host "============================================================"
Write-Host "Piper installed successfully."
Write-Host "------------------------------------------------------------"
Write-Host "PIPER_BINARY_PATH = $piperExe"
Write-Host "PIPER_MODEL_PATH  = $voicesDir"
Write-Host ""
Write-Host "Update Supabase settings (or your .env):"
Write-Host ""
Write-Host "  UPDATE kjcodedeck.settings SET value = '`"$($piperExe -replace '\\','\\\\')`"'"
Write-Host "    WHERE namespace = 'voice' AND key = 'piper_binary_path';"
Write-Host ""
Write-Host "  UPDATE kjcodedeck.settings SET value = '`"$($voicesDir -replace '\\','\\\\')`"'"
Write-Host "    WHERE namespace = 'voice' AND key = 'piper_model_path';"
Write-Host "============================================================"
