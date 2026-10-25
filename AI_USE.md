# AI tools used

> **Candidate: review and edit this file so it is true for you.** The brief disqualifies undisclosed AI use and requires
> that you can explain and change every part of the code in the live session.

| Tool | What it was used for |
|---|---|
| Claude (Anthropic), via chat | Generated the first version of the codebase from the assessment brief: API, job runner, pipeline, planner rules, render/QA code, tests, Docker files and documentation drafts. Also debugged failures found when running the tests and batch (for example a store bug, ffmpeg temp-file naming, caption sizing). |
| [add any other tool you use] | [what for] |

## How the output was checked
- All tests were run (`pytest`), plus a batch of hard-case inputs through the live HTTP API, plus a visual check of
  rendered frames in three aspect ratios. This found and fixed real bugs (see commit history).
- **[Candidate to add]** which files you read line by line, what you changed yourself, and what you can already explain.

## Things the AI could not verify (so you must)
- Live Pexels / Pixabay behaviour, real speech-to-text, Docker Compose, MinIO, and any deployed URL.
