"""ffmpeg / ffprobe helpers, input fetching and validation."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import wave
from urllib.parse import urlparse

import httpx

from ..errors import PipelineError

AUDIO_EXTS = {".mp3", ".wav", ".m4a"}


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PipelineError("MEDIA_PROCESSING_FAILED", f"{cmd[0]} timed out", retryable=True)
    if p.returncode != 0:
        raise PipelineError("MEDIA_PROCESSING_FAILED", f"{cmd[0]} failed", retryable=False,
                            details={"stderr": p.stderr[-600:]})
    return p


def ffprobe(path: str) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise PipelineError("UNSUPPORTED_MEDIA_TYPE", "File is not readable audio/video.", 415,
                            details={"stderr": p.stderr[-300:]})
    return json.loads(p.stdout or "{}")


def duration(path: str) -> float:
    return float(ffprobe(path).get("format", {}).get("duration", 0) or 0)


def max_volume_db(path: str) -> float | None:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", p.stderr)
    if not m:
        return None
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


def norm_wav(src: str, dst: str) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", dst])


def concat_wavs(paths: list[str], out: str, gap_s: float = 0.25, tail_s: float = 0.4) -> list[float]:
    """Concatenate 48k mono wavs with a short gap after each; returns per-segment durations (incl. gap)."""
    durs: list[float] = []
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        for i, p in enumerate(paths):
            with wave.open(p, "rb") as r:
                frames = r.readframes(r.getnframes())
                n = r.getnframes()
            pad = tail_s if i == len(paths) - 1 else gap_s
            pad_frames = int(round(pad * 48000))
            w.writeframes(frames + b"\x00\x00" * pad_frames)
            durs.append((n + pad_frames) / 48000)
    return durs


def _host_allowed(host: str, allow_private: bool) -> bool:
    if allow_private:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def check_url(url: str, allow_private: bool) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise PipelineError("URL_NOT_ALLOWED", "Only http(s) URLs are allowed.", 422)
    if not _host_allowed(u.hostname, allow_private):
        raise PipelineError("URL_NOT_ALLOWED", "URL points to a private or unresolvable host.", 422)


def download(url: str, dest: str, max_mb: int, timeout: float, allow_private: bool) -> None:
    check_url(url, allow_private)
    limit = max_mb * 1024 * 1024
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
            if r.status_code >= 400:
                raise PipelineError("DOWNLOAD_FAILED", f"Download returned HTTP {r.status_code}.",
                                    retryable=r.status_code >= 500)
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    size += len(chunk)
                    if size > limit:
                        raise PipelineError("DOWNLOAD_FAILED", f"File larger than {max_mb} MB.", 413)
                    f.write(chunk)
    except httpx.HTTPError as e:
        raise PipelineError("DOWNLOAD_FAILED", f"Download failed: {e.__class__.__name__}", retryable=True)


def validate_audio(path: str, max_seconds: int, filename_hint: str = "") -> float:
    """Check type, duration and that the audio is not silent. Returns duration in seconds."""
    ext = os.path.splitext(filename_hint or path)[1].lower()
    if ext and ext not in AUDIO_EXTS:
        raise PipelineError("UNSUPPORTED_MEDIA_TYPE", f"Unsupported file type '{ext}'. Use mp3, wav or m4a.", 415)
    info = ffprobe(path)
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise PipelineError("UNSUPPORTED_MEDIA_TYPE", "File has no audio stream.", 415)
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    if dur <= 0.2:
        raise PipelineError("EMPTY_INPUT", "Audio is empty.", 400)
    if dur > max_seconds:
        raise PipelineError("AUDIO_TOO_LONG", f"Audio is {dur:.0f}s; the limit is {max_seconds}s.", 422,
                            details={"duration_s": round(dur, 1), "limit_s": max_seconds})
    mv = max_volume_db(path)
    if mv is None or mv < -55:
        raise PipelineError("SILENT_AUDIO", "Audio is silent or almost silent.", 422, details={"max_volume_db": mv})
    return dur
