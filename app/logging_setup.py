"""Structured JSON logs: timestamp, level, job_id, correlation_id."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

correlation_id_var: contextvars.ContextVar = contextvars.ContextVar("correlation_id", default=None)
job_id_var: contextvars.ContextVar = contextvars.ContextVar("job_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "job_id": job_id_var.get(),
            "correlation_id": correlation_id_var.get(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            d.update(extra)
        if record.exc_info:
            d["exception"] = self.formatException(record.exc_info)
        return json.dumps(d, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.__stdout__)  # stays open even if a test runner swaps sys.stdout
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


def log(logger: logging.Logger, level: int, message: str, **fields) -> None:
    logger.log(level, message, extra={"fields": fields})
