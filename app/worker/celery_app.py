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
    # An agent loop has no natural end: LangGraph's recursion_limit counts
    # turns, not seconds, so a job that stalls between turns runs forever and
    # holds its concurrency slot. These are the wall-clock backstop.
    #
    # Soft raises SoftTimeLimitExceeded *inside* the task, so the handler in
    # tasks.py can mark the job failed in Redis/Postgres. Hard kills the child
    # process if the soft limit is swallowed somewhere in the graph.
    task_soft_time_limit=_settings.JOB_SOFT_TIME_LIMIT,
    task_time_limit=_settings.JOB_HARD_TIME_LIMIT,
    # With task_acks_late=True, a task killed by the hard limit counts as
    # "worker lost" and would be redelivered by default — a hung job would hang
    # again on the next worker, forever. Fail it once instead.
    task_reject_on_worker_lost=False,
)
