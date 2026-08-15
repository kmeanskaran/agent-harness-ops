"""The LLM cache must round-trip tool calls.

A cached reply is replayed to LangGraph in place of a real model response. If
the round-trip drops `tool_calls`, the replayed message looks like a plain final
answer: nothing to dispatch, the graph ends after one turn, no files are
written, and `assemble_result` sees empty drafts. That is the same silent blank
output a model with no Converse tool-call support produces — but triggered by a
cache hit, so it would appear intermittently and only once the cache is warm.

Nothing raises when this happens, so it needs a test.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration

from app.agent.cache import _deserialise, _serialise

TOOL_CALL = {
    "name": "write_file",
    "args": {"file_path": "/workspace/abc123/linkedin_draft.md", "content": "hi"},
    "id": "tooluse_abc",
    "type": "tool_call",
}


def _round_trip(message: AIMessage) -> AIMessage:
    generation = ChatGeneration(message=message, text=message.text)
    return _deserialise(_serialise([generation]))[0].message  # type: ignore[union-attr]


def test_tool_calls_survive_round_trip() -> None:
    original = AIMessage(
        content=[{"type": "tool_use", "id": "tooluse_abc", "name": "write_file", "input": {}}],
        tool_calls=[TOOL_CALL],
        response_metadata={"stopReason": "tool_use"},
    )
    restored = _round_trip(original)

    assert restored.tool_calls == [TOOL_CALL], (
        "tool_calls were lost in the cache round-trip; a cache hit would look "
        "like a final answer and the graph would end without writing anything."
    )


def test_response_metadata_survives_round_trip() -> None:
    """stopReason is how we tell 'wants a tool' from 'done'."""
    original = AIMessage(content="done", response_metadata={"stopReason": "end_turn"})
    assert _round_trip(original).response_metadata.get("stopReason") == "end_turn"


def test_plain_text_reply_still_round_trips() -> None:
    original = AIMessage(content="just text")
    restored = _round_trip(original)
    assert restored.content == "just text"
    assert restored.tool_calls == []
