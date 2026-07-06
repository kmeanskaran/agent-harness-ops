"""Pydantic request/response models for the HTTP layer."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ContentRequest(BaseModel):
    """Input for content generation endpoints."""
    email: str = Field(..., min_length=3, description="Unique user email.")
    readme: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="Raw README markdown (max 100KB). Large READMEs will be automatically truncated.",
    )
    learnings: list[str] = Field(default_factory=list, description="Key technical insights.")
    hard_parts: list[str] = Field(default_factory=list, description="Challenging aspects.")
    tone: str = Field(default="honest and practical", description="Voice/style.")
    audience: str = Field(default="intermediate developers", description="Target audience.")
    platforms: list[str] = Field(
        default_factory=list,
        description="Platforms to generate: x, linkedin, devto. Overrides single-platform endpoints.",
    )


class JobResponse(BaseModel):
    """Immediate response when job is enqueued."""
    job_id: str
    status: str
    thread_id: str | None = None
    parent_job_id: str | None = None


class ResultResponse(BaseModel):
    """Result when checking job status."""
    job_id: str
    status: str  # queued, running, extracting, writing, reviewing, awaiting_approval, completed, failed
    current_step: str | None = None
    thread_id: str | None = None
    parent_job_id: str | None = None
    x_thread: list[str] | None = None
    linkedin_post: str | None = None
    devto_article: str | None = None
    review_notes: str | None = None
    error: str | None = None


class RevisionRequest(BaseModel):
    """Minimal revision input for a previous job."""
    email: str = Field(..., min_length=3, description="Unique user email.")
    instruction: str = Field(..., min_length=1, description="What should change in the revision.")
    tone: str | None = Field(default=None, description="Optional new tone/style for this revision.")
    platforms: list[str] = Field(
        default_factory=list,
        description="Optional subset of platforms to revise; defaults to parent's platforms.",
    )


class ApprovalRequest(BaseModel):
    email: str = Field(..., min_length=3, description="Unique user email.")


class UserProfileResponse(BaseModel):
    email: str


class HistoryItem(BaseModel):
    job_id: str
    project_id: str
    thread_id: str
    parent_job_id: str | None = None
    status: str
    current_step: str | None = None
    tone: str | None = None
    audience: str | None = None
    platforms: list[str] = Field(default_factory=list)
    readme: str = ""
    learnings: list[str] = Field(default_factory=list)
    hard_parts: list[str] = Field(default_factory=list)
    x_thread: list[str] | None = None
    linkedin_post: str | None = None
    devto_article: str | None = None
    created_at: str
    updated_at: str
    error: str | None = None


class HistoryResponse(BaseModel):
    email: str
    items: list[HistoryItem]
