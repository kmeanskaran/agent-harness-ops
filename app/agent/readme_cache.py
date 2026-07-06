"""Cache README extractions to avoid reprocessing identical content."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from app import redis_store

logger = logging.getLogger(__name__)


def readme_hash(readme: str) -> str:
    """Generate hash of README content for caching."""
    return hashlib.sha256(readme.encode()).hexdigest()


def get_cached_extraction(readme: str) -> Optional[dict]:
    """Retrieve cached extraction if available.

    Returns extracted_insights dict if found, None otherwise.
    """
    hash_val = readme_hash(readme)
    cache_key = f"extraction:{hash_val}"

    try:
        client = redis_store.get_client()
        cached = client.get(cache_key)
        if cached:
            logger.info(f"README extraction cache HIT | hash={hash_val[:8]}")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")

    return None


def cache_extraction(readme: str, extraction: dict, ttl_seconds: int = 86400) -> None:
    """Cache an extraction result.

    Args:
        readme: Original README
        extraction: Extracted facts dict
        ttl_seconds: Time to live in cache (default 24 hours)
    """
    hash_val = readme_hash(readme)
    cache_key = f"extraction:{hash_val}"

    try:
        client = redis_store.get_client()
        client.setex(
            cache_key,
            ttl_seconds,
            json.dumps(extraction),
        )
        logger.info(f"README extraction cached | hash={hash_val[:8]} | ttl={ttl_seconds}s")
    except Exception as e:
        logger.warning(f"Cache write failed: {e}")


def extraction_cache_stats() -> dict:
    """Get cache statistics for monitoring."""
    try:
        client = redis_store.get_client()
        # Count extraction caches (pattern: extraction:*)
        pattern = "extraction:*"
        keys = client.keys(pattern)
        return {
            "cached_extractions": len(keys),
            "memory_usage_estimate": len(keys) * 5000,  # Rough estimate: 5KB per extraction
        }
    except Exception as e:
        logger.warning(f"Cache stats failed: {e}")
        return {"cached_extractions": 0, "memory_usage_estimate": 0}
