import os
import subprocess
import time

os.environ["BROLL_NO_AUTOSTART"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.pipeline.footage import MockProvider


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def _make(**kw):
        overrides = dict(data_dir=str(tmp_path / "data"), rate_limit_per_minute=0, allow_private_urls=True)
        providers = kw.pop("providers", None)
        no_worker = kw.pop("no_worker", False)
        overrides.update(kw)
        app = create_app(load_settings(**overrides), providers=providers)
        if no_worker:  # API-contract tests: accept jobs but do not render them
            app.state.worker.submit = lambda job_id: None
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def wait_job(client, job_id, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v1/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.5)
    raise TimeoutError(job_id)


def fetch_json(client, url):
    from urllib.parse import urlparse
    r = client.get(urlparse(url).path)
    assert r.status_code == 200
    return r.json()


def make_audio(path, text, voice="en-gb+f3"):
    """Make a real speech file with espeak-ng (wav, or mp3/m4a via ffmpeg)."""
    wav = str(path) + ".tmp.wav"
    subprocess.run(["espeak-ng", "-v", voice, "-w", wav, text], check=True)
    if str(path).endswith(".wav"):
        os.replace(wav, path)
    else:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, str(path)], check=True)
        os.remove(wav)
    with open(os.path.splitext(str(path))[0] + ".txt", "w") as f:
        f.write(text)
    return path


SHORT = "Saving money starts with one small habit. Put it in the bank every single month."
