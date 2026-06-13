"""Run the DevVoice pipeline once, in-process, with no Redis or Celery.

Useful for testing the agent against your configured model:

    uv run python -m scripts.run_once
"""
from __future__ import annotations

import json

from app.agent.orchestrator import run_job
from app.worker.tasks import build_brief

SAMPLE = {
    "readme": "# RealtimeBoard\nA live collaboration board. Updates are pushed "
    "with Redis pub/sub instead of HTTP polling, and scheduled cleanup runs on "
    "Celery beat.",
    "learnings": [
        "Redis pub/sub is dramatically faster than polling for real-time updates",
        "Celery beat is underrated for scheduled jobs",
    ],
    "hard_parts": ["Managing Celery task state across worker restarts"],
    "tone": "honest and practical",
    "audience": "intermediate developers",
    "platforms": ["x", "linkedin"],
}


def main() -> None:
    brief = build_brief(SAMPLE)

    def on_progress(status: str, step: str) -> None:
        print(f"  [progress] status={status} step={step}")

    print("Running DevVoice pipeline (this calls your configured model)...")
    result = run_job(
        job_id="local",
        brief_md=brief,
        platforms=SAMPLE["platforms"],
        on_progress=on_progress,
    )
    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
