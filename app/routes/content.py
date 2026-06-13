"""Content generation endpoints — single-platform shortcuts + multi-platform /generate."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import db
from app import redis_store
from app.models import ApprovalRequest, ContentRequest, HistoryItem, HistoryResponse, JobResponse, RevisionRequest, UserProfileResponse
from app.worker.tasks import generate_content_task

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _write_key(request: Request) -> str:
    return request.headers.get("x-user-email") or get_remote_address(request)


write_limiter = Limiter(key_func=_write_key)


def _enqueue(req: ContentRequest, platforms: list[str]) -> JobResponse:
    job_id = uuid.uuid4().hex[:12]
    db.upsert_user(req.email)
    thread_id = uuid.uuid4().hex
    project_id = db.project_id_for_readme(req.readme)
    db.upsert_project(project_id, req.email, req.readme)
    payload = {
        "email": req.email,
        "readme": req.readme,
        "learnings": req.learnings,
        "hard_parts": req.hard_parts,
        "tone": req.tone,
        "audience": req.audience,
        "platforms": platforms,
        "thread_id": thread_id,
        "project_id": project_id,
        "parent_job_id": None,
        "revision_instruction": None,
        "previous_result": None,
    }
    db.create_job_record(
        job_id=job_id,
        email=req.email,
        thread_id=thread_id,
        parent_job_id=None,
        project_id=project_id,
        payload=payload,
    )
    redis_store.create_job(job_id, payload)
    generate_content_task.delay(job_id, payload)
    return JobResponse(job_id=job_id, status="queued", thread_id=thread_id, parent_job_id=None)


@router.post("/generate", response_model=JobResponse)
@write_limiter.limit("10/minute")
def generate_multi(req: ContentRequest, request: Request) -> JobResponse:
    """Enqueue generation for one or more platforms in a single job. Rate: 10/min per IP."""
    platforms = req.platforms or ["x"]
    return _enqueue(req, platforms)


@router.post("/generate-x-post", response_model=JobResponse)
@write_limiter.limit("10/minute")
def generate_x_post(req: ContentRequest, request: Request) -> JobResponse:
    """Enqueue an X (Twitter) thread generation job. Rate: 10/min per IP."""
    return _enqueue(req, ["x"])


@router.post("/generate-linkedin-post", response_model=JobResponse)
@write_limiter.limit("10/minute")
def generate_linkedin_post(req: ContentRequest, request: Request) -> JobResponse:
    """Enqueue a LinkedIn post generation job. Rate: 10/min per IP."""
    return _enqueue(req, ["linkedin"])


@router.post("/generate-article", response_model=JobResponse)
@write_limiter.limit("10/minute")
def generate_article(req: ContentRequest, request: Request) -> JobResponse:
    """Enqueue a dev.to article generation job. Rate: 10/min per IP."""
    return _enqueue(req, ["devto"])


@router.post("/revise/{job_id}", response_model=JobResponse)
@write_limiter.limit("10/minute")
def revise_job(job_id: str, req: RevisionRequest, request: Request) -> JobResponse:
    parent = db.get_job_record(job_id)
    if not parent:
        raise HTTPException(status_code=404, detail="parent job not found")
    if parent["user_email"] != req.email:
        raise HTTPException(status_code=403, detail="email does not match parent job")

    original = parent["request_json"] or {}
    if not isinstance(original, dict):
        raise HTTPException(status_code=500, detail="parent job request is invalid")

    platforms = req.platforms or list(original.get("platforms") or ["x"])
    tone = req.tone or original.get("tone") or "honest and practical"
    db.upsert_user(req.email)

    new_job_id = uuid.uuid4().hex[:12]
    payload = {
        "email": req.email,
        "readme": original.get("readme", ""),
        "learnings": list(original.get("learnings") or []),
        "hard_parts": list(original.get("hard_parts") or []),
        "tone": tone,
        "audience": original.get("audience", "intermediate developers"),
        "platforms": platforms,
        "thread_id": parent["thread_id"],
        "project_id": parent["project_id"],
        "parent_job_id": job_id,
        "revision_instruction": req.instruction,
        "previous_result": parent.get("result_json"),
    }
    db.create_job_record(
        job_id=new_job_id,
        email=req.email,
        thread_id=parent["thread_id"],
        parent_job_id=job_id,
        project_id=parent["project_id"],
        payload=payload,
        revision_instruction=req.instruction,
    )
    redis_store.create_job(new_job_id, payload)
    generate_content_task.delay(new_job_id, payload)
    return JobResponse(
        job_id=new_job_id,
        status="queued",
        thread_id=parent["thread_id"],
        parent_job_id=job_id,
    )


@router.post("/approve/{job_id}")
@write_limiter.limit("20/minute")
def approve_job(job_id: str, req: ApprovalRequest, request: Request) -> dict:
    row = db.get_job_record(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row["user_email"] != req.email:
        raise HTTPException(status_code=403, detail="email does not match job")
    if not db.approve_job(req.email, job_id):
        raise HTTPException(status_code=400, detail="job is not awaiting approval")
    redis_store.approve_job(job_id)
    return {"ok": True, "job_id": job_id}


@router.get("/users/{email}", response_model=UserProfileResponse)
def get_user(email: str) -> UserProfileResponse:
    user = db.get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return UserProfileResponse(email=user["email"])


@router.get("/history/{email}", response_model=HistoryResponse)
def get_history(email: str) -> HistoryResponse:
    user = db.get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    items: list[HistoryItem] = []
    for row in db.get_user_history(email):
        request_json = row.get("request_json") or {}
        items.append(
            HistoryItem(
                job_id=row["job_id"],
                project_id=request_json.get("project_id", ""),
                thread_id=row["thread_id"],
                parent_job_id=row["parent_job_id"],
                status=row["status"],
                current_step=row["current_step"],
                tone=request_json.get("tone"),
                audience=request_json.get("audience"),
                platforms=list(request_json.get("platforms") or []),
                readme=request_json.get("readme", ""),
                learnings=list(request_json.get("learnings") or []),
                hard_parts=list(request_json.get("hard_parts") or []),
                x_thread=(row.get("result_json") or {}).get("x_thread"),
                linkedin_post=(row.get("result_json") or {}).get("linkedin_post"),
                devto_article=(row.get("result_json") or {}).get("devto_article"),
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
                error=row["error"],
            )
        )
    return HistoryResponse(email=email, items=items)


@router.delete("/history/{email}/{job_id}")
@write_limiter.limit("20/minute")
def delete_history_item(email: str, job_id: str, request: Request) -> dict:
    row = db.delete_job(email, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="history item not found")
    redis_store.delete_job(
        job_id,
        email=email,
        project_id=row.get("project_id"),
        thread_id=row.get("thread_id"),
    )
    return {"ok": True, "job_id": job_id}


@router.delete("/projects/{email}/{project_id}")
@write_limiter.limit("10/minute")
def delete_project(email: str, project_id: str, request: Request) -> dict:
    deleted = db.delete_project(email, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="project not found")
    redis_store.delete_project(project_id)
    return {"ok": True, "project_id": project_id}
