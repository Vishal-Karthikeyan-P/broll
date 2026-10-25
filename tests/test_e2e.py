"""End-to-end: real ffmpeg, real espeak-ng speech, mock footage. No API keys needed."""
import hashlib
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.pipeline.footage import MockProvider
from app.pipeline.render import qa_check
from app.worker import sign

from .conftest import SHORT, fetch_json, make_audio, wait_job


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def download(client, url, tmp_path, name):
    from urllib.parse import urlparse
    r = client.get(urlparse(url).path)
    assert r.status_code == 200
    p = tmp_path / name
    p.write_bytes(r.content)
    return str(p)


def check_outputs(client, job, tmp_path, ratios=("16:9",)):
    assert job["status"] == "succeeded", job.get("error")
    out = job["result"]["outputs"]
    tl = fetch_json(client, out["timeline"])
    mf = fetch_json(client, out["manifest"])
    # must-have 2: scenes cover the narration, in order, no gaps
    sc = tl["scenes"]
    assert sc[0]["start"] == 0 and abs(sc[-1]["end"] - tl["duration_s"]) < 0.01
    for a, b in zip(sc, sc[1:]):
        assert abs(a["end"] - b["start"]) < 0.01
    # must-have 3: every clip has licence data and allows commercial use, nothing watermarked
    for s in sc:
        c = s["clip"]
        assert c["licence"] and c["licence_url"] and c["attribution"] and c["commercial_use"] and not c["watermarked"]
        assert "ai_generated" in c and s["reason"] and s["relevance_score"] >= 1
    # must-have 5: no clip used twice
    ids = [(s["clip"]["provider"], s["clip"]["id"]) for s in sc if not s["clip"]["fallback_title_card"]]
    assert len(ids) == len(set(ids))
    # must-have 4: independent file checks
    for r in ratios:
        p = download(client, out["videos"][r], tmp_path, f"v_{r.replace(':', 'x')}.mp4")
        info = probe(p)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert v["codec_name"] == "h264" and a["codec_name"] == "aac" and v["r_frame_rate"] == "30/1"
        w, h = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[r]
        assert (v["width"], v["height"]) == (w, h)
        assert abs(float(info["format"]["duration"]) - tl["duration_s"]) < 0.25
        assert qa_check(p, tl["duration_s"], r)["passed"]
    # manifest has what the Integration Standard asks for
    for k in ("providers", "settings", "seed", "timings_s", "cost_estimate_usd", "warnings", "rights", "versions", "qa"):
        assert k in mf
    assert mf["rights"]["all_clips_commercial_use"] is True
    return tl, mf


def test_script_job_two_aspect_ratios(client, tmp_path):
    r = client.post("/api/v1/broll/jobs", json={"script": SHORT, "aspect_ratios": ["16:9", "9:16"]})
    assert r.status_code == 202
    job = wait_job(client, r.json()["job_id"])
    tl, mf = check_outputs(client, job, tmp_path, ("16:9", "9:16"))
    assert job["progress"] == 100
    assert job["result"]["outputs"]["captions_srt"]
    srt = client.get(job["result"]["outputs"]["captions_srt"].split("8000")[-1]).text
    assert "-->" in srt


def test_audio_upload_job(client, tmp_path):
    audio = make_audio(tmp_path / "vo.mp3", "Cloud computing lets teams store data on remote servers. It saves money every month.")
    with open(audio, "rb") as f:
        r = client.post("/api/v1/broll/jobs/upload", files={"file": ("vo.mp3", f, "audio/mpeg")},
                        data={"options": json.dumps({}), "transcript_hint": open(str(tmp_path / "vo.txt")).read()})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job_id"])
    tl, _ = check_outputs(client, job, tmp_path)
    assert any("server" in (s["query_used"] or "") for s in tl["scenes"])  # 'cloud' read as computing, not sky


def test_scene_list_with_visual_hints(client, tmp_path):
    body = {"scenes": [{"text": "Meet the new way to make videos.", "visual_hint": "creator editing video"},
                       {"text": "It works in minutes, not hours.", "visual_hint": "stopwatch"}]}
    job = wait_job(client, client.post("/api/v1/broll/jobs", json=body).json()["job_id"])
    tl, _ = check_outputs(client, job, tmp_path)
    assert tl["scenes"][0]["queries"][0].startswith("creator")
    assert len(tl["scenes"]) == 2  # scene list is honoured one-to-one


