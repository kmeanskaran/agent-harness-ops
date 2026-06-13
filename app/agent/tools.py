"""Tools available to the agent. Kept small and source-grounded.

`fact_check` lets the reviewer optionally verify an external claim with Tavily.
It is intentionally the only outward tool — drafts must come from the source,
not the web.
"""
from __future__ import annotations

from typing import Literal

from app.config import get_settings


def fact_check(query: str, max_results: int = 3) -> dict:
    """Look up a factual claim on the web to confirm it is not wrong.

    Use ONLY to verify an external technical fact a draft asserts (e.g. "Redis
    is single-threaded"). Do NOT use it to add new claims — drafts must stay
    grounded in extracted_insights.md.
    """
    s = get_settings()
    if not s.TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY not set; skip web verification."}
    from tavily import TavilyClient

    client = TavilyClient(api_key=s.TAVILY_API_KEY)
    return client.search(query, max_results=max_results, topic="general")
