"""The DeepAgents orchestrator — the heart of DevVoice.

Wires together the four concepts the tutorial teaches:

  * Backends           -> StateBackend gives each job an in-memory file
                          workspace that lives only for the duration of the run.
  * Context engineering -> a stable AGENTS.md loaded as `memory`, a per-job
                          brief.md seeded into the workspace, and
                          SummarizationMiddleware to keep the thread lean.
  * Skills             -> each subagent loads only its own SKILL.md via
                          progressive disclosure (skills= sources).
  * Subagents          -> extractor, three writers, and a reviewer, each with an
                          isolated context.
"""
from __future__ import annotations

import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from langfuse.decorators import observe, langfuse_context

from app.config import CONTEXT_DIR, SKILLS_DIR, get_settings
from app.agent.model import get_model
from app.agent.tools import fact_check

# Virtual paths inside the agent's in-state filesystem.
SKILLS_ROOT = "/skills"
CONTEXT_PATH = "/context/AGENTS.md"


def _workspace(job_id: str) -> str:
    return f"/workspace/{job_id}"


# --------------------------------------------------------------------------- #
# Seeding: copy skills + shared context from disk into the in-state filesystem
# --------------------------------------------------------------------------- #
def _seed_files(
    job_id: str,
    brief_md: str,
    revision_instruction: str | None = None,
    previous_result: dict | None = None,
) -> dict:
    """Build the initial `files` dict for an invoke.

    StateBackend keeps files in agent state, so anything the skills/memory
    middleware should see (SKILL.md files, AGENTS.md) has to be seeded here,
    alongside the per-job brief.
    """
    files: dict = {}

    # Skills: /skills/<name>/SKILL.md (+ any supporting files in the folder).
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        for f in sorted(skill_dir.glob("*")):
            if f.is_file():
                vpath = f"{SKILLS_ROOT}/{skill_dir.name}/{f.name}"
                files[vpath] = create_file_data(f.read_text(encoding="utf-8"))

    # Shared durable context (loaded as `memory`).
    agents_md = (CONTEXT_DIR / "AGENTS.md").read_text(encoding="utf-8")
    files[CONTEXT_PATH] = create_file_data(agents_md)

    # Per-job brief — the only task-specific input.
    ws = _workspace(job_id)
    files[f"{ws}/brief.md"] = create_file_data(brief_md)
    if revision_instruction:
        files[f"{ws}/revision_request.md"] = create_file_data(
            f"# Revision Request\n\n{revision_instruction}\n"
        )
    if previous_result:
        chunks: list[str] = ["# Previous Output"]
        if previous_result.get("x_thread"):
            chunks.append("## X Thread\n" + "\n".join(f"- {x}" for x in previous_result["x_thread"]))
        if previous_result.get("linkedin_post"):
            chunks.append("## LinkedIn Post\n" + previous_result["linkedin_post"])
        if previous_result.get("devto_article"):
            chunks.append("## dev.to Article\n" + previous_result["devto_article"])
        files[f"{ws}/previous_output.md"] = create_file_data("\n\n".join(chunks))
    return files


# --------------------------------------------------------------------------- #
# Subagents — each isolated, each loading only its own skill
# --------------------------------------------------------------------------- #
def _subagents() -> list[dict]:
    common = (
        "You are a DevVoice subagent. You operate on files in the job workspace "
        "at /workspace/{job_id} (the orchestrator gives you the job_id). Read "
        "the files you are told to read, including any revision files when "
        "present, follow your skill exactly, and save "
        "your output with write_file. Stay strictly grounded in "
        "extracted_insights.md — never invent facts."
    )

    return [
        {
            "name": "extractor",
            "description": (
                "FIRST step. Reads brief.md and produces the source-grounded "
                "extracted_insights.md. Does not write any platform content."
            ),
            "system_prompt": common
            + "\n\nFollow the `extractor` skill. Read /workspace/{job_id}/brief.md "
            "and write /workspace/{job_id}/extracted_insights.md.",
            "skills": [SKILLS_ROOT],
        },
        {
            "name": "x-writer",
            "description": (
                "Writes a 6-10 tweet X thread to x_draft.md from "
                "extracted_insights.md. Use only when 'x' is a requested platform."
            ),
            "system_prompt": common
            + "\n\nFollow the `x-writer` skill. Read extracted_insights.md and "
            "write /workspace/{job_id}/x_draft.md.",
            "skills": [SKILLS_ROOT],
        },
        {
            "name": "linkedin-writer",
            "description": (
                "Writes a 150-300 word LinkedIn post to linkedin_draft.md from "
                "extracted_insights.md. Use only when 'linkedin' is requested."
            ),
            "system_prompt": common
            + "\n\nFollow the `linkedin-writer` skill. Read extracted_insights.md "
            "and write /workspace/{job_id}/linkedin_draft.md.",
            "skills": [SKILLS_ROOT],
        },
        {
            "name": "devto-writer",
            "description": (
                "Writes a 1000-1500 word dev.to article to devto_draft.md from "
                "extracted_insights.md. Use only when 'devto' is requested."
            ),
            "system_prompt": common
            + "\n\nFollow the `devto-writer` skill. Read extracted_insights.md "
            "and write /workspace/{job_id}/devto_draft.md.",
            "skills": [SKILLS_ROOT],
        },
        {
            "name": "content-reviewer",
            "description": (
                "LAST step. Reviews every draft against extracted_insights.md, "
                "corrects each draft in place, and writes review_notes.md."
            ),
            "system_prompt": common
            + "\n\nFollow the `content-reviewer` skill. Check each draft against "
            "extracted_insights.md, rewrite drafts in place to fix issues, and "
            "write /workspace/{job_id}/review_notes.md. You may use fact_check "
            "to verify an external claim, but never add new claims.",
            "skills": [SKILLS_ROOT],
            "tools": [fact_check],
        },
    ]


