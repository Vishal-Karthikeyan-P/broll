"""Speech-to-text adapters. Select with STT_PROVIDER."""
from __future__ import annotations

import os

from ..errors import PipelineError
from .segment import Word


class MockSTT:
    """No-key adapter for tests/demo: reads <audio>.txt next to the audio and spreads words over the duration.
    It does NOT listen to the audio. Use faster_whisper for real transcription."""
    name = "mock"
    model = "none"

    def transcribe(self, audio_path: str, duration: float, transcript_hint: str | None = None) -> list[Word]:
        text = transcript_hint
        side = os.path.splitext(audio_path)[0] + ".txt"
        if not text and os.path.exists(side):
            text = open(side, encoding="utf-8").read()
        if not text or not text.strip():
            raise PipelineError("NO_SPEECH_DETECTED",
                                "Mock STT has no transcript for this audio (set STT_PROVIDER=faster_whisper).", 422)
        toks = text.split()
        # leave a little lead-in/out so scene boundaries fall in pauses
        lead, tail = 0.15, 0.3
        usable = max(duration - lead - tail, 0.5)
        weights = [len(t) + 2 for t in toks]
        total = sum(weights)
        out, t = [], lead
        for tok, wt in zip(toks, weights):
            d = usable * wt / total
            out.append(Word(tok, t, t + d * 0.9))
            t += d
        return out


class FasterWhisperSTT:
    """Real transcription with word timestamps (faster-whisper, MIT). Needs `pip install faster-whisper`
    and a model download on first use."""
    name = "faster_whisper"

    def __init__(self, model: str):
        self.model_name = model
        self.model = model
        self._m = None

    def _load(self):
        if self._m is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise PipelineError("PROVIDER_UNAVAILABLE", "faster-whisper is not installed.", 503)
            self._m = WhisperModel(self.model_name, device="auto", compute_type="int8")
        return self._m

    def transcribe(self, audio_path: str, duration: float, transcript_hint: str | None = None) -> list[Word]:
        m = self._load()
        segments, _info = m.transcribe(audio_path, word_timestamps=True, vad_filter=True)
        words: list[Word] = []
        for seg in segments:
            if getattr(seg, "no_speech_prob", 0) > 0.8:
                continue
            for w in seg.words or []:
                if w.word.strip():
                    words.append(Word(w.word.strip(), float(w.start), float(w.end)))
        if not words:
            raise PipelineError("NO_SPEECH_DETECTED", "No speech detected (silent or music-only audio).", 422)
        return words


def build_stt(settings):
    if settings.stt_provider == "faster_whisper":
        return FasterWhisperSTT(settings.whisper_model)
    return MockSTT()
