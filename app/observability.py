"""No-op stand-ins for the Langfuse SDK, so tracing can be switched off wholesale.

WHY THIS EXISTS
Langfuse is wired into four modules through decorators and multi-line
`update_current_trace(...)` calls. Commenting out ~17 individual call sites to
disable tracing means editing live control flow in code paths that only run in
the deployed worker — a lot of syntax risk for a change whose whole point is to
remove a variable from an investigation.

Instead, every module keeps its call sites exactly as written and swaps only its
import: the real Langfuse import is commented out and this module is imported in
its place. The calls all still happen, they just do nothing.

The keys are `REPLACE_ME` in dev, so the real SDK was not usefully reporting
anywhere anyway; it was only adding failure surface to jobs that were already
failing for other reasons.

TO RE-ENABLE
In each of main.py, app/routes/content.py, app/worker/tasks.py and
app/agent/orchestrator.py, uncomment the `from langfuse...` line and delete the
`from app.observability import ...` line below it. Nothing else changes. Set
real values for LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL
first, or the SDK will retry against a host that rejects them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class Langfuse:
    """Accepts the real constructor's kwargs and does nothing with them."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _LangfuseContext:
    """The `langfuse_context` singleton's surface, as used in this codebase."""

    def update_current_trace(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update_current_observation(self, *args: Any, **kwargs: Any) -> None:
        pass


langfuse_context = _LangfuseContext()


def observe(*_args: Any, **_kwargs: Any) -> Callable[[F], F]:
    """No-op form of `@observe(name=...)`.

    Returns the decorated function completely untouched — no wrapper at all.
    That keeps __name__, attributes and the static type intact, which matters
    because `@observe` sits under `@celery_app.task`: a wrapper here would hide
    `.delay` from type checkers and change what Celery registers.
    """

    def decorator(func: F) -> F:
        return func

    return decorator
