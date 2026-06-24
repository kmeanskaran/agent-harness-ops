# Python Skill — Detailed Instructions

Follow this workflow for every Python-related query.

## Step 1: Clarify the Task
- Identify what the user wants: new code, bug fix, refactor, explanation, or review.
- Note constraints: Python version, allowed libraries, performance needs, environment (script / notebook / web app).
- If the request is ambiguous, state your assumptions explicitly before answering.

## Step 2: Design Before Coding
- For anything non-trivial, outline the approach in 1-3 bullet points first.
- Choose the simplest data structure that works (dict/list/set/dataclass before custom classes).
- Prefer composition over inheritance.

## Step 3: Coding Standards (MUST follow)
1. **PEP 8** — 4-space indent, snake_case functions/variables, PascalCase classes, UPPER_CASE constants.
2. **Type hints** — annotate every function signature: `def fetch(url: str, timeout: float = 5.0) -> dict[str, Any]:`
3. **Docstrings** — Google style with Args / Returns / Raises sections on public APIs.
4. **f-strings** for formatting; never `%` or `.format()` in new code.
5. **Pathlib** over `os.path` for file paths.
6. **Context managers** (`with`) for files, locks, connections.
7. **Comprehensions** when they stay readable; loops when they don't.
8. **Dataclasses / Pydantic** for structured data instead of raw dicts.
9. **Specific exceptions** — `except ValueError:` not `except:`; raise with helpful messages.
10. **Logging** module instead of print() for anything beyond tiny scripts.

## Step 4: Error Handling & Edge Cases
- Validate inputs at function boundaries.
- Handle: empty inputs, None values, type mismatches, missing files, network failures.
- Fail fast with clear error messages.

## Step 5: Testing Guidance
- When writing significant code, include or offer pytest tests.
- Test names: `test_<function>_<scenario>` (e.g., `test_parse_empty_string_returns_none`).
- Cover the happy path + at least one edge case + one failure case.

## Step 6: Explain Your Answer
- After the code block, add a short "How it works" section (2-5 bullets).
- Call out any third-party dependencies and how to install them (`pip install ...` / `uv add ...`).
- Mention performance or security caveats if relevant.

## Async Code Rules
- Use `async`/`await` with `asyncio` only when there is real I/O concurrency to exploit.
- Never block the event loop with sync I/O — use `asyncio.to_thread` for CPU-bound or legacy sync calls.
- Always `await` coroutines; warn about fire-and-forget tasks.

## Refactoring Rules
- Preserve external behavior; say so explicitly.
- Show before → after when it aids understanding.
- One concern per refactor step; list the changes you made.