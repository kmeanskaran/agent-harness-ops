# LangFuse Observability Guide for DevVoice

LangFuse is now integrated into DevVoice to track agent performance, costs, latency, and quality metrics. This guide shows you how to use it.

## Quick Start

### 1. Credentials Already Configured

Your `.env` file already has LangFuse credentials:
```
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"
```

### 2. Install LangFuse

```bash
pip install langfuse
# Or if updating requirements:
pip install -r requirements.txt
```

### 3. Verify Setup

```bash
# Start your FastAPI app
uvicorn main:app --reload

# Send a test request
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "readme": "# My Project\n\nThis is my project.",
    "platforms": ["x"],
    "tone": "casual",
    "audience": "developers"
  }'

# Check LangFuse dashboard: https://us.cloud.langfuse.com
```

---

## What LangFuse Tracks

### 1. **API Request** (`enqueue_generation_job`)
When a user calls `/generate`, `/generate-x-post`, etc.

**Tracked:**
- `email` — who is generating content?
- `platforms` — which platforms? (x, linkedin, devto)
- `tone` — what tone?
- `audience` — target audience?
- `readme_length` — size of input
- `learnings_count` — how many learnings?
- `hard_parts_count` — how many hard parts?
- `job_id` — unique identifier
- Result: `job_id` returned to user

**When it happens:**
```
User → POST /generate → enqueue_generation_job → job_id returned
                           ↓
                        LangFuse logged
```

### 2. **Celery Task** (`generate_content_task`)
Worker picks up the job and starts processing.

**Tracked:**
- `status: "running"` → `status: "completed"` or `status: "failed"`
- `duration_seconds` — how long did the job take?
- `platforms_generated` — which platforms finished?
- `email` — which user?
- `readme_length` — input size
- `tone`, `audience` — job params
- Error details if it fails

**When it happens:**
```
Job queued → Celery worker picks it up → generate_content_task runs
                                              ↓
                                        LangFuse logged
```

### 3. **Pipeline Execution** (`devvoice_pipeline`)
The orchestrator runs the full pipeline: extract → write → review.

**Tracked:**
- `duration_seconds` — total pipeline time
- Which platforms were generated
- Whether it succeeded
- Metadata about the brief

**When it happens:**
```
generate_content_task
  ↓
  run_job (orchestrator)
     ├─ Extractor agent
     ├─ X-Writer agent (if requested)
     ├─ LinkedIn-Writer agent (if requested)
     ├─ Devto-Writer agent (if requested)
     └─ Reviewer agent
  ↓
  LangFuse logged
```

---

## Viewing Results in LangFuse Dashboard

### Step 1: Log In
Go to **https://us.cloud.langfuse.com**
- Email: (your email for LangFuse account)
- Password: (your password)

### Step 2: Navigate to Traces Tab
Click **Traces** in the left sidebar.

You'll see a table like this:

```
Timestamp          | Trace Name              | Duration | Status
2024-06-25 10:30   | enqueue_generation_job  | 45ms     | ✓
2024-06-25 10:31   | generate_content_task   | 28.3s    | ✓
2024-06-25 10:31   | devvoice_pipeline       | 27.8s    | ✓
```

### Step 3: Click a Trace to See Details

**Example: Click on `generate_content_task`**

You'll see:
```
TRACE DETAILS
=============
Name: generate_content_task
Duration: 28.3 seconds
Status: ✓ Success

USER CONTEXT
- User ID: test@example.com
- Session ID: a1b2c3d4

METADATA
- job_id: a1b2c3d4
- platforms: ["x", "linkedin"]
- tone: casual
- audience: developers
- readme_length: 512
- email: test@example.com
- status: completed
- duration_seconds: 28.3
- platforms_generated: ["x_thread", "linkedin_post"]
```

### Step 4: View Subtraces (Agent Hierarchy)

Each trace shows what happened inside. Click to expand:

```
generate_content_task (28.3s)
  └─ devvoice_pipeline (27.8s)
       ├─ [1] Extractor runs
       ├─ [2] X-Writer runs (if x in platforms)
       ├─ [3] LinkedIn-Writer runs (if linkedin in platforms)
       ├─ [4] Devto-Writer runs (if devto in platforms)
       └─ [5] Reviewer checks all outputs
```

