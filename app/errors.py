"""Error model: {"error": {"code", "message", "retryable", "details"}}."""
from __future__ import annotations

# Documented in README.md. Codes are UPPER_SNAKE_CASE.
ERROR_CODES = {
    "INVALID_REQUEST": "Request body failed validation.",
    "EMPTY_INPUT": "Script, scenes or audio were empty or missing.",
    "UNAUTHORIZED": "Missing or wrong bearer token.",
    "RATE_LIMITED": "Too many requests; retry later.",
    "NOT_FOUND": "Route or resource not found.",
    "JOB_NOT_FOUND": "No job with that id.",
    "IDEMPOTENCY_KEY_REUSED": "Idempotency-Key was reused with a different request.",
    "UNSUPPORTED_MEDIA_TYPE": "Input is not mp3, wav or m4a audio (or is unreadable).",
    "AUDIO_TOO_LONG": "Audio is longer than MAX_AUDIO_SECONDS.",
    "SILENT_AUDIO": "Audio contains no audible signal.",
    "NO_SPEECH_DETECTED": "No speech found (silent, music-only or unintelligible).",
    "DOWNLOAD_FAILED": "Could not download the input URL.",
    "URL_NOT_ALLOWED": "URL scheme or host is not allowed.",
    "PROVIDER_UNAVAILABLE": "A required provider (STT/TTS) failed.",
    "MEDIA_PROCESSING_FAILED": "ffmpeg/ffprobe failed.",
    "INTERNAL_ERROR": "Unexpected server error.",
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.details = details or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}}


class PipelineError(ApiError):
    """Raised inside a running job; stored on the job as its error."""
