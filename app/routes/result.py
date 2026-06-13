"""Result endpoint — check job status and retrieve finished content."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app import db, redis_store
from app.models import ResultResponse

router = APIRouter()


@router.get("/result/{job_id}", response_model=ResultResponse)
def get_result(job_id: str) -> ResultResponse:
    """Check job status. Returns status while running, content when completed."""
    job = redis_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found or expired")

    status = job.get("status", "unknown")
    resp = ResultResponse(
        job_id=job_id,
        status=status,
        current_step=job.get("current_step"),
        error=job.get("error"),
    )
    record = db.get_job_record(job_id)
    if record:
        resp.thread_id = record["thread_id"]
        resp.parent_job_id = record["parent_job_id"]

    # If finalized or awaiting approval, return the platform-specific content
    if status in {"completed", "awaiting_approval"} and job.get("result"):
        result = json.loads(job["result"])
        resp.x_thread = result.get("x_thread")
        resp.linkedin_post = result.get("linkedin_post")
        resp.devto_article = result.get("devto_article")
        resp.review_notes = result.get("review_notes")

    return resp
