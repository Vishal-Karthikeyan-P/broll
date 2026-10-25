"""Text-to-speech adapters. Select with TTS_PROVIDER.

espeak-ng is GPL-3.0 and is run as a separate process. It is fine for tests and for a no-key demo, but its voice
is robotic; swap in a commercially licensed TTS behind this same interface for production.
"""
from __future__ import annotations

import math
import struct
import subprocess
import wave

from ..errors import PipelineError
from .media import norm_wav

_LANG = {"en": "en-gb", "hi": "hi", "ta": "ta"}


def _espeak_voice(voice: str) -> str:
    """'en-IN-female' -> espeak voice name. Language prefix picks the language, 'female' picks a variant."""
    parts = voice.lower().split("-")
    lang = _LANG.get(parts[0], "en-gb")
    variant = "+f3" if "female" in parts else "+m3"
    return lang + variant


class EspeakTTS:
    name = "espeak-ng"
    model = "espeak-ng"

    def synthesize(self, text: str, voice: str, out_wav: str) -> None:
        tmp = out_wav + ".raw.wav"
        p = subprocess.run(["espeak-ng", "-v", _espeak_voice(voice), "-s", "150", "-w", tmp, text],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise PipelineError("PROVIDER_UNAVAILABLE", "espeak-ng failed.", 503, retryable=True,
                                details={"stderr": p.stderr[-300:]})
        norm_wav(tmp, out_wav)


class MockTTS:
    """Writes a quiet tone whose length follows the word count. For tests on machines without espeak."""
    name = "mock"
    model = "none"

    def synthesize(self, text: str, voice: str, out_wav: str) -> None:
        secs = max(1.2, 0.38 * len(text.split()))
        n = int(48000 * secs)
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * i / 48000)))
                                   for i in range(n)))


def build_tts(settings):
    return MockTTS() if settings.tts_provider == "mock" else EspeakTTS()
