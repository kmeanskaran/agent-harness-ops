"""Celery app. Redis is both broker and result backend."""

from __future__ import annotations

from celery import Celery

from app.config import get_settings
from app.logging_config import setup_logging

# Configure structured JSON logging when the worker process boots.
setup_logging("worker")

_settings = get_settings()

celery_app = Celery(
    "devvoice",
    broker=_settings.REDIS_URL,
    backend=_settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_max_tasks_per_child=50,
    result_expires=_settings.JOB_TTL_SECONDS,
    # Celery replaces the root logger's handlers by default, which would undo
    # our JSON formatter. Keep ours.
    worker_hijack_root_logger=False,
)
