"""Run a folder (or one file) of test inputs against the API and write every result to one folder.

  python -m cli.batch_runner --api http://localhost:8000 --input samples --out results [--token T]

Input types:  .txt -> script   .json -> job request body   .mp3/.wav/.m4a -> audio upload
              (an audio file's sibling .txt is sent as transcript_hint for the mock STT adapter)
Anything else is uploaded as-is so you can see the API's rejection.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

AUDIO = {".mp3", ".wav", ".m4a"}


def collect(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(p for p in path.iterdir() if p.is_file())
    audio_stems = {p.stem for p in files if p.suffix.lower() in AUDIO}
    # a .txt that belongs to an audio file is a transcript hint, not a script job
    return [p for p in files if not (p.suffix == ".txt" and p.stem in audio_stems)]


def submit(c: httpx.Client, api: str, p: Path, headers: dict) -> httpx.Response:
    ext = p.suffix.lower()
    if ext == ".txt":
        return c.post(f"{api}/api/v1/broll/jobs", json={"script": p.read_text(encoding="utf-8")}, headers=headers)
    if ext == ".json":
        return c.post(f"{api}/api/v1/broll/jobs", json=json.loads(p.read_text(encoding="utf-8")), headers=headers)
    hint = p.with_suffix(".txt")
    data = {"options": "{}"}
    if hint.exists():
        data["transcript_hint"] = hint.read_text(encoding="utf-8")
    with open(p, "rb") as f:
        return c.post(f"{api}/api/v1/broll/jobs/upload", files={"file": (p.name, f)}, data=data, headers=headers)


def download(c: httpx.Client, url: str, dest: Path, headers: dict) -> None:
    r = c.get(url, headers=headers, follow_redirects=True)
    r.raise_for_status()
    dest.write_bytes(r.content)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--token", default=os.environ.get("API_TOKEN", ""))
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--no-videos", action="store_true", help="skip downloading mp4 files")
    a = ap.parse_args()
    api = a.api.rstrip("/")
    headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=60) as c:
        for p in collect(Path(a.input)):
            name = p.stem if p.suffix.lower() != ".pdf" else p.name
            folder = out / p.name.replace(".", "_")
            folder.mkdir(exist_ok=True)
            t0 = time.time()
            row = {"input": p.name, "job_id": "", "status": "", "error_code": "", "seconds": "", "scenes": "",
                   "qa_passed": "", "warnings": "", "fallback_cards": ""}
            r = submit(c, api, p, headers)
            if r.status_code != 202:  # rejected up front
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                row.update(status=f"rejected_http_{r.status_code}", error_code=body.get("error", {}).get("code", ""),
                           seconds=round(time.time() - t0, 1))
                (folder / "status.json").write_text(json.dumps({"http_status": r.status_code, "body": body}, indent=2))
                rows.append(row)
                print(f"{p.name:32} rejected {r.status_code} {row['error_code']}")
                continue
            job_id = r.json()["job_id"]
            job = {}
            while time.time() - t0 < a.timeout:
                job = c.get(f"{api}/api/v1/jobs/{job_id}", headers=headers).json()
                if job["status"] in ("succeeded", "failed"):
                    break
                time.sleep(1)
            row.update(job_id=job_id, status=job.get("status", "timeout"), seconds=round(time.time() - t0, 1))
            (folder / "status.json").write_text(json.dumps(job, indent=2))
            if job.get("status") == "succeeded":
                res = job["result"]
                row.update(scenes=res["scene_count"], qa_passed=res["qa_passed"],
                           warnings=len(res["warnings"]),
                           fallback_cards=sum(1 for w in res["warnings"] if w["code"] == "FALLBACK_CARD_USED"))
                o = res["outputs"]
                download(c, o["timeline"], folder / "timeline.json", headers)
                download(c, o["manifest"], folder / "manifest.json", headers)
                if o.get("captions_srt"):
                    download(c, o["captions_srt"], folder / "captions.srt", headers)
                if not a.no_videos:
                    for ratio, url in o["videos"].items():
                        download(c, url, folder / f"video_{ratio.replace(':', 'x')}.mp4", headers)
            elif job.get("error"):
                row["error_code"] = job["error"]["code"]
            rows.append(row)
            print(f"{p.name:32} {row['status']:10} {row['error_code']:22} {row['seconds']}s scenes={row['scenes']}")
    (out / "summary.json").write_text(json.dumps(rows, indent=2))
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["input"])
        w.writeheader()
        w.writerows(rows)
    ok = sum(1 for r in rows if r["status"] == "succeeded")
    print(f"\n{ok}/{len(rows)} succeeded. Results in {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
