# ============================================================================
# Piper TTS Installation (SCAFFOLD)
#
# Bridge-D will complete this script. Expected final behavior:
#
#   1. Download Piper Windows release from GitHub
#      https://github.com/rhasspy/piper/releases (latest)
#   2. Extract to bin/piper/ at repo root
#   3. Download en_US-ryan-high voice model (onnx + json)
#      https://huggingface.co/rhasspy/piper-voices/
#   4. Place models next to piper.exe
#   5. Print PIPER_BINARY_PATH and PIPER_MODEL_PATH for user to paste in .env
#   6. Smoke-test: echo "The bridge is online" | piper --model ... --output-raw | ffplay -
# ============================================================================

Write-Host "[Bridge-D] Piper installation is not yet implemented."
Write-Host "[Bridge-D] Fill in this script after Bridge-D core is built."
Write-Host ""
Write-Host "When complete, this script must:"
Write-Host "  1. Download + extract Piper Windows binary to bin/piper/"
Write-Host "  2. Download en_US-ryan-high voice model"
Write-Host "  3. Print the paths to paste into .env (PIPER_BINARY_PATH, PIPER_MODEL_PATH)"
Write-Host "  4. Smoke-test TTS playback"
exit 0
