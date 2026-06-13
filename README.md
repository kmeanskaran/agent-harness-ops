# DevVoice — Content Creation Agent Harness

Turn a GitHub README into a **reviewed** X thread, LinkedIn post, and/or dev.to article — all accurate to your source, zero AI filler.

The magic: a **review step** that checks every claim against the original source. A single LLM call can't do that. The harness can.

## What it is

**Architecture**: FastAPI + Celery + Redis + DeepAgents

- **3 clean endpoints** — one per platform
- **Async job queue** — returns job_id immediately, runs agent in background
- **Redis tracking** — status updates (queued → running → extracting → writing → reviewing → completed)
- **Rate limiting** — 10 requests/min per IP
- **Four DeepAgents concepts** — backends, context engineering, skills, subagents

## Setup

### 1. Install dependencies

```bash
uv sync
```

Or with pip:
```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` to choose your model:
```env
MODEL_PROVIDER=ollama        # or: groq, openai, anthropic
OLLAMA_MODEL=gemma4:31b-cloud
OLLAMA_BASE_URL=http://localhost:11434
REDIS_URL=redis://localhost:6379/0
```

For other providers:
```env
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Run the App

### Option A: Direct Python + FastAPI (requires Redis + Celery worker)

**Terminal 1 — Redis:**
```bash
redis-server
```

**Terminal 2 — Celery Worker:**
```bash
uv run celery -A app.worker.celery_app worker --loglevel=info
```

**Terminal 3 — FastAPI:**
```bash
uv run uvicorn main:app --reload --port 8000
```

### Option B: Docker (all-in-one)

```bash
docker compose up --build
```

This starts:
- API on `localhost:8000`
- Worker (background)
- Redis (in-memory)

### Option C: One-off Python script (no queue, no Redis)

```bash
uv run python -m scripts.run_once
```

---

## API Endpoints

### Base URL
```
http://localhost:8000
```

### 1. Generate X (Twitter) Thread

**Request:**
```bash
curl -X POST http://localhost:8000/generate-x-post \
  -H 'Content-Type: application/json' \
  -d '{
    "readme": "# RealtimeBoard\n\nA live collaboration board using Redis pub/sub for real-time updates instead of HTTP polling.\n\n## Key tech: Redis, Celery, WebSocket",
    "learnings": [
      "Redis pub/sub is 10x faster than HTTP polling for real-time updates",
      "Celery beat handles scheduled jobs better than cron"
    ],
    "hard_parts": [
      "Managing Celery task state across worker restarts",
      "Debugging Redis connection timeouts in production"
    ],
    "tone": "honest and practical",
    "audience": "intermediate developers"
  }'
```

**Response (immediate):**
```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "queued"
}
```

### 2. Check Result

Poll until `status` is `"completed"`:

```bash
curl http://localhost:8000/result/a1b2c3d4e5f6
```

**Response (while running):**
```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "running",
  "current_step": "writing",
  "x_thread": null,
  "linkedin_post": null,
  "devto_article": null,
  "review_notes": null,
  "error": null
}
```

**Response (completed):**
```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "completed",
  "current_step": "completed",
  "x_thread": [
    "Spent 3 months building a real-time collab board. Biggest lesson: Redis pub/sub destroys HTTP polling for latency.",
    "Benchmarked 100 simultaneous updates:\n- HTTP polling: 2.3s avg latency\n- Redis pub/sub: 80ms avg latency\n\nThat's 28x faster.",
    "The hard part wasn't the speed. It was Celery worker crashes after restarts. Lost queued tasks 3 times before we added state tracking.",
    "What we learned: 1) Pub/sub > polling 2) Schedule tasks with beat, not cron 3) Log worker state on restart"
  ],
  "linkedin_post": null,
  "devto_article": null,
  "review_notes": "✓ All claims verified against source README",
  "error": null
}
```

### 3. Generate LinkedIn Post

```bash
curl -X POST http://localhost:8000/generate-linkedin-post \
  -H 'Content-Type: application/json' \
  -d '{
    "readme": "...",
    "learnings": ["..."],
    "hard_parts": ["..."],
    "tone": "honest and practical",
    "audience": "intermediate developers"
  }'
```

Response: `{ "job_id": "...", "status": "queued" }`

Then poll: `GET /result/{job_id}` → returns `linkedin_post` when done.

### 4. Generate dev.to Article

```bash
curl -X POST http://localhost:8000/generate-article \
  -H 'Content-Type: application/json' \
  -d '{...same request...}'
