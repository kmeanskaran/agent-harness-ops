"""Central configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load the repo-root .env once, regardless of where the process starts.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

# Paths inside the package (used to seed skills + context into agent state).
APP_DIR = Path(__file__).resolve().parent
SKILLS_DIR = APP_DIR / "skills"
CONTEXT_DIR = APP_DIR / "context"


# Terraform seeds not-yet-configured secrets with `REPLACE_ME`. That is a
# non-empty string, so a plain `if not s.SOME_KEY` guard passes and the code
# proceeds to call the API with a junk credential. Treat the sentinels as unset
# at the boundary, so every existing truthiness guard is correct for free.
_PLACEHOLDER_VALUES = {"", "REPLACE_ME", "replace_me", "changeme", "CHANGEME", "TODO"}


def _secret(name: str, default: str = "") -> str:
    """Read a secret, mapping placeholder sentinels to '' (i.e. unset)."""
    value = os.getenv(name, default).strip()
    return "" if value in _PLACEHOLDER_VALUES else value


class Settings:
    """Runtime settings. Read from env so the same image runs anywhere."""

    # --- Job store + Celery broker (one Redis instance, three roles) ---
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    JOB_TTL_SECONDS: int = int(os.getenv("JOB_TTL_SECONDS", "7200"))  # 2h
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://devvoice:devvoice@localhost:5432/devvoice"
    )

    # --- Model selection ---
    # MODEL_PROVIDER one of: ollama (default) | groq | openai | anthropic | bedrock
    MODEL_PROVIDER: str = os.getenv("MODEL_PROVIDER", "ollama").lower()
    MODEL_NAME: str = os.getenv("MODEL_NAME", "")
    MODEL_TEMPERATURE: float = float(os.getenv("MODEL_TEMPERATURE", "0.4"))

    # Bedrock: region for the Bedrock client. No key — boto3 resolves creds from
    # the default chain (local `aws configure` profile in dev, ECS task role in prod).
    AWS_REGION: str = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

    # Ollama
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Provider keys. `_secret` maps REPLACE_ME-style placeholders to "" so the
    # `if not s.KEY` guards at the call sites actually fire.
    ANTHROPIC_API_KEY: str = _secret("ANTHROPIC_API_KEY")
    GROQ_API_KEY: str = _secret("GROQ_API_KEY")
    OPENAI_API_KEY: str = _secret("OPENAI_API_KEY")
    TAVILY_API_KEY: str = _secret("TAVILY_API_KEY")

    # --- Job wall-clock limits (Celery) ---
    # An agent loop can stall without ever raising; these bound it in seconds.
    # Soft raises inside the task so it can be marked failed; hard kills the
    # child process. Keep hard > soft with room for the cleanup handler to run.
    JOB_SOFT_TIME_LIMIT: int = int(os.getenv("JOB_SOFT_TIME_LIMIT", "900"))  # 15m
    JOB_HARD_TIME_LIMIT: int = int(os.getenv("JOB_HARD_TIME_LIMIT", "1020"))  # 17m

    # Context engineering: summarize history once it grows past this many tokens.
    SUMMARIZE_TRIGGER_TOKENS: int = int(os.getenv("SUMMARIZE_TRIGGER_TOKENS", "12000"))
    SUMMARIZE_KEEP_MESSAGES: int = int(os.getenv("SUMMARIZE_KEEP_MESSAGES", "20"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
