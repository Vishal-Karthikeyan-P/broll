import io

import pytest

from .conftest import SHORT


@pytest.fixture
def client(make_client):
    return make_client(no_worker=True)


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200 and all(r.json()["checks"].values())


def test_correlation_id_is_echoed(client):
    assert client.get("/health", headers={"X-Correlation-Id": "abc123"}).headers["X-Correlation-Id"] == "abc123"
    assert client.get("/health").headers["X-Correlation-Id"]


def assert_error_shape(body, code=None):
    e = body["error"]
    assert set(e) == {"code", "message", "retryable", "details"}
    assert e["code"] == e["code"].upper()
    if code:
        assert e["code"] == code


def test_empty_script_is_a_clear_400(client):
    r = client.post("/api/v1/broll/jobs", json={"script": "   "})
    assert r.status_code == 400
    assert_error_shape(r.json(), "EMPTY_INPUT")


def test_no_input_and_two_inputs_are_rejected(client):
    assert_error_shape(client.post("/api/v1/broll/jobs", json={}).json(), "EMPTY_INPUT")
    r = client.post("/api/v1/broll/jobs", json={"script": "Hello there my friend.", "audio_url": "http://x/a.mp3"})
    assert r.status_code == 422
    assert_error_shape(r.json(), "INVALID_REQUEST")


def test_bad_values_are_validation_errors(client):
    r = client.post("/api/v1/broll/jobs", json={"script": "Hello there my friend.", "aspect_ratios": ["4:3"]})
    assert r.status_code == 422
    assert_error_shape(r.json(), "INVALID_REQUEST")
    r = client.post("/api/v1/broll/jobs", json={"script": "Hello there my friend.", "surprise": 1})
    assert r.status_code == 422


def test_wrong_file_type_upload_is_415(client):
    r = client.post("/api/v1/broll/jobs/upload", files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 hello"), "application/pdf")})
    assert r.status_code == 415
    assert_error_shape(r.json(), "UNSUPPORTED_MEDIA_TYPE")


def test_unknown_job_and_route(client):
    r = client.get("/api/v1/jobs/job_nope")
    assert r.status_code == 404
    assert_error_shape(r.json(), "JOB_NOT_FOUND")
    assert_error_shape(client.get("/api/v1/nothing").json(), "NOT_FOUND")


def test_idempotency_same_key_same_job_and_conflict(client):
    body = {"script": SHORT}
    h = {"Idempotency-Key": "key-1"}
    a = client.post("/api/v1/broll/jobs", json=body, headers=h)
    b = client.post("/api/v1/broll/jobs", json=body, headers=h)
    assert a.status_code == b.status_code == 202
    assert a.json()["job_id"] == b.json()["job_id"]
    assert a.headers["Idempotent-Replay"] == "false" and b.headers["Idempotent-Replay"] == "true"
    c = client.post("/api/v1/broll/jobs", json={"script": "A different request entirely."}, headers=h)
    assert c.status_code == 409
    assert_error_shape(c.json(), "IDEMPOTENCY_KEY_REUSED")
    d = client.post("/api/v1/broll/jobs", json=body, headers={"Idempotency-Key": "key-2"})
    assert d.json()["job_id"] != a.json()["job_id"]


def test_bearer_token_protects_the_api(make_client):
    c = make_client(api_token="s3cret", no_worker=True)
    assert c.get("/health").status_code == 200
    r = c.post("/api/v1/broll/jobs", json={"script": SHORT})
    assert r.status_code == 401
    assert_error_shape(r.json(), "UNAUTHORIZED")
    assert c.post("/api/v1/broll/jobs", json={"script": SHORT}, headers={"Authorization": "Bearer s3cret"}).status_code == 202


def test_rate_limit(make_client):
    c = make_client(rate_limit_per_minute=2, no_worker=True)
    codes = [c.post("/api/v1/broll/jobs", json={"script": ""}).status_code for _ in range(3)]
    assert codes[:2] == [400, 400] and codes[2] == 429
    assert_error_shape(c.post("/api/v1/broll/jobs", json={"script": ""}).json(), "RATE_LIMITED")
