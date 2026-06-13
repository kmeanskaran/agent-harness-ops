"""Model factory — pick the reasoning engine from config.

Defaults to the Ollama model already configured in .env, but the same harness
runs on Groq / OpenAI / Anthropic by setting MODEL_PROVIDER (+ the matching key).
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


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
        # Requires `langchain-anthropic`. Latest capable default per idea.md.
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=s.MODEL_NAME or "claude-sonnet-4-6",
            temperature=s.MODEL_TEMPERATURE,
            api_key=s.ANTHROPIC_API_KEY or None,
        )

    raise ValueError(f"Unknown MODEL_PROVIDER: {provider!r}")
