# REPORT: Script and Voiceover to B-roll Video Engine

*Draft written from what was built and measured in a 1-vCPU sandbox. Sections marked **[you]** need your own input
before submission. Do not claim anything here that you have not re-run and can explain.*

## 1. Approach and why
**Pipeline.** Input -> narration + timed scenes -> per-scene search queries -> licence-filtered footage -> per-scene
normalised segments -> concat + narration + captions -> automated QA -> storage. One job = one thread-pool task; state in SQLite.

| Decision | Alternatives considered | Why this one |
|---|---|---|
| Text input: synthesise **each phrase separately** and concatenate | One TTS call, then align with STT | Scene times are exact by construction, no alignment error |
| Audio input: STT **word timestamps** grouped on sentence ends/pauses | Fixed-length chunks | Cuts land on phrase boundaries, which is a must-have |
| Planner = **rules first**, optional LLM on top | LLM only | Works with no key, deterministic, and safety rules (sensitive topics, named people) can never be overridden by a model |
| Fallback **title card** when relevance is low | Always use best match | A visible, flagged card is safer than a nonsense clip |
| Normalise every clip to a **cached segment** | One big ffmpeg graph | Constant format/fps, cheap re-use (and a base for swap-a-clip) |
| All providers behind adapters + mock | Direct calls | Required by the brief; also made failure tests possible |

## 2. What works (tested)
- 38 automated tests pass (unit, API contract, end-to-end with real ffmpeg + espeak-ng speech, S3 storage against an emulator).
- Both input types (upload and script/scene list) produce mp4s in 16:9, 9:16 and 1:1; automated QA per file checks
  H.264/AAC, 30 fps, resolution, audio/video duration match, no black or frozen frames.
- No clip used twice in a video; every clip has source, licence, attribution and AI flag in `timeline.json`.
- Provider failure: one provider down -> other used; all down -> title cards; job still finishes with warnings.
- Hard cases (see `HARD_CASES.md`): abstract lines, statistics, named person/brand, bank/cloud/mouse/python/value,
  sad news, 9:16, empty script, wrong file type, silent audio, music-only, corrupt audio, two concurrent users.
- Integration Standard: Compose file, OpenAPI 3.1 file checked against the live schema, 202 jobs + progress + signed
  callback, idempotency keys, JSON errors, env config, upload/URL in and S3 out, JSON logs with job_id and correlation id,
  `/health` `/ready`, manifest, batch runner.

## 3. What does not work or is not verified (be honest in the form)
- **Real speech-to-text never ran** (no model download in the sandbox). Audio tests use a mock STT that reads a transcript
  hint; it does not listen. Must-have 1 (audio) is therefore *Partial* until you run `faster_whisper`.
- **Pexels/Pixabay adapters never ran against the live APIs.** Run `scripts/check_providers.py` with keys.
- **Relevance is a lexical heuristic** (query words vs provider title/tags), not a vision model. With the mock provider it
  is inflated by design. No human ratings exist, so Core "average >= 3.5" and Outstanding are **unverified**.
- **Docker / Compose / MinIO not run** (no Docker in the sandbox). S3 code is tested against an emulator only.
- **No demo URL deployed.** **[you]**
- "Avoid people's faces" is best-effort (provider tags); faces cannot be ruled out from tags.
- 9:16 uses a blurred-background fit so edge subjects stay visible, but the whole frame is smaller; no subject detection.
- Planner is English-only without the LLM adapter (Hindi narration works through espeak; its scenes got a generic query).
- A 5-minute and a 10-minute voiceover were **not** tested. **[you]**
- Advanced: scene-list input done; second/generative source with a written rule, swap-a-clip and cross-source colour
  matching are **not** done. Outstanding: none done.

## 4. Numbers (Metrics tab)
Measured on a **1 vCPU sandbox, mock footage (no network), espeak TTS**, script of 70.8 s narration, 14 scenes, 16:9:

| Metric | Result |
|---|---|
| Turnaround, 60-70 s narration | **97.5 s cold, 73.4 s warm** (render 88 s / 72 s; footage 8 s / 0 s). Real footage adds download time. The final captioned re-encode dominates; more cores will cut this a lot. |
| Short job (2 scenes, ~5 s) | about 7-12 s |
| Cost per minute of video | compute estimate about **$0.0027 per 70.8 s** at the configured $0.10/h; Pexels/Pixabay free; espeak free; LLM $0 (not used). Real TTS/LLM costs are **not measured**. |
| Coverage | 100% of narration time is covered by a clip or title card by construction; share rated >= 3 by a human is **not measured** |
| Relevance | **not measured** (see above) |
| Reliability | 18/18 valid sample inputs rendered; 5/5 invalid inputs refused with the right code; repeat-clip rate 0 (asserted in tests) |
| Resources | peak memory and GPU **not measured** (no GPU used) |
| Concurrency | 2 simultaneous jobs tested (`MAX_WORKERS=2`); jobs per server **not measured** |

## 5. Next steps (in order of marks)
1. Run real STT and real Pexels/Pixabay; rate 10 varied videos yourself; fix the worst matches. (Core)
2. Deploy a demo URL with a token and rate limit; run `docker compose up` and `make test` for real. (Must-have 8)
3. Add a second source with a measurable choosing rule, store the reason in `timeline.json`; implement swap-a-clip using
   the existing segment cache; add colour/brightness matching. (Advanced)
4. Add a vision-language relevance scorer and compare it with your own ratings; Hindi/Tamil planning. (Outstanding)
