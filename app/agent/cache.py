"""Provider-agnostic LLM response cache backed by Redis.

Works with every LangChain provider (Groq, Ollama, OpenAI, Anthropic) because
it intercepts at the LangChain generation layer, before any API call is made.

A cache hit means zero tokens sent to the provider — the serialised response is
returned directly from Redis, saving both cost and latency.

Cache key: SHA-256 of (llm_string + prompt)
  - llm_string encodes model name + temperature + provider config, so responses
    are never shared across different model configurations.
  - prompt is the full stringified message list.

TTL defaults to 24 h, configurable via LLM_CACHE_TTL_SECONDS in the environment.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Sequence

from langchain_core.caches import BaseCache
from langchain_core.outputs import ChatGeneration, Generation

from app.redis_store import get_client

logger = logging.getLogger(__name__)

_TTL = int(os.getenv("LLM_CACHE_TTL_SECONDS", "86400"))  # 24 h default
_PREFIX = "llmcache:"


def _cache_key(prompt: str, llm_string: str) -> str:
    digest = hashlib.sha256(f"{llm_string}\x00{prompt}".encode()).hexdigest()
    return f"{_PREFIX}{digest}"


def _serialise(generations: Sequence[Generation]) -> str:
    items = []
    for g in generations:
        if isinstance(g, ChatGeneration):
            items.append({
                "type": "chat",
                "text": g.text,
                "message": {
                    "type": g.message.type,
                    "content": g.message.content,
                    "additional_kwargs": g.message.additional_kwargs,
                },
                "generation_info": g.generation_info,
            })
        else:
            items.append({
                "type": "base",
                "text": g.text,
                "generation_info": g.generation_info,
            })
    return json.dumps(items)


def _deserialise(raw: str) -> list[Generation]:
    from langchain_core.messages import AIMessage
    items = json.loads(raw)
    out: list[Generation] = []
    for item in items:
        if item["type"] == "chat":
            m = item["message"]
            msg = AIMessage(
                content=m["content"],
                additional_kwargs=m.get("additional_kwargs", {}),
            )
            out.append(ChatGeneration(
                text=item["text"],
                message=msg,
                generation_info=item.get("generation_info"),
            ))
        else:
            out.append(Generation(
                text=item["text"],
                generation_info=item.get("generation_info"),
            ))
    return out


class RedisLLMCache(BaseCache):
    """LangChain BaseCache backed by the app's existing Redis instance."""

    def __init__(self, ttl: int = _TTL) -> None:
        self._ttl = ttl

    def lookup(self, prompt: str, llm_string: str) -> list[Generation] | None:
        key = _cache_key(prompt, llm_string)
        try:
            raw = get_client().get(key)  # type: ignore[assignment]
        except Exception:
            logger.warning("LLM cache lookup failed", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            result = _deserialise(raw)  # type: ignore[arg-type]
            logger.debug("LLM cache hit: %s", key)
            return result
        except Exception:
            logger.warning("LLM cache deserialisation failed; cache miss", exc_info=True)
            return None

    def update(self, prompt: str, llm_string: str, return_val: Sequence[Generation]) -> None:
        key = _cache_key(prompt, llm_string)
        try:
            get_client().setex(key, self._ttl, _serialise(return_val))
            logger.debug("LLM cache set: %s (ttl=%ds)", key, self._ttl)
        except Exception:
            logger.warning("LLM cache write failed", exc_info=True)

    async def alookup(self, prompt: str, llm_string: str) -> list[Generation] | None:
        return self.lookup(prompt, llm_string)

    async def aupdate(self, prompt: str, llm_string: str, return_val: Sequence[Generation]) -> None:
        self.update(prompt, llm_string, return_val)

    def clear(self, **_kwargs: Any) -> None:
        try:
            client = get_client()
            keys = client.keys(f"{_PREFIX}*")  # type: ignore[assignment]
            if keys:
                client.delete(*keys)  # type: ignore[misc]
        except Exception:
            logger.warning("LLM cache clear failed", exc_info=True)
