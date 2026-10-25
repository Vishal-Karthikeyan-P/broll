"""IncuBrix Script/Voiceover -> B-roll video service (HTTP API)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, load_settings
from .errors import ApiError
from .logging_setup import correlation_id_var, log, setup_logging
from .models import CreateJobRequest, JobCreated, JobStatus
from .pipeline.footage import build_providers
from .pipeline.planner import build_planner
from .pipeline.run import Ctx
from .pipeline.stt import build_stt
from .pipeline.tts import build_tts
from .storage import build_storage
from .store import JobStore
from .worker import Worker

logger = logging.getLogger("broll.api")
UPLOAD_EXTS = {".mp3", ".wav", ".m4a"}


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


ERR = {400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
       415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}}


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute, self.hits, self.lock = per_minute, defaultdict(deque), threading.Lock()

    def check(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def create_app(settings: Settings | None = None, *, providers=None, stt=None, tts=None, planner=None) -> FastAPI:
    s = settings or load_settings()
    setup_logging(s.log_level)
    os.makedirs(s.data_dir, exist_ok=True)
    store = JobStore(s.db_path)
    storage = build_storage(s)
    ctx = Ctx(s, stt or build_stt(s), tts or build_tts(s), planner or build_planner(s),
              providers if providers is not None else build_providers(s), storage)
    worker = Worker(store, ctx)
    limiter = RateLimiter(s.rate_limit_per_minute)

    app = FastAPI(title="IncuBrix B-roll Engine", version=s.app_version,
                  description="Turns a voiceover or script into a finished, licence-clean B-roll video.")
    app.state.settings, app.state.store, app.state.worker, app.state.ctx = s, store, worker, ctx

    @app.on_event("startup")
    def _resume():
        worker.resume_incomplete()

    # ---------- middleware: correlation id, auth, rate limit, request log ----------
    @app.middleware("http")
    async def mw(request: Request, call_next):
        cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex[:16]
        correlation_id_var.set(cid)
        t0 = time.time()
        path = request.url.path
        try:
            if path.startswith("/api/v1/") and not path.startswith(("/api/v1/files/", "/api/v1/health", "/api/v1/ready")):
                if s.api_token and request.headers.get("Authorization") != f"Bearer {s.api_token}":
                    raise ApiError("UNAUTHORIZED", "Missing or invalid bearer token.", 401)
                if request.method == "POST" and not limiter.check(request.client.host if request.client else "anon"):
                    raise ApiError("RATE_LIMITED", "Too many requests.", 429, retryable=True,
                                   details={"limit_per_minute": s.rate_limit_per_minute})
            response = await call_next(request)
        except ApiError as e:
            response = JSONResponse(e.body(), status_code=e.status)
        response.headers["X-Correlation-Id"] = cid
        log(logger, logging.INFO, "request", method=request.method, path=path, status=response.status_code,
            ms=round((time.time() - t0) * 1000))
        return response

    # ---------- error handlers ----------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse(e.body(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        errs = json.loads(json.dumps(e.errors(), default=str))
        return JSONResponse(ApiError("INVALID_REQUEST", "Request body failed validation.", 422,
                                     details={"errors": errs}).body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = "NOT_FOUND" if e.status_code == 404 else "INVALID_REQUEST"
        return JSONResponse(ApiError(code, str(e.detail), e.status_code).body(), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception):
        logger.exception("unhandled error")
        return JSONResponse(ApiError("INTERNAL_ERROR", "Unexpected server error.", 500, retryable=True).body(), status_code=500)

    # ---------- helpers ----------
    def _accept(req_dict: dict, idem: Optional[str], rhash: str, request: Request, input_path: str | None = None):
        job, created = store.create(req_dict, idem, rhash, correlation_id_var.get(), input_path)
        if created:
            worker.submit(job["job_id"])
        body = JobCreated(job_id=job["job_id"], status=job["status"],
                          links={"self": f"/api/v1/jobs/{job['job_id']}"})
        return JSONResponse(body.model_dump(), status_code=202,
                            headers={"Location": f"/api/v1/jobs/{job['job_id']}",
                                     "Idempotent-Replay": "false" if created else "true"})

    # ---------- routes ----------
    @app.post("/api/v1/broll/jobs", status_code=202, response_model=JobCreated, responses=ERR, tags=["jobs"],
              summary="Create a B-roll job from audio_url, script or scenes")
    def create_job(req: CreateJobRequest, request: Request,
                   idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
        req.input_kind()
        d = req.model_dump()
        return _accept(d, idempotency_key, hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest(), request)

    @app.post("/api/v1/broll/jobs/upload", status_code=202, response_model=JobCreated, responses=ERR, tags=["jobs"],
              summary="Create a job from an uploaded audio file (mp3, wav, m4a)")
    def create_job_upload(request: Request, file: UploadFile = File(...), options: str = Form("{}"),
                          transcript_hint: Optional[str] = Form(None, description="Used only by the mock STT adapter."),
                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
        name = os.path.basename(file.filename or "audio")
        ext = os.path.splitext(name)[1].lower()
        if ext not in UPLOAD_EXTS:
            raise ApiError("UNSUPPORTED_MEDIA_TYPE", f"Unsupported file type '{ext or 'none'}'. Use mp3, wav or m4a.", 415)
        try:
            req = CreateJobRequest(**json.loads(options or "{}"))
        except (ValueError, TypeError) as e:
            raise ApiError("INVALID_REQUEST", f"options must be a JSON object matching the job schema: {e}", 422)
        req.input_kind(has_upload=True)
        folder = os.path.join(s.data_dir, "uploads", uuid.uuid4().hex[:12])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "audio" + ext)
        h, size = hashlib.sha256(), 0
        with open(path, "wb") as out:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > s.max_download_mb * 1024 * 1024:
                    shutil.rmtree(folder, ignore_errors=True)
                    raise ApiError("INVALID_REQUEST", f"File larger than {s.max_download_mb} MB.", 413)
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            shutil.rmtree(folder, ignore_errors=True)
            raise ApiError("EMPTY_INPUT", "Uploaded file is empty.", 400)
        if transcript_hint:
            with open(os.path.join(folder, "audio.txt"), "w", encoding="utf-8") as f:
                f.write(transcript_hint)
        d = req.model_dump()
        rhash = hashlib.sha256((json.dumps(d, sort_keys=True) + h.hexdigest()).encode()).hexdigest()
        resp = _accept(d, idempotency_key, rhash, request, input_path=path)
        if resp.headers.get("Idempotent-Replay") == "true":
            shutil.rmtree(folder, ignore_errors=True)  # duplicate request: don't keep a second copy
        return resp

    @app.get("/api/v1/jobs/{job_id}", response_model=JobStatus, responses={404: {"model": ErrorResponse}}, tags=["jobs"],
             summary="Job status, progress and result links")
    def get_job(job_id: str):
        j = store.get(job_id)
        if not j:
            raise ApiError("JOB_NOT_FOUND", f"No job '{job_id}'.", 404)
        return JobStatus(job_id=j["job_id"], status=j["status"], progress=j["progress"], stage=j["stage"],
                         created_at=j["created_at"], updated_at=j["updated_at"], result=j["result"], error=j["error"])

    @app.get("/api/v1/files/{key:path}", tags=["files"], summary="Download an output file (local storage only)",
             responses={404: {"model": ErrorResponse}})
    def get_file(key: str):
        p = storage.local_path(key)
        if not p:
            raise ApiError("NOT_FOUND", "File not found.", 404)
        return FileResponse(p)

    def _health():
        return {"status": "ok", "version": s.app_version}

    def _ready():
        checks = {"database": False, "storage": False, "ffmpeg": shutil.which("ffmpeg") is not None}
        try:
            checks["database"] = store.ping()
        except Exception:
            pass
        try:
            checks["storage"] = storage.ready()
        except Exception:
            pass
        ok = all(checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)

    app.get("/health", tags=["ops"])(_health)
    app.get("/ready", tags=["ops"])(_ready)
    app.get("/api/v1/health", tags=["ops"], include_in_schema=False)(_health)
    app.get("/api/v1/ready", tags=["ops"], include_in_schema=False)(_ready)
    return app


app = create_app() if os.environ.get("BROLL_NO_AUTOSTART") != "1" else None
