"""Celery app. Redis is both broker and result backend."""
from __future__ import annotations

from celery import Celery

from app.config import get_settings

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
)
