"""Background job runner (thread pool) and signed callbacks."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .errors import ApiError
from .logging_setup import correlation_id_var, job_id_var, log
from .pipeline import media
from .pipeline.run import Ctx, run_pipeline

logger = logging.getLogger("broll.worker")


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Worker:
    def __init__(self, store, ctx: Ctx):
        self.store, self.ctx = store, ctx
        self.pool = ThreadPoolExecutor(max_workers=ctx.settings.max_workers, thread_name_prefix="job")

    def submit(self, job_id: str) -> None:
        self.pool.submit(self._run, job_id)

    def resume_incomplete(self) -> None:
        for j in self.store.incomplete():
            self.store.update(j["job_id"], status="queued", progress=0, stage="requeued after restart")
            self.submit(j["job_id"])

    def _run(self, job_id: str) -> None:
        job = self.store.get(job_id)
        job_id_var.set(job_id)
        correlation_id_var.set(job.get("correlation_id"))
        self.store.update(job_id, status="running", progress=1, stage="starting")
        started = time.time()
        log(logger, logging.INFO, "job started")
        try:
            def progress(pct: int, stage: str) -> None:
                self.store.update(job_id, progress=min(int(pct), 99), stage=stage)

            result = run_pipeline(job, self.ctx, progress)
            self.store.update(job_id, status="succeeded", progress=100, stage="done", result=result)
            log(logger, logging.INFO, "job succeeded", seconds=round(time.time() - started, 2))
        except ApiError as e:
            self.store.update(job_id, status="failed", stage="failed", error=e.body()["error"])
            log(logger, logging.WARNING, "job failed", code=e.code, message=e.message)
        except Exception as e:  # unexpected: record and keep the worker alive
            logger.exception("job crashed")
            self.store.update(job_id, status="failed", stage="failed",
                              error={"code": "INTERNAL_ERROR", "message": f"{e.__class__.__name__}",
                                     "retryable": True, "details": {}})
        finally:
            self._callback(job_id)

    def _callback(self, job_id: str) -> None:
        job = self.store.get(job_id)
        url = job["request"].get("callback_url")
        if not url:
            return
        s = self.ctx.settings
        body = json.dumps({"job_id": job_id, "status": job["status"], "result": job["result"],
                           "error": job["error"]}).encode()
        headers = {"Content-Type": "application/json", "X-IncuBrix-Signature": sign(s.callback_secret, body),
                   "X-Correlation-Id": job.get("correlation_id") or ""}
        for attempt in range(3):
            try:
                media.check_url(url, s.allow_private_urls)
                r = httpx.post(url, content=body, headers=headers, timeout=s.http_timeout)
                if r.status_code < 300:
                    log(logger, logging.INFO, "callback delivered", url=url)
                    return
            except Exception as e:
                log(logger, logging.WARNING, "callback attempt failed", attempt=attempt + 1, error=str(e)[:120])
            time.sleep(0.5 * (attempt + 1))
