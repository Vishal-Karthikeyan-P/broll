from app.store import JobStore


def test_finished_job_can_be_read_back(tmp_path):
    s = JobStore(str(tmp_path / "j.db"))
    job, _ = s.create({"script": "hi there"}, None, "h", None)
    s.update(job["job_id"], status="succeeded", progress=100, result={"outputs": {"a": 1}})
    got = s.get(job["job_id"])
    assert got["result"] == {"outputs": {"a": 1}} and got["error"] is None
    s.update(job["job_id"], status="failed", error={"code": "X", "message": "m", "retryable": False, "details": {}})
    assert s.get(job["job_id"])["error"]["code"] == "X"
