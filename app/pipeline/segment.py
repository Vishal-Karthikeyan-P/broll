"""Split narration into scenes on sentence/phrase boundaries; build SRT captions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TERMINATORS = (".", "!", "?", "…", "।")
SOFT = (",", ";", ":", "—", "–")
ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "e.g", "i.e", "st", "no", "inc", "ltd"}


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Scene:
    index: int
    text: str
    start: float = 0.0
    end: float = 0.0
    visual_hint: str | None = None
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------- text → phrases (used for the script / scenes path) ----------
def split_sentences(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        buf = ""
        tokens = para.split(" ")
        for i, tok in enumerate(tokens):
            buf = f"{buf} {tok}".strip()
            core = tok.rstrip("\"')”’")
            if core.endswith(TERMINATORS):
                base = core.rstrip(".!?…").lower()
                if core.endswith(".") and (base in ABBREV or re.fullmatch(r"[a-z]", base)):
                    continue  # abbreviation like "Dr." or an initial
                if i + 1 < len(tokens):
                    nxt = tokens[i + 1]
                    if core.endswith(".") and nxt[:1].islower():
                        continue
                out.append(buf)
                buf = ""
        if buf:
            out.append(buf)
    return out


def split_long(sentence: str, max_words: int) -> list[str]:
    """Split an over-long sentence at the soft punctuation closest to its middle; fall back to the middle word."""
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    mid = len(words) // 2
    cands = [i for i, w in enumerate(words[:-2]) if w.endswith(SOFT) and i >= 2]
    cut = min(cands, key=lambda i: abs(i - mid)) + 1 if cands else mid
    return split_long(" ".join(words[:cut]), max_words) + split_long(" ".join(words[cut:]), max_words)


def merge_short(parts: list[str], min_words: int) -> list[str]:
    out: list[str] = []
    for p in parts:
        if out and len(p.split()) < min_words:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    if len(out) > 1 and len(out[0].split()) < min_words:
        out[1] = f"{out[0]} {out[1]}"
        out = out[1:]
    return out


def phrases_from_text(text: str, min_words: int = 4, max_words: int = 22) -> list[str]:
    parts: list[str] = []
    for s in split_sentences(text):
        parts.extend(split_long(s, max_words))
    return merge_short(parts, min_words)


# ---------- word timestamps → scenes (audio path) ----------
def scenes_from_words(words: list[Word], total: float, min_s: float, max_s: float) -> list[Scene]:
    if not words:
        return []
    units: list[list[Word]] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        sentence_end = w.text.rstrip("\"')”’").endswith(TERMINATORS)
        long_pause = nxt is not None and (nxt.start - w.end) >= 0.9
        if nxt is None or sentence_end or long_pause:
            units.append(cur)
            cur = []

    def span(u):  # duration of the spoken words
        return u[-1].end - u[0].start

    # split units longer than max_s at soft punctuation / largest pause nearest the middle
    def split_unit(u: list[Word]) -> list[list[Word]]:
        if span(u) <= max_s or len(u) < 4:
            return [u]
        mid_t = u[0].start + span(u) / 2
        soft = [i for i, w in enumerate(u[:-1]) if w.text.endswith(SOFT) and 1 <= i < len(u) - 2]
        if soft:
            cut = min(soft, key=lambda i: abs(u[i].end - mid_t)) + 1
        else:
            gaps = [(u[i + 1].start - u[i].end, i) for i in range(1, len(u) - 2)]
            cut = max(gaps)[1] + 1 if gaps else len(u) // 2
        return split_unit(u[:cut]) + split_unit(u[cut:])

    split: list[list[Word]] = []
    for u in units:
        split.extend(split_unit(u))

    # merge units shorter than min_s into a neighbour
    merged: list[list[Word]] = []
    for u in split:
        if merged and span(u) < min_s:
            merged[-1] = merged[-1] + u
        else:
            merged.append(u)
    if len(merged) > 1 and span(merged[0]) < min_s:
        merged[1] = merged[0] + merged[1]
        merged = merged[1:]

    scenes: list[Scene] = []
    for i, u in enumerate(merged):
        scenes.append(Scene(index=i, text=" ".join(w.text for w in u), words=u))
    # contiguous coverage: boundaries at the midpoint of the pause between units
    for i, sc in enumerate(scenes):
        sc.start = 0.0 if i == 0 else (scenes[i - 1].words[-1].end + sc.words[0].start) / 2
        sc.end = total if i == len(scenes) - 1 else (sc.words[-1].end + scenes[i + 1].words[0].start) / 2
    return scenes


# ---------- captions ----------
def _fmt(t: float) -> str:
    t = max(t, 0)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _wrap(text: str, width: int = 38) -> str:
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def build_srt(scenes: list[Scene], max_words: int = 7) -> str:
    """Cues use real word times when we have them, otherwise proportional timing inside each scene."""
    cues: list[tuple[float, float, str]] = []
    for sc in scenes:
        if sc.words:
            group: list[Word] = []
            for i, w in enumerate(sc.words):
                group.append(w)
                if len(group) >= max_words or w.text.endswith(TERMINATORS + SOFT) or i == len(sc.words) - 1:
                    cues.append((group[0].start, group[-1].end, " ".join(x.text for x in group)))
                    group = []
        else:
            toks = sc.text.split()
            chunks = [toks[i:i + max_words] for i in range(0, len(toks), max_words)] or [[]]
            total_chars = sum(len(" ".join(c)) for c in chunks) or 1
            t = sc.start
            for c in chunks:
                d = (sc.duration - 0.1) * len(" ".join(c)) / total_chars
                cues.append((t, t + d, " ".join(c)))
                t += d
    # stretch each cue to the next cue's start (no flicker), keep inside the video
    out = []
    for i, (s, e, txt) in enumerate(cues):
        if i + 1 < len(cues):
            e = min(max(e, s + 0.3) + 0.25, cues[i + 1][0])
        out.append(f"{i + 1}\n{_fmt(s)} --> {_fmt(max(e, s + 0.2))}\n{_wrap(txt)}\n")
    return "\n".join(out)
