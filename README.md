# DevVoice — Content Creation Agent Harness

Turn a GitHub README into a reviewed X thread, LinkedIn post, and dev.to article. Five specialized agents (extract → write → review) keep every claim grounded in the source — nothing hallucinated, and a human approves before anything is final.

Built as a reference implementation of the **Agent Harness** pattern: state backend + layered context + skills + subagents on the inside; async queue, dual storage, cost control, and tracing on the outside. Full write-up in [docs/doc.md](docs/doc.md), diagrams in [docs/full_diagram.md](docs/full_diagram.md).

## What's Inside

| Layer | Tech | Role |
| --- | --- | --- |
| API | FastAPI + slowapi | Validates input, caps README size, rate-limits, enqueues jobs |
| Queue | Celery + Redis | Async job execution; workers scale horizontally |
| Agents | DeepAgents + LangChain | Orchestrator delegating to extractor, 3 platform writers, reviewer |
| LLM | Ollama / Groq / OpenAI / Anthropic | Swappable via `MODEL_PROVIDER`; Anthropic gets prompt caching |
| Storage | PostgreSQL + Redis | Postgres: users, projects, jobs, revision chains. Redis: live status, results (TTL), LLM response cache |
| Observability | Langfuse | Traces every stage, keyed by job_id |
| Frontend | React + Vite + TS, nginx | Tab-based workspace: generate, track progress, approve, revise, browse history |

### How a job flows

```text
Browser → nginx → FastAPI ──enqueue──→ Redis ──→ Celery worker
                     │                              │
                     └─ returns job_id instantly    └─ DeepAgents pipeline:
                                                       extractor → writers → reviewer
Frontend polls /result/{job_id} ←── status in Redis ←──┘
Job lands in awaiting_approval → human approves, or revises (spawns child job)
```

## Getting Started

### Prerequisites

