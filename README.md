# IncuBrix B-roll Engine (Assessment 3)

Turns a **voiceover (audio)** or a **script / scene list (text)** into a finished video: footage for every line, timed
to the narration, burned-in captions, and a full record of where every clip came from and under what licence.

```
 POST /api/v1/broll/jobs ──► 202 + job_id ──► worker (thread pool)
                                               │
   audio ─► STT (word times) ─┐                ▼
   text  ─► TTS per phrase  ──┴─► scenes ─► planner ─► footage providers ─► select ─► render ─► QA ─► storage
            (exact timing)        (sentence/   (queries,   (pexels, pixabay,   (licence, no     (ffmpeg)  (S3/MinIO
                                   phrase)      safety)      mock; failover)    repeats, score)            or local)
 GET /api/v1/jobs/{id} ◄── status, progress 0-100, result links (video_*.mp4, captions.srt, timeline.json, manifest.json)
```

Every external service sits behind a small adapter chosen by an environment variable (`STT_PROVIDER`, `TTS_PROVIDER`,
`PLANNER_PROVIDER`, `FOOTAGE_PROVIDERS`), and each has a mock/no-key option so the tests need no API keys.

## Quick start (no API keys)

```bash
cp .env.example .env
docker compose up --build        # API on :8000, MinIO on :9000
curl -s localhost:8000/ready
curl -s -X POST localhost:8000/api/v1/broll/jobs -H 'Content-Type: application/json' \
  -d '{"script":"Saving money starts with one small habit. Put a little aside every month.","aspect_ratios":["16:9","9:16"]}'
curl -s localhost:8000/api/v1/jobs/<job_id>
make test                        # all tests, no keys
make batch                       # run samples/ and write results
```
Without Docker: `pip install -r requirements-dev.txt`, install `ffmpeg` and `espeak-ng`, then
`uvicorn app.main:app` and `pytest -q`.

**To use real footage / speech:** set `FOOTAGE_PROVIDERS=pexels,pixabay` plus the two keys; set
`STT_PROVIDER=faster_whisper` and build with `WITH_WHISPER=1`; optionally `PLANNER_PROVIDER=openai_compat` with
`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (e.g. Gemini's OpenAI-compatible endpoint). Check the footage adapters with
`python scripts/check_providers.py`.

## API (all under `/api/v1/`, schema in `openapi.yaml`)

| Route | Purpose |
|---|---|
| `POST /api/v1/broll/jobs` | JSON body with exactly one of `audio_url`, `script`, `scenes`. Returns **202** `{job_id}`. Optional `Idempotency-Key` header and `callback_url`. |
| `POST /api/v1/broll/jobs/upload` | Multipart upload of mp3/wav/m4a (`file`) plus `options` (JSON string with the same fields). |
| `GET /api/v1/jobs/{job_id}` | `status` (`queued`/`running`/`succeeded`/`failed`), `progress` 0-100, `result` links or `error`. |
| `GET /api/v1/files/{key}` | Download outputs when using local storage (S3 mode returns presigned links instead). |
| `GET /health`, `GET /ready` | Liveness; readiness checks database, storage and ffmpeg. |

**Outputs per job:** `video_16x9.mp4` / `video_9x16.mp4` / `video_1x1.mp4` (H.264/AAC, 30 fps, 1920x1080 / 1080x1920 /
1080x1080), `captions.srt`, `timeline.json` (per scene: text, times, clip, source, licence, attribution, AI flag,
reason, relevance score), `manifest.json` (providers and versions, settings, seed, timings, cost estimate, warnings,
rights, automated QA results).

**Callbacks:** if `callback_url` is set, the final status is POSTed with header
`X-IncuBrix-Signature: sha256=<HMAC-SHA256(body, CALLBACK_SECRET)>`.

### Error format and codes
`{"error": {"code", "message", "retryable", "details"}}`

| Code | Meaning |
|---|---|
| `INVALID_REQUEST` | Body failed validation (422) |
| `EMPTY_INPUT` | Empty script/scenes/audio (400) |
| `UNAUTHORIZED` / `RATE_LIMITED` | Missing token (401) / too many requests (429) |
| `NOT_FOUND` / `JOB_NOT_FOUND` | Unknown route / job (404) |
| `IDEMPOTENCY_KEY_REUSED` | Same key, different request (409) |
| `UNSUPPORTED_MEDIA_TYPE` | Not mp3/wav/m4a, or unreadable (415) |
| `AUDIO_TOO_LONG` | Longer than `MAX_AUDIO_SECONDS` (default 600) |
| `SILENT_AUDIO` | No audible signal |
| `NO_SPEECH_DETECTED` | Music-only or unintelligible audio |
| `DOWNLOAD_FAILED` / `URL_NOT_ALLOWED` | URL fetch failed / blocked (non-http(s) or private host) |
| `PROVIDER_UNAVAILABLE` | STT/TTS failed |
| `MEDIA_PROCESSING_FAILED` | ffmpeg/ffprobe failed |
| `INTERNAL_ERROR` | Unexpected (retryable) |

Warnings (in `manifest.json` and the job result) include `PROVIDER_FAILED`, `PROVIDER_DISABLED_FOR_JOB`,
`FALLBACK_CARD_USED`, `CLIP_LOOPED`, `CORRUPT_OR_FAILED_DOWNLOAD`, `NAMED_ENTITY_GENERIC_FOOTAGE`,
`SENSITIVE_TOPIC_RESPECTFUL_FOOTAGE`, `AVOID_PEOPLE_BEST_EFFORT`, `PLANNER_LLM_FALLBACK`, `QA_CHECK_FAILED`.

## How decisions are made
* **Scenes follow the voice.** Audio: word timestamps are grouped on sentence ends and long pauses; long sentences split at
  commas; micro-scenes (< `MIN_SCENE_SECONDS`) merge into a neighbour; boundaries sit mid-pause so every second is covered.
  Text: each phrase is synthesised separately, so scene times are exact.
* **Meaning, not keywords.** The planner reads the surrounding lines to pick the sense of *bank, cloud, mouse, python,
  value*; turns abstract lines into visual metaphors; turns statistics into chart footage (the number goes in captions);
  strips named people/brands from searches; switches sensitive stories to calm, people-free visuals.
* **Selection.** Candidates from all providers are filtered (licence commercial, not watermarked, not already used, no
  `avoid` tags), scored 1-5, and the best is downloaded and verified. If nothing reaches `MIN_RELEVANCE` an animated
  title card is used instead of a nonsense match, and a warning says so.
* **Resilience.** A provider that fails twice in a job is skipped for the rest of it; if every provider is down the job
  still finishes with title cards.
* **Idempotency.** Same `Idempotency-Key` + same body returns the same job (header `Idempotent-Replay: true`); same key
  with a different body is `409`.

## Honest status against the brief
See `REPORT.md` for measured numbers and `HARD_CASES.md` for generated evidence. Not done or not verified:
real speech-to-text (adapter written, never run here), live Pexels/Pixabay calls, Docker/compose (written, not run),
a deployed demo URL, measured relevance with real footage and human ratings, the Advanced items except scene lists
(second/generative source, swap-a-clip, cross-source colour matching), and all Outstanding items.
