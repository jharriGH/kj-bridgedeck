"""Voice stack — Whisper (STT) + Piper (TTS).

Whisper runs over the public OpenAI endpoint. Piper is a local subprocess
on Jim's Windows machine; install/install_piper.ps1 sets it up. If Piper
isn't installed we fall back to raising — callers should catch and let the
browser do Web Speech TTS instead."""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import struct
import wave
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
DEFAULT_VOICE = "en_US-ryan-high"
PIPER_SAMPLE_RATE = 22050  # en_US-ryan-high default


class VoiceService:
    def __init__(
        self,
        openai_key: str | None = None,
        piper_binary: str | None = None,
        piper_models_dir: str | None = None,
    ):
        self.openai_key = openai_key or os.environ.get("OPENAI_API_KEY")
        self.piper_binary = piper_binary
        self.piper_models_dir = piper_models_dir

    # ------------------------------------------------------------------
    # STT — Whisper
    # ------------------------------------------------------------------

    async def transcribe(self, audio_base64: str, mime: str = "audio/webm") -> str:
        if not self.openai_key:
            raise RuntimeError("OPENAI_API_KEY is required for Whisper transcription.")
        audio_bytes = base64.b64decode(audio_base64)
        filename = "audio.webm" if mime.endswith("webm") else "audio.wav"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                WHISPER_URL,
                headers={"Authorization": f"Bearer {self.openai_key}"},
                files={"file": (filename, audio_bytes, mime)},
                data={
                    "model": "whisper-1",
                    "response_format": "json",
                    "language": "en",
                },
            )
            resp.raise_for_status()
            return resp.json()["text"]

    # ------------------------------------------------------------------
    # TTS — Piper
    # ------------------------------------------------------------------

    def _resolve_model(self, voice: str) -> Path:
        if not self.piper_models_dir:
            raise RuntimeError(
                "Piper models directory not configured. Run install/install_piper.ps1 "
                "and set voice.piper_model_path."
            )
        path = Path(self.piper_models_dir) / f"{voice}.onnx"
        if not path.exists():
            raise RuntimeError(f"Voice model not found: {path}")
        return path

    def _resolve_binary(self) -> Path:
        if not self.piper_binary:
            raise RuntimeError(
                "Piper binary path not configured. Run install/install_piper.ps1 "
                "and set voice.piper_binary_path."
            )
        path = Path(self.piper_binary)
        if not path.exists():
            raise RuntimeError(f"Piper binary not found: {path}")
        return path

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        sample_rate: int = PIPER_SAMPLE_RATE,
    ) -> bytes:
        """Run Piper and return WAV-wrapped PCM bytes ready for browser playback."""
        binary = self._resolve_binary()
        model_path = self._resolve_model(voice)

        proc = await asyncio.create_subprocess_exec(
            str(binary),
            "--model",
            str(model_path),
            "--output_raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(
                f"Piper failed (rc={proc.returncode}): {stderr.decode(errors='replace')}"
            )
        return _wrap_pcm_wav(stdout, sample_rate=sample_rate)


def _wrap_pcm_wav(pcm: bytes, sample_rate: int = PIPER_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container for browser playback."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


# Kept around so tests / tools can verify the WAV header layout without
# exercising the full Piper pipeline.
def _wav_header_fields(wav_bytes: bytes) -> dict:
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise ValueError("not a WAV blob")
    (_riff, _size, _wave, _fmt, _fmt_size, audio_format, channels, sample_rate,
     _byte_rate, _block_align, bits) = struct.unpack("<4sI4s4sIHHIIHH", wav_bytes[:36])
    return {
        "audio_format": audio_format,
        "channels": channels,
        "sample_rate": sample_rate,
        "bits": bits,
    }
