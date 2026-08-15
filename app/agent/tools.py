"""Tools available to the agent. Kept small and source-grounded.

`fact_check` lets the reviewer optionally verify an external claim with Tavily.
It is intentionally the only outward tool — drafts must come from the source,
not the web.
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger("devvoice.agent")


def fact_check(query: str, max_results: int = 3) -> dict:
    """Look up a factual claim on the web to confirm it is not wrong.

    Use ONLY to verify an external technical fact a draft asserts (e.g. "Redis
    is single-threaded"). Do NOT use it to add new claims — drafts must stay
    grounded in extracted_insights.md.
    """
    s = get_settings()
    # Placeholder values like REPLACE_ME are normalised to "" in app.config, so
    # this guard fires for "unset" and "not yet configured" alike.
    if not s.TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY not set; skip web verification."}
    from tavily import TavilyClient

    # fact_check is optional enrichment — a bad key or a network blip must not
    # take down the whole run. Return the error as a tool result so the model
    # can note it and move on.
    try:
        client = TavilyClient(api_key=s.TAVILY_API_KEY)
        return client.search(query, max_results=max_results, topic="general")
    except Exception as exc:  # noqa: BLE001 — any failure here is non-fatal
        logger.warning("fact_check failed: %s: %s", type(exc).__name__, exc)
        return {"error": f"web verification unavailable ({type(exc).__name__}); skip it."}
