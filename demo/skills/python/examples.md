# Python Skill — Worked Examples

Follow the structure of these examples when answering.

---

## Example 1: Writing a New Function

**User asks:** "Write a function to read a CSV and return rows as dicts."

**Good answer pattern:**

```python
import csv
from pathlib import Path
from typing import Any


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    """Read a CSV file and return its rows as dictionaries.

    Args:
        path: Path to the CSV file.

    Returns:
        A list of dicts keyed by the CSV header row.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty or has no header.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    with file_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file has no header row: {file_path}")
        return list(reader)
```

**How it works:**
- `csv.DictReader` maps each row to the header automatically.
- `pathlib.Path` handles cross-platform paths.
- Explicit errors for missing file and missing header.

---

## Example 2: Debugging a Traceback

**User asks:** "Why does this fail? `KeyError: 'name'` when doing `user['name']`"

**Good answer pattern:**
1. Explain the root cause: the dict has no `'name'` key at that point.
2. Show how to inspect: `print(user.keys())`.
3. Give the fix with options:

```python
# Option A: default value
name = user.get("name", "unknown")

# Option B: validate early and fail with a clear message
if "name" not in user:
    raise ValueError(f"User record missing 'name': {user}")
```

4. Recommend the structural fix (e.g., a dataclass/Pydantic model) so the bug class disappears.

---

## Example 3: Async I/O

**User asks:** "Fetch 10 URLs concurrently."

```python
import asyncio

import httpx


async def fetch_all(urls: list[str], timeout: float = 10.0) -> list[str]:
    """Fetch all URLs concurrently and return their response bodies."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        responses = await asyncio.gather(
            *(client.get(u) for u in urls), return_exceptions=True
        )
    results: list[str] = []
    for url, resp in zip(urls, responses):
        if isinstance(resp, Exception):
            results.append(f"ERROR fetching {url}: {resp}")
        else:
            results.append(resp.text)
    return results


# asyncio.run(fetch_all(["https://example.com"] * 10))
```

Note the dependency callout: `pip install httpx`.

---

## Example 4: Pytest Structure

```python
import pytest

from mymodule import read_csv_rows


def test_read_csv_rows_returns_dicts(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,age\nalice,30\n", encoding="utf-8")
    rows = read_csv_rows(csv_file)
    assert rows == [{"name": "alice", "age": "30"}]


def test_read_csv_rows_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        read_csv_rows("does/not/exist.csv")
```