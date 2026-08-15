"""Structured logging of the agent's tool decisions.

CloudWatch recorded *that* a Bedrock call happened, never *which* tool the model
asked for or what came back. That gap is why a loop burning ~90 turns without
writing a file could not be diagnosed from logs at all — the only way to tell
"asked for the wrong path" from "got a result and asked again" was to guess.

This handler logs one line per model turn and one per tool result, as JSON that
Logs Insights can filter by job_id. It is deliberately cheap and truncating: the
point is to see the *shape* of the loop, not to archive payloads.

Query the loop for a job with:

    fields @timestamp, turn, tool_calls.0.name, tool_calls.0.args_preview
    | filter job_id = "<id>" and event = "model_turn"
    | sort @timestamp asc
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("devvoice.agent")

# Enough of an argument to see a wrong path or an empty payload, short enough
# that 90 turns of it stays readable and cheap to ship.
_PREVIEW_CHARS = 200


def _preview(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS] + "…"


class ToolTraceHandler(BaseCallbackHandler):
    """Logs each model turn's tool calls and each tool's result size."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.turn = 0
        self.tool_calls = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self.turn += 1
        calls: list[dict] = []
        stop_reason = None
        try:
            for generation in response.generations[0]:
                message = getattr(generation, "message", None)
                if message is None:
                    continue
                stop_reason = (message.response_metadata or {}).get("stopReason")
                for call in getattr(message, "tool_calls", None) or []:
                    calls.append(
                        {"name": call.get("name"), "args_preview": _preview(call.get("args"))}
                    )
        except Exception:  # never let tracing break a run
            logger.debug("tool trace: could not parse llm response", exc_info=True)
            return

        self.tool_calls += len(calls)
        logger.info(
            "model turn",
            extra={
                "event": "model_turn",
                "job_id": self.job_id,
                "turn": self.turn,
                "n_tool_calls": len(calls),
                "tool_calls": calls,
                "stop_reason": stop_reason,
            },
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        text = str(output)
        logger.info(
            "tool result",
            extra={
                "event": "tool_result",
                "job_id": self.job_id,
                "turn": self.turn,
                "tool": kwargs.get("name"),
                "result_chars": len(text),
                "result_preview": _preview(text),
            },
        )

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        logger.warning(
            "tool error",
            extra={
                "event": "tool_error",
                "job_id": self.job_id,
                "turn": self.turn,
                "tool": kwargs.get("name"),
                "error_type": type(error).__name__,
                "error_msg": str(error),
            },
        )