# --------------------------------------------------------------------------- #
# Orchestrator construction (built once, reused across jobs)
# --------------------------------------------------------------------------- #
ORCHESTRATOR_PROMPT = """You are the DevVoice orchestrator.

You turn a developer's README + learnings into accurate, platform-native content
by delegating to subagents. Your job is coordination and verification, NOT
writing the content yourself.

Workflow for job {job_id}:
1. Read /workspace/{job_id}/brief.md to learn the requested `platforms`.
2. Delegate to the `extractor` subagent to produce extracted_insights.md.
3. For EACH requested platform, delegate to the matching writer subagent
   (x -> x-writer, linkedin -> linkedin-writer, devto -> devto-writer). Pass the
   job_id explicitly.
4. Delegate to the `content-reviewer` subagent to verify and correct all drafts.
5. Confirm the requested draft files exist, then reply with a one-line summary.

Rules:
- Always pass the job_id to subagents so they read/write the right workspace.
- Only generate the platforms listed in the brief.
- Never write or edit draft files yourself — re-delegate if a draft is wrong.
- Follow the durable guidance in your memory (AGENTS.md)."""


@lru_cache
def build_orchestrator():
    """Construct the compiled orchestrator graph once."""
    from langchain_core.globals import set_llm_cache

    from app.agent.cache import RedisLLMCache

    set_llm_cache(RedisLLMCache())

    model = get_model()
    backend = StateBackend()

    # NOTE on context engineering: create_deep_agent's base stack already
    # includes a SummarizationMiddleware that compacts the thread once it grows
    # large. We lean on that, plus three deliberate context moves of our own:
    #   * `memory=[AGENTS.md]`  -> stable durable project context, loaded once.
    #   * per-job brief.md      -> the only task-specific context in the thread.
    #   * subagents + skills    -> heavy work runs in isolated contexts so the
    #                              orchestrator thread stays lean.
    return create_deep_agent(
        model=model,
        system_prompt=ORCHESTRATOR_PROMPT,
        backend=backend,
        subagents=_subagents(),
        skills=[SKILLS_ROOT],
        memory=[CONTEXT_PATH],
        name="devvoice-orchestrator",
    )


# --------------------------------------------------------------------------- #
# Parsing the finished workspace back into the API result
# --------------------------------------------------------------------------- #
def _file_text(files: dict, vpath: str) -> str | None:
    data = files.get(vpath)
    if not data:
        return None
    return data["content"] if isinstance(data, dict) else str(data)


_TWEET_RE = re.compile(r"^\s*\d+\s*/\s*(.*)$")


def _parse_thread(md: str) -> list[str]:
    """Turn a numbered '1/ ...' thread into a list of tweet strings."""
    tweets: list[str] = []
    current: list[str] = []
    for line in md.splitlines():
        if line.startswith("#"):
            continue
        m = _TWEET_RE.match(line)
        if m:
            if current:
                tweets.append("\n".join(current).strip())
            current = [m.group(1)]
        elif current:
            current.append(line)
    if current:
        tweets.append("\n".join(current).strip())
    return [t for t in (t.strip() for t in tweets) if t]


