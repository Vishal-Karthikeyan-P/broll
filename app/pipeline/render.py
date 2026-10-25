"""ffmpeg rendering: normalise each clip, concatenate, add narration and captions, then run automated QA."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess

from .media import ffprobe, run

SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
FPS = 30


def ratio_slug(r: str) -> str:
    return r.replace(":", "x")


def _snap(t: float) -> float:
    return round(t * FPS) / FPS


def render_segment(clip: str, seconds: float, ratio: str, portrait_mode: str, out: str) -> None:
    """One scene, normalised: exact length, 30 fps, yuv420p, target size. Loops only if the source is too short."""
    w, h = SIZES[ratio]
    src_ratio_note = ""
    if ratio == "9:16" and portrait_mode == "blur_fit":
        # keep the whole frame (subject at the edge stays visible) over a blurred, filled background
        sw, sh = w // 4, h // 4  # blur a small copy, then scale up: much cheaper than blurring full size
        vf = (f"split[a][b];[a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},boxblur=5:2,"
              f"scale={w}:{h}[bg];[b]scale={w}:-2:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p,setsar=1")
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},format=yuv420p,setsar=1"
    run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", clip, "-t", f"{seconds:.4f}", "-vf", vf,
         "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-video_track_timescale", "15360", out])


def segment_key(clip_key: str, seconds: float, ratio: str, mode: str) -> str:
    return hashlib.sha1(f"{clip_key}|{seconds:.4f}|{ratio}|{mode}".encode()).hexdigest()[:20]


def assemble(segments: list[str], narration: str, srt_path: str | None, burn_in: bool, ratio: str,
             total_seconds: float, workdir: str, out: str) -> None:
    w, h = SIZES[ratio]
    lst = os.path.join(workdir, f"concat_{ratio_slug(ratio)}.txt")
    with open(lst, "w") as f:
        for s in segments:
            f.write("file '" + s.replace("'", "'\\''") + "'\n")
    joined = os.path.join(workdir, f"joined_{ratio_slug(ratio)}.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", joined, "-i", narration]
    if burn_in and srt_path:
        # libass maps SRT onto a 288-unit-high canvas, so sizes are given in those units (not pixels)
        target_px = h * 0.040 if ratio != "9:16" else w * 0.050
        size = max(8, round(target_px * 288 / h))
        style = f"FontSize={size},Outline=1,Shadow=0,Alignment=2,MarginV={int(0.09 * 288)},PrimaryColour=&H00FFFFFF"
        rel = os.path.relpath(srt_path, workdir)
        vf = f"subtitles={rel}:force_style='{style}'"
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS)]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", f"{total_seconds:.4f}", "-movflags", "+faststart", out]
    _run_in(cmd, workdir)


def _run_in(cmd: list[str], cwd: str) -> None:
    from ..errors import PipelineError
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if p.returncode:
        raise PipelineError("MEDIA_PROCESSING_FAILED", "ffmpeg failed while adding captions",
                            details={"stderr": p.stderr[-500:]})


def qa_check(path: str, expected_seconds: float, ratio: str) -> dict:
    """Automated checks on a finished file: codecs, fps, size, A/V duration, black and frozen frames."""
    info = ffprobe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    num, den = v["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    w, h = SIZES[ratio]
    vdur = float(v.get("duration") or info["format"]["duration"])
    adur = float(a.get("duration") or info["format"]["duration"]) if a else 0.0
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-vf", "blackdetect=d=0.5:pix_th=0.08,freezedetect=n=0.0005:d=2.5",
                        "-an", "-f", "null", "-"], capture_output=True, text=True)
    black = len(re.findall(r"black_start", p.stderr))
    frozen = len(re.findall(r"freeze_start", p.stderr))
    checks = {
        "video_codec_h264": v["codec_name"] == "h264",
        "audio_codec_aac": bool(a) and a["codec_name"] == "aac",
        "fps_30": abs(fps - FPS) < 0.01,
        "resolution_ok": (v["width"], v["height"]) == (w, h),
        "audio_video_duration_match": abs(vdur - adur) < 0.15 and abs(adur - expected_seconds) < 0.2,
        "no_black_frames": black == 0,
        "no_frozen_frames": frozen == 0,
    }
    return {"ratio": ratio, "passed": all(checks.values()), "checks": checks,
            "measured": {"fps": round(fps, 3), "width": v["width"], "height": v["height"],
                         "video_s": round(vdur, 3), "audio_s": round(adur, 3), "black_segments": black,
                         "frozen_segments": frozen}}
