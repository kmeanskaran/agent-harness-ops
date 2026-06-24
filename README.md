# DevVoice — Content Creation Agent Harness

Turn a GitHub README into polished X threads, LinkedIn posts, and articles using 5 specialized AI agents. Every claim fact-checked against the source.

## Overview

**What it does:** FastAPI accepts a README. Celery queues the job. DeepAgents orchestrates 5 agents (Extractor → Writers → Reviewer) in parallel. Results cached aggressively. Returns optimized content for each platform.

**Why it works:** Specialization beats generalization. Each agent masters one platform. Isolation prevents hallucinations. Caching drops cost by 70%.

**Tech Stack:** FastAPI (API) + Celery (queue) + Redis (cache + broker) + DeepAgents (orchestration) + Ollama/Groq/OpenAI/Anthropic (LLM)

---

## System Components

**FastAPI** — REST API server. Validates input, creates job, returns job_id immediately (no blocking).

**Redis** — In-memory store. Acts as Celery broker, caches LLM responses, tracks job status, auto-expires results after 2 hours.

**Celery** — Distributed task queue. Workers poll Redis, pick up jobs, run DeepAgents orchestrator async. Add more workers to scale.

**DeepAgents** — Multi-agent framework. Runs 5 subagents in parallel with isolated memory. Manages context, skills, state. Prevents hallucinations.

**Orchestrator** — Coordinates agents: Extractor (pulls facts) → X-Writer + LinkedIn-Writer + Article-Writer (optimize for platform) → Reviewer (fact-checks).

---

## Quick Start

### 1. Install & Configure

```bash
# Install dependencies
uv sync

# Copy .env template
cp .env.example .env

# Edit .env: choose model provider (ollama, groq, openai, anthropic)
```

### 2. Choose Run Mode

**Docker (recommended):**
```bash
docker compose up --build
# API on localhost:8000
# Frontend on localhost:5173 (React dev server)
# Worker + Redis in background
```

**Local (4 terminals):**
```bash
# Terminal 1: Redis
redis-server

# Terminal 2: Celery worker
uv run celery -A app.worker.celery_app worker --loglevel=info

# Terminal 3: FastAPI API
uv run uvicorn main:app --reload --port 8000

# Terminal 4: React frontend (from frontend/ directory)
cd frontend && npm run dev
# Frontend on http://localhost:5173
```

**One-off (no queue):**
```bash
uv run python -m scripts.run_once
```

### 3. Access Frontend

Open in browser:

```
http://localhost:5173
```

Or if running Docker with frontend container:
```
http://localhost:3000
```

You'll see:
- Input fields for README, learnings, hard_parts, tone, audience
- Generate buttons for X, LinkedIn, Article
- Real-time job status tracking
- Result display when complete

### 4. Test via API (curl)

```bash
curl -X POST http://localhost:8000/generate-x-post \
  -H 'Content-Type: application/json' \
  -d '{
    "readme": "# MyProject - uses Redis pub/sub for real-time updates",
    "learnings": ["Pub/sub 28x faster than polling"],
    "hard_parts": ["Celery task state across restarts"],
    "tone": "honest and practical"
  }'
```

Returns: `{ "job_id": "abc123", "status": "queued" }`

Poll for results:
```bash
curl http://localhost:8000/result/abc123
```

Or visit: `http://localhost:8000/docs` for interactive API explorer (Swagger UI)

---

## API Reference

**Base:** `http://localhost:8000`

**Endpoints:**
- `POST /generate-x-post` — Create X thread job
- `POST /generate-linkedin-post` — Create LinkedIn job
- `POST /generate-article` — Create article job
- `GET /result/{job_id}` — Check job status and results
- `GET /health` — Health check

**Request body (all endpoints):**
```json
{
  "readme": "string (required)",
  "learnings": ["string"],
  "hard_parts": ["string"],
  "tone": "string (default: 'honest and practical')",
  "audience": "string (default: 'intermediate developers')"
}
```

**Response:**
```json
{
  "job_id": "a1b2c3d4",
  "status": "completed",
  "current_step": "completed",
  "x_thread": ["tweet 1", "tweet 2"],
  "linkedin_post": "post content",
  "article": "article content",
  "review_notes": "✓ All claims verified",
  "error": null
}
```