(Note: Currently, individual agent runs aren't separately tracked—only the pipeline. This can be enhanced.)

---

## Key Metrics to Watch

### 1. **Latency (Duration)**

**What:** How long did the job take end-to-end?

**Where:** LangFuse Traces → `generate_content_task` → Duration

**Goal:** < 30 seconds for most requests

**If slow:**
- Check if Celery workers are available (maybe backlog?)
- Check if Redis cache is working (cache hits should be fast)
- Check if orchestrator is stuck on a particular agent

```bash
# View duration trend
# LangFuse → Analytics → Average request duration over time
```

### 2. **Success Rate**

**What:** % of jobs that complete successfully vs fail?

**Where:** LangFuse → Analytics → Success Rate

**Goal:** > 99% (very few failures)

**If low:**
- Check error messages in failed traces
- Check orchestrator logs
- Check if agents are refusing content

### 3. **Cost Per Request**

**What:** How much did this request cost? (Not auto-calculated by LangFuse, but you can track it)

**Current:** Not tracked automatically. To add:
```python
# In app/worker/tasks.py, track cost
langfuse_context.update_current_trace(
    {
        "metadata": {
            "cost_cents": 20,  # Calculate based on tokens
            "tokens_input": 5000,
            "tokens_output": 1000,
        }
    }
)
```

**Where to check:** LangFuse Metadata section

---

## Example Traces You'll See

### Successful Request

```
TRACE: enqueue_generation_job
├─ Status: ✓
├─ Duration: 45ms
├─ User: user@example.com
├─ Job ID: abc123xyz
└─ Metadata:
   - platforms: ["x"]
   - readme_length: 1024

TRACE: generate_content_task
├─ Status: ✓
├─ Duration: 28.3s
├─ Metadata:
   - status: completed
   - platforms_generated: ["x_thread"]

TRACE: devvoice_pipeline
├─ Status: ✓
├─ Duration: 27.8s
└─ Metadata:
   - success: true
```

### Failed Request

```
TRACE: generate_content_task
├─ Status: ✗ FAILED
├─ Duration: 5.2s
├─ Metadata:
   - status: failed
   - error: "ValueError: Orchestrator timeout"

TRACE: devvoice_pipeline
├─ Status: ✗ FAILED
├─ Duration: 4.8s
└─ Metadata:
   - error details in trace
```

---

## Advanced: Add Custom Scoring

You can manually score traces after they complete. Example:

```python
from langfuse import Langfuse
import os

langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    baseUrl=os.getenv("LANGFUSE_BASE_URL"),
)

# After a job completes, score it
langfuse.score_trace(
    trace_id="abc123xyz",
    name="fact_accuracy",
    value=0.92,
    comment="9/10 facts verified against README",
)

langfuse.score_trace(
    trace_id="abc123xyz",
    name="content_quality",
    value=0.85,
    comment="Good structure, minor tone issues",
)
```

Then in LangFuse dashboard, you can see scores over time:
- Fact accuracy trending up? ✓
- Quality scores dropping? ⚠️

---

## Troubleshooting

### Issue: No traces appear in LangFuse

**Check:**
1. Are credentials in `.env` correct?
   ```bash
   grep LANGFUSE .env
   ```

2. Is LangFuse library installed?
   ```bash
   pip show langfuse
   ```

3. Is your app running? Did you send a request?
   ```bash
   curl -X POST http://localhost:8000/generate ...
   ```

4. Check app logs for errors:
   ```bash
   # Look for any LangFuse errors in stdout
   ```

### Issue: Traces appear but metadata is empty

**Check:**
1. Are `@observe` decorators in place?
   - `app/worker/tasks.py` — `@observe(name="generate_content_task")`
   - `app/agent/orchestrator.py` — `@observe(name="devvoice_pipeline")`
   - `app/routes/content.py` — `@observe(name="enqueue_generation_job")`

2. Are you updating the trace with metadata?
   ```python
   langfuse_context.update_current_trace({"metadata": {"key": "value"}})
   ```

### Issue: "AttributeError: langfuse_context"

Make sure you imported it:
```python
from langfuse.decorators import observe, langfuse_context
```

---

## Checklist: Is LangFuse Working?

- [ ] Credentials in `.env` ✓
- [ ] `pip install langfuse` ✓
- [ ] `@observe` decorators added to key functions ✓
- [ ] App starts without errors ✓
- [ ] Send test request to `/generate` ✓
- [ ] Check LangFuse dashboard: https://us.cloud.langfuse.com
- [ ] Can see traces in "Traces" tab ✓
- [ ] Click a trace and see metadata ✓

---

## Next Steps

### Short Term
- Monitor success rate (should be >99%)
- Monitor latency (should be <30s)
- Check for errors in failed traces

### Medium Term
- Add cost tracking (tokens × price)
- Add fact-accuracy scoring after each job
- Create dashboards for trends

### Long Term
- Integrate with Slack alerts (alert on high error rate)
- Export metrics to data warehouse for analysis
- Use LangFuse to find bottlenecks and optimize

---

## Architecture: How LangFuse Tracks Your Pipeline

```
User Request
    ↓
FastAPI /generate endpoint
    ↓
@observe("enqueue_generation_job")  ← LangFuse logs API call
    ↓
Job enqueued to Celery
    ↓
Celery worker picks up job
    ↓
@observe("generate_content_task")  ← LangFuse logs task start/end
    ↓
    └─→ run_job() orchestrator
        ↓
        @observe("devvoice_pipeline")  ← LangFuse logs pipeline
        ↓
        ├─ Extractor agent (not separately tracked yet)
        ├─ X-Writer agent (not separately tracked yet)
        ├─ LinkedIn-Writer agent (not separately tracked yet)
        ├─ Devto-Writer agent (not separately tracked yet)
        └─ Reviewer agent (not separately tracked yet)
        ↓
    ← Returns result
    ↓
LangFuse logs completion
```

Each `@observe()` creates a **trace** in LangFuse. You can click through the hierarchy to see what happened.

---

## Files Modified

If you want to review the changes made:

1. **main.py** — Initialize LangFuse at startup
2. **app/agent/orchestrator.py** — `@observe` decorator on `run_job()`
3. **app/worker/tasks.py** — `@observe` decorator on `generate_content_task()`
4. **app/routes/content.py** — `@observe` decorator on `_enqueue()`
5. **requirements.txt** — Added `langfuse>=2.0.0`

---

## Summary

LangFuse is now integrated and tracking:
- ✅ Every API request (who, what, when)
- ✅ Every job execution (duration, success/failure)
- ✅ End-to-end pipeline execution (latency, status)

**To view:** https://us.cloud.langfuse.com → Traces tab

**To debug:** Click any trace to see full details and metadata.

**To extend:** Add custom scoring, cost tracking, or agent-level observability.

Enjoy! 🚀