def test_one_provider_down_still_finishes_with_another(make_client, tmp_path):
    down = MockProvider(fail=True)
    down.name = "stock_library_down"  # distinct name, like real providers
    c = make_client(providers=[down, MockProvider()])
    job = wait_job(c, c.post("/api/v1/broll/jobs", json={"script": SHORT}).json()["job_id"])
    _, mf = check_outputs(c, job, tmp_path)
    codes = [w["code"] for w in mf["warnings"]]
    assert "PROVIDER_FAILED" in codes and "PROVIDER_DISABLED_FOR_JOB" in codes
    assert mf["rights"]["fallback_title_cards"] == 0


def test_all_providers_down_uses_fallback_cards_and_still_finishes(make_client, tmp_path):
    c = make_client(providers=[MockProvider(fail=True)])
    job = wait_job(c, c.post("/api/v1/broll/jobs", json={"script": SHORT}).json()["job_id"])
    _, mf = check_outputs(c, job, tmp_path)
    assert "FALLBACK_CARD_USED" in [w["code"] for w in mf["warnings"]]
    assert mf["rights"]["fallback_title_cards"] >= 1


def test_silent_audio_fails_clearly(client, tmp_path):
    p = tmp_path / "silence.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3", str(p)], check=True)
    with open(p, "rb") as f:
        r = client.post("/api/v1/broll/jobs/upload", files={"file": ("silence.wav", f, "audio/wav")})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "SILENT_AUDIO"
    assert set(job["error"]) == {"code", "message", "retryable", "details"}


def test_music_only_audio_reports_no_speech(client, tmp_path):
    p = tmp_path / "music.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", str(p)], check=True)
    with open(p, "rb") as f:
        r = client.post("/api/v1/broll/jobs/upload", files={"file": ("music.mp3", f, "audio/mpeg")})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "NO_SPEECH_DETECTED"


def test_corrupt_audio_is_rejected(client, tmp_path):
    p = tmp_path / "broken.mp3"
    p.write_bytes(b"this is not audio at all" * 50)
    with open(p, "rb") as f:
        r = client.post("/api/v1/broll/jobs/upload", files={"file": ("broken.mp3", f, "audio/mpeg")})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_audio_longer_than_limit_is_rejected(make_client, tmp_path):
    c = make_client(max_audio_seconds=3)
    audio = make_audio(tmp_path / "long.wav", "This narration is intentionally much longer than the three second limit that we configured for this test.")
    with open(audio, "rb") as f:
        r = c.post("/api/v1/broll/jobs/upload", files={"file": ("long.wav", f, "audio/wav")})
    job = wait_job(c, r.json()["job_id"])
    assert job["error"]["code"] == "AUDIO_TOO_LONG"


def test_two_users_at_the_same_time(client, tmp_path):
    a = client.post("/api/v1/broll/jobs", json={"script": "The first job talks about saving money every month."}).json()["job_id"]
    b = client.post("/api/v1/broll/jobs", json={"script": "The second job talks about growing a small business."}).json()["job_id"]
    ja, jb = wait_job(client, a), wait_job(client, b)
    ta, _ = check_outputs(client, ja, tmp_path / "..")
    tb, _ = check_outputs(client, jb, tmp_path / "..")
    assert ja["result"]["outputs"]["videos"] != jb["result"]["outputs"]["videos"]


def test_signed_callback_is_delivered(client, tmp_path):
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got.update(body=body, sig=self.headers.get("X-IncuBrix-Signature"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    r = client.post("/api/v1/broll/jobs", json={"script": SHORT, "callback_url": f"http://127.0.0.1:{srv.server_port}/hook"})
    wait_job(client, r.json()["job_id"])
    import time
    for _ in range(40):
        if got:
            break
        time.sleep(0.25)
    srv.shutdown()
    assert got and got["sig"] == sign("change-me", got["body"])
    assert json.loads(got["body"])["status"] == "succeeded"


def test_avoid_list_filters_clips_by_metadata(make_client, tmp_path):
    class Tagged(MockProvider):
        def search(self, query, orientation, limit):
            out = super().search(query, orientation, limit)
            out[0].tags = out[0].tags + ["wine"]  # best candidate carries an avoided tag
            return out

    c = make_client(providers=[Tagged()])
    body = {"script": "Celebrate the launch with the whole team tonight.", "avoid": ["alcohol"]}
    job = wait_job(c, c.post("/api/v1/broll/jobs", json=body).json()["job_id"])
    tl, _ = check_outputs(c, job, tmp_path)
    assert all("variant 1" not in s["clip"]["title"] for s in tl["scenes"])
