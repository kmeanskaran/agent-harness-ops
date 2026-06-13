"""Redis-backed job store. One Redis instance serves three roles:
Celery broker, Celery result backend, and this job/result store.

A job is a Redis hash at `jobs:{job_id}` with a 2h TTL — no database, no
cleanup. Fields match the data model in idea.md.
"""
from __future__ import annotations

import json
import time
from typing import Any

import redis

from app.config import get_settings

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().REDIS_URL, decode_responses=True
        )
    return _client


def _key(job_id: str) -> str:
    return f"jobs:{job_id}"


def _user_active_key(email: str) -> str:
    return f"user:{email}:active_jobs"


def _project_jobs_key(project_id: str) -> str:
    return f"project:{project_id}:jobs"


def _thread_jobs_key(thread_id: str) -> str:
    return f"thread:{thread_id}:jobs"


def _project_latest_key(project_id: str) -> str:
    return f"project:{project_id}:latest_job"


def _thread_latest_key(thread_id: str) -> str:
    return f"thread:{thread_id}:latest_job"


def _touch_ttl(job_id: str) -> None:
    get_client().expire(_key(job_id), get_settings().JOB_TTL_SECONDS)


def _touch_related(*keys: str) -> None:
    ttl = get_settings().JOB_TTL_SECONDS
    client = get_client()
    for key in keys:
        if key:
            client.expire(key, ttl)


def create_job(job_id: str, payload: dict[str, Any]) -> None:
    """Persist a brand-new job in the `queued` state."""
    client = get_client()
    email = str(payload.get("email") or "")
    project_id = str(payload.get("project_id") or "")
    thread_id = str(payload.get("thread_id") or "")
    client.hset(
        _key(job_id),
        mapping={
            "status": "queued",
            "current_step": "queued",
            "input": json.dumps(payload),
            "email": email,
            "project_id": project_id,
            "thread_id": thread_id,
        },
    )
    _touch_ttl(job_id)
    if email:
        client.sadd(_user_active_key(email), job_id)
    if project_id:
        client.zadd(_project_jobs_key(project_id), {job_id: time.time()})
        client.set(_project_latest_key(project_id), job_id)
    if thread_id:
        client.zadd(_thread_jobs_key(thread_id), {job_id: time.time()})
        client.set(_thread_latest_key(thread_id), job_id)
    _touch_related(
        _user_active_key(email) if email else "",
        _project_jobs_key(project_id) if project_id else "",
        _thread_jobs_key(thread_id) if thread_id else "",
        _project_latest_key(project_id) if project_id else "",
        _thread_latest_key(thread_id) if thread_id else "",
    )


def set_status(job_id: str, status: str, current_step: str | None = None) -> None:
    mapping: dict[str, str] = {"status": status}
    if current_step is not None:
        mapping["current_step"] = current_step
    get_client().hset(_key(job_id), mapping=mapping)
    _touch_ttl(job_id)


def set_result(job_id: str, result: dict[str, Any]) -> None:
    client = get_client()
    client.hset(
        _key(job_id),
        mapping={
            "status": "completed",
            "current_step": "completed",
            "result": json.dumps(result),
        },
    )
    email = client.hget(_key(job_id), "email")
    if email:
        client.srem(_user_active_key(email), job_id)
    _touch_ttl(job_id)


def set_awaiting_approval(job_id: str, result: dict[str, Any]) -> None:
    client = get_client()
    client.hset(
        _key(job_id),
        mapping={
            "status": "awaiting_approval",
            "current_step": "awaiting_approval",
            "result": json.dumps(result),
        },
    )
    email = client.hget(_key(job_id), "email")
    if email:
        client.srem(_user_active_key(email), job_id)
    _touch_ttl(job_id)


def set_error(job_id: str, message: str) -> None:
    client = get_client()
    client.hset(
        _key(job_id),
        mapping={"status": "failed", "current_step": "failed", "error": message},
    )
    email = client.hget(_key(job_id), "email")
    if email:
        client.srem(_user_active_key(email), job_id)
    _touch_ttl(job_id)


def get_job(job_id: str) -> dict[str, Any] | None:
    data = get_client().hgetall(_key(job_id))
    return data or None


def delete_job(job_id: str, email: str | None = None, project_id: str | None = None, thread_id: str | None = None) -> None:
    client = get_client()
    email = email or client.hget(_key(job_id), "email")
    project_id = project_id or client.hget(_key(job_id), "project_id")
    thread_id = thread_id or client.hget(_key(job_id), "thread_id")
    client.delete(_key(job_id))
    if email:
        client.srem(_user_active_key(email), job_id)
    if project_id:
        client.zrem(_project_jobs_key(project_id), job_id)
        latest = client.get(_project_latest_key(project_id))
        if latest == job_id:
            client.delete(_project_latest_key(project_id))
    if thread_id:
        client.zrem(_thread_jobs_key(thread_id), job_id)
        latest = client.get(_thread_latest_key(thread_id))
        if latest == job_id:
            client.delete(_thread_latest_key(thread_id))


def delete_project(project_id: str) -> None:
    client = get_client()
    job_ids = client.zrange(_project_jobs_key(project_id), 0, -1)
    for job_id in job_ids:
        delete_job(job_id, project_id=project_id)
    client.delete(_project_jobs_key(project_id))
    client.delete(_project_latest_key(project_id))


def approve_job(job_id: str) -> None:
    client = get_client()
    client.hset(
        _key(job_id),
        mapping={"status": "completed", "current_step": "completed"},
    )
    _touch_ttl(job_id)
