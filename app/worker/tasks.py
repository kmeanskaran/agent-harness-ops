"""Background task: run the DeepAgents pipeline for one job.

Jobs are enqueued by the HTTP endpoints and processed by Celery workers.
Progress is tracked in Redis so the client can poll for results.
LangFuse tracks job execution, timing, and results.

Token optimization:
- Validates README size before processing
- Truncates large READMEs to fit context windows
- Caches extractions to avoid reprocessing
"""
from __future__ import annotations

import logging
import os
import time

from langfuse.decorators import observe, langfuse_context
from langfuse import Langfuse

from app import db
from app import redis_store
from app.agent.orchestrator import run_job
from app.agent.token_utils import validate_readme_size, truncate_readme, estimate_job_tokens, log_token_estimate  # noqa: F401
from app.agent.readme_cache import get_cached_extraction, cache_extraction  # noqa: F401
from app.worker.celery_app import celery_app

# Initialize LangFuse in worker
langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_BASE_URL")
)

logger = logging.getLogger("devvoice.worker")


def build_brief(payload: dict) -> str:
    """Render the request into the brief.md the orchestrator reads."""
    learnings = "\n".join(f"- {x}" for x in payload.get("learnings", [])) or "- (none provided)"
    hard_parts = "\n".join(f"- {x}" for x in payload.get("hard_parts", [])) or "- (none provided)"
    # Support both legacy `platform` (str) and new `platforms` (list)
    raw = payload.get("platforms") or [payload.get("platform", "x")]
    platforms_line = ", ".join(raw)
    previous_result = payload.get("previous_result") or {}
    previous_sections: list[str] = []
    if previous_result.get("x_thread"):
        previous_sections.append("### Previous X Thread\n" + "\n".join(f"- {x}" for x in previous_result["x_thread"]))
    if previous_result.get("linkedin_post"):
        previous_sections.append("### Previous LinkedIn Post\n" + previous_result["linkedin_post"])
    if previous_result.get("devto_article"):
        previous_sections.append("### Previous dev.to Article\n" + previous_result["devto_article"])
    previous_output_md = "\n\n".join(previous_sections) or "(no previous output)"
    revision_instruction = payload.get("revision_instruction") or "(none)"
    return f"""# Job Brief

## Requested Platforms
{platforms_line}

## Tone
{payload.get("tone", "honest and practical")}

## Audience
{payload.get("audience", "intermediate developers")}

## User Email
{payload.get("email", "")}

## Learnings
{learnings}

## Hard Parts
{hard_parts}

## Revision Instruction
{revision_instruction}

## Previous Output
{previous_output_md}

## README
{payload.get("readme", "")}
"""


@celery_app.task(name="devvoice.generate_content")
@observe(name="generate_content_task")
def generate_content_task(job_id: str, payload: dict) -> dict:
    """Celery worker task — runs the orchestrator and stores the result in Redis.

    Token optimization:
    - Validates README doesn't exceed limits (100KB, 12K tokens)
    - Truncates large READMEs to fit token budget (10K tokens)
    - Estimates total job tokens before processing
    - Logs token usage for monitoring

    LangFuse tracks:
    - job_id, email, platforms, token estimates
    - job start/completion timing
    - success/failure status
    """
    # Support both legacy `platform` (str) and new `platforms` (list)
    platforms = payload.get("platforms") or [payload.get("platform", "x")]
    platform = ", ".join(platforms)
    started_at = time.time()
    readme = payload.get("readme", "")

    # ========== TOKEN OPTIMIZATION: VALIDATE & TRUNCATE ==========
    is_valid, error_msg = validate_readme_size(readme, max_chars=100000, max_tokens=12000)
    if not is_valid:
        logger.warning(f"README size check: {error_msg} (will truncate)")
        readme = truncate_readme(readme, max_tokens=10000)
        payload["readme"] = readme
        payload["readme_truncated"] = True

    # Estimate tokens before processing
    token_estimate = estimate_job_tokens(
        readme=readme,
        learnings=payload.get("learnings", []),
        hard_parts=payload.get("hard_parts", []),
        tone=payload.get("tone", ""),
        audience=payload.get("audience", ""),
    )
    log_token_estimate(job_id, token_estimate)

    # Set LangFuse context with token information
    langfuse_context.update_current_trace(**{
        "user_id": payload.get("email", "unknown"),
        "session_id": job_id,
        "metadata": {
            "job_id": job_id,
            "platforms": platforms,
            "tone": payload.get("tone"),
            "audience": payload.get("audience"),
            "readme_length": len(readme),
            "readme_truncated": payload.get("readme_truncated", False),
            "estimated_tokens": token_estimate["total"],
            "token_breakdown": {
                "readme": token_estimate["readme"],
                "learnings": token_estimate["learnings"],
                "hard_parts": token_estimate["hard_parts"],
                "overhead": token_estimate["overhead"],
            },
            "email": payload.get("email")
        }
    })

    logger.info("=" * 70)
    logger.info(f"JOB START  | job_id={job_id} | platform={platform}")
    logger.info(f"           | tone={payload.get('tone')} | audience={payload.get('audience')}")
    logger.info(f"           | readme_len={len(readme)} chars | est_tokens={token_estimate['total']}K")
    if payload.get("readme_truncated"):
        logger.warning(f"           | README WAS TRUNCATED to fit context")
    logger.info("=" * 70)

    redis_store.set_status(job_id, "running", "orchestrator")
    db.update_job_progress(job_id, "running", "orchestrator")

    try:
        brief = build_brief(payload)

        def on_progress(status: str, step: str) -> None:
            elapsed = time.time() - started_at
            logger.info(f"PROGRESS   | job_id={job_id} | status={status} | step={step} | elapsed={elapsed:.1f}s")
            redis_store.set_status(job_id, status, step)
            db.update_job_progress(job_id, status, step)

        result = run_job(
            job_id=job_id,
            brief_md=brief,
            platforms=platforms,
            revision_instruction=payload.get("revision_instruction"),
            previous_result=payload.get("previous_result"),
            on_progress=on_progress,
        )

        elapsed = time.time() - started_at
        logger.info(f"JOB DONE   | job_id={job_id} | platform={platform} | elapsed={elapsed:.1f}s")
        logger.info("=" * 70)

        # Update LangFuse with success
        langfuse_context.update_current_trace(**{
            "metadata": {
                "status": "completed",
                "duration_seconds": elapsed,
                "platforms_generated": list(result.keys()),
                "estimated_tokens_used": token_estimate["total"],
            }
        })

        redis_store.set_awaiting_approval(job_id, result)
        db.mark_job_awaiting_approval(job_id, result)
        return {"job_id": job_id, "status": "awaiting_approval"}

    except Exception as exc:
        elapsed = time.time() - started_at
        logger.error(f"JOB FAILED | job_id={job_id} | elapsed={elapsed:.1f}s | error={type(exc).__name__}: {exc}")
        logger.info("=" * 70)

        # Update LangFuse with failure
        langfuse_context.update_current_trace(**{
            "metadata": {
                "status": "failed",
                "duration_seconds": elapsed,
                "error": f"{type(exc).__name__}: {exc}",
                "estimated_tokens_used": token_estimate["total"],
            }
        })

        redis_store.set_error(job_id, f"{type(exc).__name__}: {exc}")
        db.fail_job(job_id, f"{type(exc).__name__}: {exc}")
        raise
