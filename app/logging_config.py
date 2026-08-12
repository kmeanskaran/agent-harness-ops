"""One-line structured logging setup, called once per process.

Why JSON: on Fargate the awslogs driver ships stdout straight to CloudWatch.
Plain text is only greppable; JSON is *queryable* — CloudWatch Logs Insights can
filter and aggregate on fields like job_id, stage, and elapsed_s.

Usage:
    from app.logging_config import setup_logging
    setup_logging("api")        # or "worker", at process start

    logger.info("job start", extra={"job_id": job_id, "platform": platform})
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

# Attributes the stdlib puts on every LogRecord — anything else the caller
# passed via extra={...} is a custom field we want in the JSON output.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}

# Libraries that log a lot and tell us nothing about our own app.
_NOISY = ("botocore", "boto3", "urllib3", "httpx", "httpcore", "s3transfer", "openai")


class JsonFormatter(logging.Formatter):
    """Render each record as a single-line JSON object."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Promote anything passed as extra={...} to a top-level field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(service: str, level: str | None = None) -> None:
    """Configure the root logger. Idempotent — safe to call more than once."""
    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers = [handler]  # replace, so repeated calls don't duplicate output
    root.setLevel(resolved)

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)

    root.info("logging configured", extra={"log_level": resolved})