- Docker Desktop (easiest path), **or** for local dev: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 20+, Redis, PostgreSQL
- An LLM: [Ollama](https://ollama.com) running locally (default, free), or an API key for Groq / OpenAI / Anthropic

### 1. Clone & configure

```bash
git clone <repo-url>
cd agent-harness-ops
cp .env.example .env
# Edit .env — pick a provider and fill ONLY its key (see Configuration below)
```

### 2. Run with Docker (recommended)

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API + Swagger UI | <http://localhost:8000/docs> |
| PostgreSQL | localhost:5432 (`devvoice`/`devvoice`) |
| Redis | localhost:6379 |

> **Ollama users:** inside containers, `localhost` is the container. Set
> `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`.

### 3. Or run locally (development)

```bash
uv sync                      # install Python deps into .venv
cd frontend && npm install   # install frontend deps
```

Then four terminals:

```bash
# 1 — infra (or run redis/postgres natively)
docker compose up postgres redis

# 2 — Celery worker
uv run celery -A app.worker.celery_app worker --loglevel=info

# 3 — API (hot reload)
uv run uvicorn main:app --reload --port 8000

# 4 — frontend dev server (hot reload)
cd frontend && npm run dev   # http://localhost:5173
```

### 4. Smoke test

```bash
curl -X POST http://localhost:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "you@example.com",
    "readme": "# MyProject — uses Redis pub/sub for real-time updates",
    "learnings": ["Pub/sub was 28x faster than polling"],
    "hard_parts": ["Celery task state across restarts"],
    "tone": "honest and practical",
    "platforms": ["x"]
  }'
# → { "job_id": "abc123...", "status": "queued", ... }

curl http://localhost:8000/result/<job_id>   # poll until awaiting_approval
```

## API Reference

Interactive docs at `http://localhost:8000/docs`.

| Endpoint | Purpose |
| --- | --- |
| `POST /generate` | Enqueue generation for one or more platforms (`x`, `linkedin`, `devto`) |
| `POST /generate-x-post` / `-linkedin-post` / `-article` | Single-platform shortcuts |
| `GET /result/{job_id}` | Poll status, current step, and results |
| `POST /revise/{job_id}` | Create a revision (child job) with an instruction |
| `POST /approve/{job_id}` | Approve an `awaiting_approval` job |
| `GET /history/{email}` | All jobs for a user, grouped by project |
| `DELETE /history/{email}/{job_id}` | Delete a job |
| `DELETE /projects/{email}/{project_id}` | Delete a project and its jobs |
| `GET /health` | Service health |

Job statuses: `queued → running → extracting → writing → reviewing → awaiting_approval → completed` (or `failed`).

Rate limits: 10/min on generation endpoints, 20/min on approve/delete (per user/IP).

## Configuration

All config lives in `.env` (see `.env.example` for the full template). Key settings:

```bash
# --- Model provider (pick one, fill only its key) ---
MODEL_PROVIDER=ollama          # ollama | groq | openai | anthropic
OLLAMA_BASE_URL=http://localhost:11434   # host.docker.internal in Docker
OLLAMA_MODEL=<model-id>
# GROQ_API_KEY= / OPENAI_API_KEY= / ANTHROPIC_API_KEY=

# --- Infra (docker compose overrides these automatically) ---
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql://devvoice:devvoice@localhost:5432/devvoice
JOB_TTL_SECONDS=7200

# --- Observability (optional but recommended) ---
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com

# --- Reviewer's fact-check tool ---
TAVILY_API_KEY=
```

## Contributing / Development Workflow

1. **Branch** off `master`: `git checkout -b feat/<short-name>`
2. **Develop** with the local setup above — API and frontend both hot-reload; only the Celery worker needs a restart after code changes.
3. **Keep the lockfile in sync** when you touch dependencies: edit `pyproject.toml`, then run `uv lock` and commit both.
4. **Before pushing**, run through the checklist below.
5. **Open a PR** against `master` with a clear description of what changed and why.

Project layout:

```text
agent-harness-ops/
├── main.py                      FastAPI entry point
├── app/
│   ├── agent/
│   │   ├── orchestrator.py      Agent harness core (orchestrator + 5 subagents)
│   │   ├── model.py             Provider factory (+ Anthropic prompt caching)
│   │   ├── cache.py             RedisLLMCache (response cache, all providers)
│   │   ├── token_utils.py       README validation / truncation / estimation
│   │   └── tools.py             fact_check (Tavily) for the reviewer
│   ├── skills/*/SKILL.md        Per-agent instructions (progressive disclosure)
│   ├── context/AGENTS.md        Durable shared guidance (agent memory)
│   ├── routes/                  content.py · result.py · health.py
│   ├── worker/                  celery_app.py · tasks.py
│   ├── db.py                    PostgreSQL layer
│   └── redis_store.py           Live job state
├── frontend/                    React SPA + nginx (Dockerfile inside)
├── docs/                        Architecture deep-dive + Mermaid diagrams
├── docker-compose.yml           postgres · redis · app · worker · frontend
└── .env.example                 Config template — never commit the real .env
```

### Pre-push checklist

- [ ] `.env` is **not** staged: `git status --short | grep -c "^A.*\.env$"` should be 0 (it's gitignored — keep it that way)
- [ ] No real keys in tracked files: `git diff --cached | grep -nEi "sk-lf-[a-f0-9]|sk-ant-api|gsk_[A-Za-z0-9]{20}|tvly-[A-Za-z0-9]"` returns nothing (placeholders like `sk-ant-...` in docs are fine)
- [ ] `.env.example` has **blank** values for every secret
- [ ] Lockfile matches `pyproject.toml`: `uv lock --check`
- [ ] App boots: `docker compose up --build` and `GET /health` returns OK

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError` running locally | `uv sync` — the venv is out of date with `pyproject.toml` |
| Worker never picks up jobs | Is Redis up? Is the worker running? `uv run celery -A app.worker.celery_app inspect ping` |
| Agent calls hang with Ollama in Docker | `OLLAMA_BASE_URL` must be `http://host.docker.internal:11434`, not localhost |
| `429 Too Many Requests` | Rate limit (10/min). Wait 60s. |
| Job stuck in `running` | Check worker logs; check the Langfuse trace for the job_id |

## License

MIT
