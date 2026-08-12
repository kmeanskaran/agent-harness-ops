"""Model factory — pick the reasoning engine from config.

Defaults to the Ollama model already configured in .env, but the same harness
runs on Groq / OpenAI / Anthropic by setting MODEL_PROVIDER (+ the matching key).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

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
                    b: dict[str, Any] = (
                        block if isinstance(block, dict) else {"type": "text", "text": block}
                    )
                    # Anthropic only allows one breakpoint per message; put it on the last block.
                    if i == len(content) - 1:
                        b = {**b, "cache_control": {"type": "ephemeral"}}
                    blocks.append(b)
            else:
                blocks = [
                    {"type": "text", "text": str(content), "cache_control": {"type": "ephemeral"}}
                ]
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

    if provider == "bedrock_openai":
        # OpenAI-compatible Bedrock (`bedrock-mantle` endpoint). REQUIRED for
        # models that are NOT on the Converse/InvokeModel API — e.g. Google's
        # `google.gemma-4-e2b`, which is only served on `bedrock-mantle`'s
        # `/openai/v1` path. Uses the OpenAI SDK, not langchain-aws.
        #
        # Auth is a bearer token, NOT an OpenAI key. We never store one:
        #   - If AWS_BEARER_TOKEN_BEDROCK is set (e.g. injected into a Docker
        #     container), use it directly.
        #   - Otherwise mint a SHORT-TERM Bedrock API key from the ambient IAM
        #     identity (SSO profile in dev, ECS task role in prod). It inherits
        #     that principal's permissions, lasts <=12h, and provide_token()
        #     caches + auto-refreshes it. No long-term key, no stored secret.
        import os

        from langchain_openai import ChatOpenAI

        token = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
        if not token:
            from aws_bedrock_token_generator import provide_token

            token = provide_token()  # short-term key from the IAM credential chain

        return ChatOpenAI(
            model=s.MODEL_NAME or "google.gemma-4-e2b",
            temperature=s.MODEL_TEMPERATURE,
            api_key=token,
            base_url=f"https://bedrock-mantle.{s.AWS_REGION}.api.aws/openai/v1",
            # Gemma 4 E2B reasons heavily; AWS recommends reasoning_effort="high"
            # to keep reasoning out of the final text. Add if quality needs it:
            #   model_kwargs={"reasoning_effort": "high"},
        )

    if provider == "bedrock":
        # Claude on Amazon Bedrock. Credentials are NEVER passed here — boto3
        # resolves them from the default chain: your `aws configure` profile in
        # dev, the ECS task role in prod. No API key, no secret in the container.
        from langchain_aws import ChatBedrockConverse

        class _CachingChatBedrock(ChatBedrockConverse):
            """ChatBedrockConverse with explicit prompt caching on system messages.

            Bedrock has no *automatic* prompt caching — only explicit cache
            breakpoints — so we reuse the same cache_control blocks as the
            Anthropic path; langchain-aws maps them to Bedrock cachePoints.
            """

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

        # Bedrock needs a full inference-profile / model ID. Confirm the exact ID
        # for your region with `aws bedrock list-inference-profiles`.
        model_id = s.MODEL_NAME or "us.anthropic.claude-sonnet-4-6"

        # Only Anthropic (and a few other) models accept cachePoint blocks. Gemma
        # rejects the whole request with AccessDeniedException ("You invoked an
        # unsupported model or your request did not allow prompt caching"), so
        # send plain messages for anything that isn't Claude.
        if "anthropic" not in model_id:
            return ChatBedrockConverse(
                model=model_id,
                region_name=s.AWS_REGION,
                temperature=s.MODEL_TEMPERATURE,
            )

        return _CachingChatBedrock(
            model=model_id,
            region_name=s.AWS_REGION,
            temperature=s.MODEL_TEMPERATURE,
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