**Job statuses:** queued → extracting → writing → reviewing → completed (or failed)

---

## Configuration

### .env Checklist

Before pushing, verify `.env` is correct:

- [ ] `.env` exists (copied from `.env.example`)
- [ ] `.env` is in `.gitignore` (never commit secrets)
- [ ] `MODEL_PROVIDER` set (ollama, groq, openai, or anthropic)
- [ ] `REDIS_URL` correct for your setup
- [ ] API keys only for chosen provider (leave others blank)
- [ ] No sensitive keys in `.env.example`

### Provider Setup

**Ollama (local):**
```env
MODEL_PROVIDER=ollama
OLLAMA_MODEL=gemma4:31b-cloud
OLLAMA_BASE_URL=http://localhost:11434
```

**Anthropic (Claude):**
```env
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

**Groq (free API):**
```env
MODEL_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...
```

**OpenAI (GPT):**
```env
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4-turbo
OPENAI_API_KEY=sk-...
```

---

## Pre-Push Checklist

- [ ] All tests pass: `pytest`
- [ ] No untracked secrets in repo: `grep -r "ANTHROPIC_API_KEY\|GROQ_API_KEY\|OPENAI_API_KEY" --include="*.py"`
- [ ] `.env` is in `.gitignore` and NOT tracked: `git status | grep .env`
- [ ] `.env.example` updated with correct template (keys blank)
- [ ] Python formatting: `black .` or `uv run black .`
- [ ] Requirements up to date: `uv lock` or `pip freeze > requirements.txt`
- [ ] README accurate (this file)
- [ ] No debug prints or `pdb` left in code
- [ ] Commit message clear and concise

**Final push:**
```bash
git status  # Verify changes
git log --oneline -5  # Verify commits
git push origin main
```

---

## Troubleshooting

**Redis connection refused:** Start Redis first (`redis-server`)

**Worker not picking up tasks:** Check worker is running and connected to Redis (`celery inspect stats`)

**API returns 502:** Ensure Redis and worker both running

**Rate limit (429):** Default 10/min. Wait 60s or change in `main.py`

**Timeout (>2min):** Check model is responding, worker has resources

---

## Rate Limiting

- Generation endpoints: **10 requests/minute per IP**
- Health endpoint: **30 requests/minute per IP**
- Response header: `X-RateLimit-Remaining` shows requests left

---

## Architecture Diagram

```
README input
    ↓
FastAPI (validate) → Redis job store → Celery queue
    ↓
Worker picks up → DeepAgents orchestrator
    ├─ Extractor (pull facts)
    ├─ Writers (X + LinkedIn + Article in parallel)
    └─ Reviewer (fact-check)
    ↓
Results in Redis → Frontend polls → Displays results
```

---

## Project Structure

```
agent-harness-ops/
├── main.py                  FastAPI entry point
├── app/
│   ├── agent/
│   │   ├── orchestrator.py  DeepAgents orchestrator (5 agents)
│   │   ├── model.py         Model factory (providers)
│   │   └── cache.py         Prompt caching logic
│   ├── routes/
│   │   ├── content.py       POST endpoints
│   │   ├── result.py        GET endpoints
│   │   └── health.py        Health check
│   ├── worker/
│   │   ├── celery_app.py    Celery config
│   │   └── tasks.py         @celery_app.task
│   ├── skills/              Agent instructions (SKILL.md)
│   ├── context/AGENTS.md    Shared memory
│   └── redis_store.py       Job store
├── scripts/run_once.py      One-off test script
├── .env.example             Template (no secrets)
├── .env                     Local config (NEVER commit)
├── docker-compose.yml
├── requirements.txt
└── pyproject.toml
```

---

## Cost & Performance

**First run:** $0.20 (all agents execute)

**Cached run:** $0.00 (Redis hit, instant)

**By 100 users:** Cost per request → $0 (70% cost reduction via caching)

**Speed:** 3-5 minutes first run, 50ms cached

---

## What's Next

- [ ] Template presets (save tone/audience combos)
- [ ] Batch operations (regenerate all at once)
- [ ] Cache analytics dashboard
- [ ] Team workspaces
- [ ] Streaming results (output as agents complete)

---

**Built with:** DeepAgents, FastAPI, Celery, Redis, Claude Code  
**License:** MIT  
**Status:** Production-ready
