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


class Settings:
    """Runtime settings. Read from env so the same image runs anywhere."""

    # --- Job store + Celery broker (one Redis instance, three roles) ---
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    JOB_TTL_SECONDS: int = int(os.getenv("JOB_TTL_SECONDS", "7200"))  # 2h
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://devvoice:devvoice@localhost:5432/devvoice"
    )

    # --- Model selection ---
    # MODEL_PROVIDER one of: ollama (default, from .env) | groq | openai | anthropic
    MODEL_PROVIDER: str = os.getenv("MODEL_PROVIDER", "ollama").lower()
    MODEL_NAME: str = os.getenv("MODEL_NAME", "")
    MODEL_TEMPERATURE: float = float(os.getenv("MODEL_TEMPERATURE", "0.4"))

    # Ollama
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Provider keys
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # Context engineering: summarize history once it grows past this many tokens.
    SUMMARIZE_TRIGGER_TOKENS: int = int(os.getenv("SUMMARIZE_TRIGGER_TOKENS", "12000"))
    SUMMARIZE_KEEP_MESSAGES: int = int(os.getenv("SUMMARIZE_KEEP_MESSAGES", "20"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
