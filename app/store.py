"""SQLite job store with idempotency keys."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from .errors import ApiError


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY, idempotency_key TEXT, request_hash TEXT,
                  status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, stage TEXT,
                  request_json TEXT NOT NULL, input_path TEXT, correlation_id TEXT,
                  result_json TEXT, error_json TEXT, created_at TEXT, updated_at TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idem ON jobs(idempotency_key)
                  WHERE idempotency_key IS NOT NULL;
                """
            )
            self.conn.commit()

    @staticmethod
    def _row(r: sqlite3.Row | None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        d["request"] = json.loads(d.pop("request_json"))
        result_json, error_json = d.pop("result_json"), d.pop("error_json")
        d["result"] = json.loads(result_json) if result_json else None
        d["error"] = json.loads(error_json) if error_json else None
        return d

    def create(self, request: dict, idem_key: str | None, request_hash: str, correlation_id: str | None,
               input_path: str | None = None) -> tuple[dict, bool]:
        """Returns (job, created). Same key + same request returns the existing job."""
        with self.lock:
            if idem_key:
                r = self.conn.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idem_key,)).fetchone()
                if r is not None:
                    if r["request_hash"] != request_hash:
                        raise ApiError("IDEMPOTENCY_KEY_REUSED",
                                       "This Idempotency-Key was already used with a different request.", 409)
                    return self._row(r), False
            job_id = "job_" + uuid.uuid4().hex[:16]
            ts = now()
            self.conn.execute(
                "INSERT INTO jobs (job_id, idempotency_key, request_hash, status, progress, stage, request_json,"
                " input_path, correlation_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, idem_key, request_hash, "queued", 0, "queued", json.dumps(request), input_path,
                 correlation_id, ts, ts))
            self.conn.commit()
            return self.get(job_id), True

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return self._row(self.conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def update(self, job_id: str, **fields) -> None:
        cols = []
        vals = []
        for k, v in fields.items():
            if k in ("result", "error"):
                cols.append(f"{k}_json=?")
                vals.append(json.dumps(v) if v is not None else None)
            else:
                cols.append(f"{k}=?")
                vals.append(v)
        cols.append("updated_at=?")
        vals.append(now())
        vals.append(job_id)
        with self.lock:
            self.conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE job_id=?", vals)
            self.conn.commit()

    def incomplete(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM jobs WHERE status IN ('queued','running')").fetchall()
        return [self._row(r) for r in rows]

    def ping(self) -> bool:
        with self.lock:
            self.conn.execute("SELECT 1").fetchone()
        return True
