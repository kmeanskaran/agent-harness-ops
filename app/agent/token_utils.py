"""Token counting and context budget utilities.

Helps estimate token usage and enforce context limits to prevent silent failures
and runaway costs.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough estimate of token count (1 token ≈ 4 characters for English).

    For precise counting with a real model, use `count_tokens_claude()`.
    This is fast and good enough for validation.
    """
    return len(text) // 4


def validate_readme_size(readme: str, max_chars: int = 50000, max_tokens: int = 12000) -> tuple[bool, str]:
    """Validate README doesn't exceed size limits.

    Args:
        readme: Raw README markdown
        max_chars: Maximum characters allowed (50KB default)
        max_tokens: Maximum estimated tokens (12K default)

    Returns:
        (is_valid, message)
    """
    char_count = len(readme)
    token_count = estimate_tokens(readme)

    if char_count > max_chars:
        return False, f"README too large: {char_count} chars (max {max_chars})"

    if token_count > max_tokens:
        return False, f"README too large: ~{token_count} tokens (max {max_tokens})"

    return True, ""


def truncate_readme(readme: str, max_tokens: int = 10000) -> str:
    """Truncate README to fit token budget while preserving structure.

    Keeps:
    1. First 50% of content (usually intro/overview)
    2. All heading structure (helps with understanding)
    3. A truncation marker
    """
    estimated_tokens = estimate_tokens(readme)

    if estimated_tokens <= max_tokens:
        return readme

    logger.warning(f"Truncating README: {estimated_tokens} → {max_tokens} tokens")

    # Keep first ~60% by character count (accounts for compression from removing details)
    truncate_at = int(len(readme) * 0.6)

    # Try to truncate at a paragraph boundary
    paragraph_break = readme.rfind("\n\n", 0, truncate_at)
    if paragraph_break > len(readme) * 0.5:  # Found break in reasonable range
        truncate_at = paragraph_break

    truncated = readme[:truncate_at].rstrip()
    marker = (
        "\n\n---\n\n"
        "**[DevVoice: README truncated to manage context size. "
        f"Original: ~{estimated_tokens} tokens, Kept: ~{estimate_tokens(truncated)} tokens]**"
    )

    return truncated + marker


def estimate_job_tokens(
    readme: str,
    learnings: list[str],
    hard_parts: list[str],
    tone: str,
    audience: str,
) -> dict:
    """Estimate total tokens for a job before running it.

    Returns breakdown of token usage per component.
    """
    readme_tokens = estimate_tokens(readme)
    learnings_tokens = sum(estimate_tokens(l) for l in (learnings or []))
    hard_parts_tokens = sum(estimate_tokens(h) for h in (hard_parts or []))
    metadata_tokens = estimate_tokens(tone) + estimate_tokens(audience) + 100  # Buffer

    # Rough estimate of overhead
    # - Skills: ~2K tokens
    # - AGENTS.md: ~500 tokens
    # - Instructions: ~300 tokens
    # - Formatting: ~200 tokens
    overhead_tokens = 3000

    total = readme_tokens + learnings_tokens + hard_parts_tokens + metadata_tokens + overhead_tokens

    return {
        "readme": readme_tokens,
        "learnings": learnings_tokens,
        "hard_parts": hard_parts_tokens,
        "metadata": metadata_tokens,
        "overhead": overhead_tokens,
        "total": total,
        "warning": "high_context" if total > 20000 else None,
    }


def log_token_estimate(job_id: str, estimate: dict) -> None:
    """Log token estimate for monitoring."""
    logger.info(
        f"JOB TOKEN ESTIMATE | job_id={job_id} | "
        f"readme={estimate['readme']}K | "
        f"total={estimate['total']}K | "
        f"warning={estimate.get('warning')}"
    )