```

Response: `{ "job_id": "...", "status": "queued" }`

Then poll: `GET /result/{job_id}` → returns `devto_article` when done.

### 5. Health Check

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "ok",
  "redis": true
}
```

---

## Request Body Schema

All three endpoints accept the same request:

```json
{
  "readme": "string (required)",
  "learnings": ["string", "string"],
  "hard_parts": ["string", "string"],
  "tone": "string (default: 'honest and practical')",
  "audience": "string (default: 'intermediate developers')"
}
```

### Field Details

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `readme` | string | ✓ | Raw README markdown. Include code, architecture, decisions. |
| `learnings` | array | | Key insights, discoveries, patterns you found. |
| `hard_parts` | array | | Challenges, gotchas, things that were difficult. |
| `tone` | string | | Style: "honest and practical", "technical", "casual", etc. |
| `audience` | string | | Who this is for: "junior devs", "CTOs", "DevOps", etc. |

---

## Job Lifecycle (How it works)

```
┌─────────────────────────────────────────────────────────────────┐
│ Client calls POST /generate-x-post                              │
│ ↓                                                               │
│ FastAPI creates job, stores in Redis, enqueues to Celery       │
│ Returns immediately: { "job_id": "abc123", "status": "queued" } │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Client polls GET /result/abc123                                  │
│ ↓                                                               │
│ Redis shows: status = "running", current_step = "extracting"   │
│ ↓                                                               │
│ Celery Worker picks up task from Redis queue                   │
│ ├─ Run extractor subagent                                      │
│ │  status = "extracting" → save extracted_insights.md          │
│ ├─ Run x-writer subagent                                       │
│ │  status = "writing" → save x_draft.md                        │
│ ├─ Run content-reviewer subagent                               │
│ │  status = "reviewing" → correct draft, save review_notes.md  │
│ └─ Store result in Redis                                       │
│    status = "completed" → result = {...x_thread, ...}          │
│ ↓                                                               │
│ Client polls again → gets complete result                       │
└─────────────────────────────────────────────────────────────────┘
```

### Job Statuses

| Status | Meaning |
| --- | --- |
| `queued` | Waiting in Redis queue for a worker to pick up |
| `running` | Worker is processing |
| `extracting` | Extracting insights from README |
| `writing` | Generating drafts (x/linkedin/devto) |
| `reviewing` | Verifying claims and correcting drafts |
| `completed` | Done. Result is ready. |
| `failed` | Error occurred. Check `error` field. |

### What's Stored in Redis

```
Redis Hash: jobs:{job_id}
├─ status        (string)      Current state
├─ current_step  (string)      Which subagent is active
├─ input         (JSON)        Original request
├─ result        (JSON)        Finished content
├─ error         (string)      If failed
└─ TTL: 2 hours (auto-expire)
```

---

## Rate Limiting

**Rules:**
- Generation endpoints: **10 requests/minute per IP**
- Health/root: **30 requests/minute per IP**
- Header: `X-RateLimit-Remaining` shows requests left

**Example (limit exceeded):**
```bash
curl -X POST http://localhost:8000/generate-x-post -d '{...}'

# After 10 requests:
HTTP/1.1 429 Too Many Requests
{"detail": "Rate limit exceeded: 10 requests per minute per IP"}
```

To increase limits, edit `main.py` and `app/routes/content.py`:
```python
@limiter.limit("20/minute")  # Change this
def generate_x_post(req: ContentRequest, request: Request):
```

---

## Common Workflows

### Example 1: Generate X thread from a project

```bash
# 1. Start the request
JOB_ID=$(curl -s -X POST http://localhost:8000/generate-x-post \
  -H 'Content-Type: application/json' \
  -d '{
    "readme": "# MyProject\n...",
    "learnings": ["insight 1"],
    "hard_parts": ["challenge 1"]
  }' | jq -r .job_id)

echo "Job: $JOB_ID"

# 2. Poll until done
for i in {1..60}; do
  RESULT=$(curl -s http://localhost:8000/result/$JOB_ID)
  STATUS=$(echo $RESULT | jq -r .status)
  echo "[$i] Status: $STATUS"
  
  if [ "$STATUS" = "completed" ]; then
    echo $RESULT | jq '.x_thread'
    break
  fi
  
  sleep 2
done
```

### Example 2: Check all three platforms

```bash
# Start jobs for all three
X_JOB=$(curl -s -X POST http://localhost:8000/generate-x-post -d '...' | jq -r .job_id)
LI_JOB=$(curl -s -X POST http://localhost:8000/generate-linkedin-post -d '...' | jq -r .job_id)
ARTICLE_JOB=$(curl -s -X POST http://localhost:8000/generate-article -d '...' | jq -r .job_id)

# Poll all three
for job in $X_JOB $LI_JOB $ARTICLE_JOB; do
  while true; do
    curl -s http://localhost:8000/result/$job | jq '{job_id, status}'
    # Check if completed and break
  done
done
```

