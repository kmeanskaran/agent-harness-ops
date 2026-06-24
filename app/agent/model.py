"""Model factory — pick the reasoning engine from config.

Defaults to the Ollama model already configured in .env, but the same harness
runs on Groq / OpenAI / Anthropic by setting MODEL_PROVIDER (+ the matching key).
"""
from __future__ import annotations

from typing import Any, Iterator, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from app.config import get_settings


def _mark_system_cached(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Add cache_control to every SystemMessage so Anthropic can cache it."""
    out: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            content = msg.content
            if isinstance(content, str):
                blocks: list[dict[str, Any]] = [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ]
            elif isinstance(content, list):
                blocks = []
                for i, block in enumerate(content):
                    b: dict[str, Any] = block if isinstance(block, dict) else {"type": "text", "text": block}
                    # Anthropic only allows one breakpoint per message; put it on the last block.
                    if i == len(content) - 1:
                        b = {**b, "cache_control": {"type": "ephemeral"}}
                    blocks.append(b)
            else:
                blocks = [{"type": "text", "text": str(content), "cache_control": {"type": "ephemeral"}}]
            out.append(SystemMessage(content=blocks))  # type: ignore[arg-type]
        else:
            out.append(msg)
    return out


def get_model() -> BaseChatModel:
    s = get_settings()
    provider = s.MODEL_PROVIDER

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=s.OLLAMA_MODEL,
            base_url=s.OLLAMA_BASE_URL,
            temperature=s.MODEL_TEMPERATURE,
        )

    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=s.MODEL_NAME or "llama-3.3-70b-versatile",
            temperature=s.MODEL_TEMPERATURE,
            api_key=s.GROQ_API_KEY or None,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=s.MODEL_NAME or "gpt-4.1",
            temperature=s.MODEL_TEMPERATURE,
            api_key=s.OPENAI_API_KEY or None,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        class _CachingChatAnthropic(ChatAnthropic):
            """ChatAnthropic with automatic prompt caching on system messages."""

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> ChatResult:
                return super()._generate(_mark_system_cached(messages), stop, run_manager, **kwargs)

            def _stream(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> Iterator[ChatGenerationChunk]:
                return super()._stream(_mark_system_cached(messages), stop, run_manager, **kwargs)

        return _CachingChatAnthropic(
            model=s.MODEL_NAME or "claude-sonnet-4-6",
            temperature=s.MODEL_TEMPERATURE,
            api_key=s.ANTHROPIC_API_KEY or None,
            betas=["prompt-caching-2024-07-31"],
        )

    raise ValueError(f"Unknown MODEL_PROVIDER: {provider!r}")