def assemble_result(files: dict, job_id: str, platforms: Iterable[str]) -> dict:
    ws = _workspace(job_id)
    platforms = set(platforms)
    result: dict = {}

    if "x" in platforms:
        md = _file_text(files, f"{ws}/x_draft.md") or ""
        result["x_thread"] = _parse_thread(md)
    if "linkedin" in platforms:
        body = _file_text(files, f"{ws}/linkedin_draft.md") or ""
        # Drop a leading "# LinkedIn Post" heading if present.
        result["linkedin_post"] = re.sub(
            r"^#.*\n+", "", body, count=1
        ).strip()
    if "devto" in platforms:
        result["devto_article"] = (_file_text(files, f"{ws}/devto_draft.md") or "").strip()

    result["review_notes"] = _file_text(files, f"{ws}/review_notes.md")
    return result


# --------------------------------------------------------------------------- #
# Running a job
# --------------------------------------------------------------------------- #
@observe(name="devvoice_pipeline")
def run_job(
    job_id: str,
    brief_md: str,
    platforms: Iterable[str],
    revision_instruction: str | None = None,
    previous_result: dict | None = None,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict:
    """Run the full pipeline for one job and return the assembled result.

    `on_progress(status, current_step)` is called as the workspace fills, so the
    Celery task can stream coarse progress into Redis.

    LangFuse tracks:
    - job_id and platforms (input)
    - execution time
    - which subagents ran
    - final result
    """
    start_time = time.time()
    agent = build_orchestrator()
    files = _seed_files(job_id, brief_md, revision_instruction, previous_result)
    ws = _workspace(job_id)

    # Set LangFuse trace context
    langfuse_context.update_current_trace(**{
        "user_id": job_id,
        "session_id": job_id,
        "metadata": {
            "platforms": list(platforms),
            "has_revision": revision_instruction is not None,
            "has_previous_result": previous_result is not None,
            "brief_length": len(brief_md)
        }
    })

    def emit(status: str, step: str) -> None:
        if on_progress:
            on_progress(status, step)

    emit("running", "orchestrator")

    last_status = "running"
    final_files: dict = files
    user_msg = (
        f"Run the DevVoice pipeline for job_id={job_id}. The brief is at "
        f"{ws}/brief.md. If {ws}/revision_request.md or {ws}/previous_output.md exist, use them "
        f"to revise the content instead of starting blind. Generate exactly the "
        f"platforms it lists, then have the reviewer verify and correct every draft."
    )

    # Stream values so we can infer progress from which files now exist.
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": user_msg}], "files": files},
        config={"recursion_limit": 100},
        stream_mode="values",
    ):
        cur = chunk.get("files") or {}
        if cur:
            final_files = cur
        status = last_status
        if f"{ws}/review_notes.md" in cur:
            status = "reviewing"
        elif any(k.endswith("_draft.md") for k in cur):
            status = "writing"
        elif f"{ws}/extracted_insights.md" in cur:
            status = "extracting"
        if status != last_status:
            emit(status, status)
            last_status = status

    result = assemble_result(final_files, job_id, platforms)

    # Update LangFuse trace with completion info
    elapsed = time.time() - start_time
    langfuse_context.update_current_trace(**{
        "metadata": {
            "duration_seconds": elapsed,
            "success": True,
            "platforms_generated": list(platforms)
        }
    })

    return result


def generate_content(
    readme: str,
    learnings: list[str],
    hard_parts: list[str],
    tone: str,
    audience: str,
    platform: str,
) -> dict:
    """Run the DevVoice pipeline for a single platform synchronously.

    Takes raw input and returns the finished content for one platform.
    Used by the direct HTTP endpoints (/generate-x-post, etc).
    """
    import uuid

    job_id = uuid.uuid4().hex[:12]

    # Build brief from inputs
    learnings_text = (
        "\n".join(f"- {x}" for x in learnings) if learnings else "- (none provided)"
    )
    hard_parts_text = (
        "\n".join(f"- {x}" for x in hard_parts) if hard_parts else "- (none provided)"
    )
    brief_md = f"""# Job Brief

## Requested Platforms
{platform}

## Tone
{tone}

## Audience
{audience}

## Learnings
{learnings_text}

## Hard Parts
{hard_parts_text}

## README
{readme}
"""

    # Run the full pipeline (extract → write → review) for this one platform
    result = run_job(
        job_id=job_id,
        brief_md=brief_md,
        platforms=[platform],
        on_progress=None,
    )

    return result
