"""Prompts must contain no unrendered `{placeholder}` text.

The orchestrator graph is built once and cached (`build_orchestrator` is
`@lru_cache`-decorated with no arguments), so no per-job formatting pass ever
runs over these strings. A `{job_id}` left in a prompt therefore reaches the
model as five literal characters and sends it reading a path that cannot exist —
which is exactly how the dev environment burned ~90 model turns without writing
a single file. Nothing raises when this happens, so it needs a test.

The real workspace path is supplied in the user message instead; see
`run_job`'s `user_msg`.
"""

from __future__ import annotations

import re

import pytest

from app.agent.orchestrator import ORCHESTRATOR_PROMPT, _subagents

# A `{...}` run that looks like a format placeholder: no whitespace, no braces.
# Deliberately loose — any brace pair in a prompt is suspicious.
PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def test_orchestrator_prompt_has_no_unrendered_placeholder() -> None:
    found = PLACEHOLDER_RE.findall(ORCHESTRATOR_PROMPT)
    assert not found, (
        f"ORCHESTRATOR_PROMPT contains unrendered placeholders {found}. "
        "Nothing formats this string — the model would receive them literally."
    )


@pytest.mark.parametrize("spec", _subagents(), ids=lambda s: s["name"])
def test_subagent_prompt_has_no_unrendered_placeholder(spec: dict) -> None:
    found = PLACEHOLDER_RE.findall(spec["system_prompt"])
    assert not found, (
        f"Subagent {spec['name']!r} system_prompt contains unrendered "
        f"placeholders {found}. Subagents receive the workspace path in the "
        "task description the orchestrator writes, not via string formatting."
    )


def test_user_message_carries_the_real_workspace_path() -> None:
    """The one place the actual job_id must appear."""
    from app.agent.orchestrator import _workspace

    ws = _workspace("testjob123")
    assert ws == "/workspace/testjob123"
    assert not PLACEHOLDER_RE.findall(ws)