---

## Model Selection

Edit `.env` to pick your reasoning engine:

### Ollama (default, local)
```env
MODEL_PROVIDER=ollama
OLLAMA_MODEL=gemma4:31b-cloud
OLLAMA_BASE_URL=http://localhost:11434
```

### Anthropic (Claude)
```env
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

### Groq (fast, free API)
```env
MODEL_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...
```

### OpenAI (GPT)
```env
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4-turbo
OPENAI_API_KEY=sk-...
```

---

## Troubleshooting

### "Redis connection refused"
```bash
redis-server  # Start Redis first
```

### "Worker not picking up tasks"
Check Celery worker terminal:
```bash
uv run celery -A app.worker.celery_app worker --loglevel=info
```

Should show:
```
celery@hostname ready to accept tasks
```

### "Task timeout (takes >30min)"
The agent runs for 30-90s typically. If stuck, check:
- Model is responding: `curl http://localhost:11434/api/tags` (for Ollama)
- Redis has space: `redis-cli info`
- Worker has resources: `celery inspect stats`

### "Rate limit errors"
Expected after 10 requests/minute. Wait 60 seconds or change limits in `main.py`.

---

## Deployment

### Railway

1. Push to GitHub
2. Create Railway project
3. Add Redis plugin
4. Deploy two services:
   - **API**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Worker**: `celery -A app.worker.celery_app worker --loglevel=info`
5. Set env vars: `REDIS_URL`, `MODEL_PROVIDER`, API keys

### Docker (local)
```bash
docker compose up --build
```

### Render / Fly.io / Others
Similar to Railway — need Redis addon + 2 services (API + Worker).

---

## Project Structure

```
deepagents-tutorial/
├── main.py                      FastAPI app with rate limiting
├── app/
│   ├── agent/
│   │   ├── orchestrator.py      DeepAgents orchestrator (backends + subagents)
│   │   ├── model.py             Model factory (Ollama/Groq/OpenAI/Anthropic)
│   │   └── tools.py             Tools (fact_check)
│   ├── routes/
│   │   ├── content.py           POST /generate-{x|linkedin|article}
│   │   ├── result.py            GET /result/{job_id}
│   │   └── health.py            GET /health
│   ├── worker/
│   │   ├── celery_app.py        Celery app (Redis broker)
│   │   └── tasks.py             @celery_app.task generate_content_task
│   ├── skills/                  SKILL.md files (progressive disclosure)
│   │   ├── extractor/SKILL.md
│   │   ├── x-writer/SKILL.md
│   │   ├── linkedin-writer/SKILL.md
│   │   ├── devto-writer/SKILL.md
│   │   └── content-reviewer/SKILL.md
│   ├── context/AGENTS.md        Durable orchestrator memory
│   ├── models.py                Pydantic schemas (ContentRequest, JobResponse)
│   ├── config.py                Settings from .env
│   └── redis_store.py           Redis job store (HSET/HGET)
├── scripts/
│   └── run_once.py              One-off test (no queue)
├── docker-compose.yml           API + Worker + Redis
├── Dockerfile
├── .env.example
├── requirements.txt
├── pyproject.toml
└── DEVVOICE.md                  Architecture deep-dive
```

---

## What the Four DeepAgents Concepts Do Here

| Concept | Use |
| --- | --- |
| **Backends** | `StateBackend` isolates each job's files (extracted_insights.md, drafts, etc). Files live in memory, not disk. |
| **Context Engineering** | AGENTS.md loaded as `memory` once, brief.md seeded per-job, built-in summarization, subagent isolation keeps thread lean. |
| **Skills** | Each subagent loads only its SKILL.md (extractor, writers, reviewer). Progressive disclosure — read full instructions only when needed. |
| **Subagents** | Extractor, x-writer, linkedin-writer, devto-writer, content-reviewer. Each runs in isolated context so main thread doesn't balloon. |

---

## Quick Links

- **FastAPI Docs**: http://localhost:8000/docs
- **Celery Status**: `celery -A app.worker.celery_app inspect stats`
- **Redis CLI**: `redis-cli KEYS 'jobs:*'` (list all job IDs)
- **Architecture**: See `DEVVOICE.md`

---

Built with DeepAgents, FastAPI, Celery, Redis. Licensed MIT.
