# Report Writer Skill — Example Reports

These show the expected quality. Match this structure exactly.

---

## Example 1: After a Coding Question

User asked: "Write a Python function to upload a file to S3."
The agent answered using the `python` and `aws` skills, then saved:

**File:** `/reports/s3-upload-python-report.md`

```markdown
# Report: Uploading Files to S3 with Python

**Date:** 2026-06-04
**Requested by:** user
**Skills used:** python, aws

## 1. Question
How to upload a local file to an Amazon S3 bucket using Python.

## 2. Approach
- Read the `python` skill for coding standards (type hints, error handling).
- Read the `aws` skill for boto3 patterns and security rules.
- Produced a boto3-based function with `ClientError` handling.

## 3. Key Findings
- `boto3.client("s3").upload_file()` is the simplest reliable upload API.
- Errors should be caught as `botocore.exceptions.ClientError`, not bare except.
- Credentials must come from IAM roles/profiles, never hard-coded.
- The target bucket should keep Block Public Access enabled.

## 4. Answer
\```python
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3", region_name="us-east-1")

def upload_file(local_path: str, bucket: str, key: str) -> bool:
    """Upload a local file to S3. Returns True on success."""
    try:
        s3.upload_file(local_path, bucket, key)
        return True
    except ClientError as e:
        print(f"Upload failed: {e.response['Error']['Code']}")
        return False
\```

## 5. Sources / Tools Used
- Skill files: `python/instructions.md`, `aws/examples.md`
- Model knowledge of boto3 API.

## 6. Caveats & Next Steps
- For files >100 MB, consider multipart upload via `TransferConfig`.
- Add retries with botocore's `config=Config(retries={"max_attempts": 5})` for production.
```

---

## Example 2: After a Conceptual / Research Question

User asked: "How does memory work in LangGraph?"

**File:** `/reports/langgraph-memory-report.md`

```markdown
# Report: How Memory Works in LangGraph

**Date:** 2026-06-04
**Requested by:** user
**Skills used:** langgraph

## 1. Question
How LangGraph provides memory/persistence across agent conversations.

## 2. Approach
- Read the `langgraph` skill instructions on checkpointers and stores.
- Distinguished short-term (per-thread) vs long-term (cross-thread) memory.

## 3. Key Findings
- A **checkpointer** (e.g., `MemorySaver`) snapshots graph state after each step.
- Memory is scoped by `thread_id` in the invoke config — same id = same conversation.
- Long-term, cross-thread memory uses a `BaseStore` (e.g., `InMemoryStore`, Postgres).
- Checkpointing also enables human-in-the-loop interrupts and time travel.

## 4. Answer
Compile the graph with a checkpointer and pass a thread id at invoke time:
\```python
app = graph.compile(checkpointer=MemorySaver())
app.invoke(inputs, config={"configurable": {"thread_id": "user-1"}})
\```
For durable memory between sessions, swap `MemorySaver` for a SQLite/Postgres
checkpointer and use a `BaseStore` for per-user facts.

## 5. Sources / Tools Used
- Skill files: `langgraph/instructions.md`, `langgraph/examples.md`

## 6. Caveats & Next Steps
- `MemorySaver` is in-process only; it is lost on restart.
- Next step: demo `StoreBackend` for cross-thread memory in deepagents.
```

---

## Confirmation Line Pattern

End the chat reply with exactly one line like:

> 📄 Report saved to /reports/langgraph-memory-report.md