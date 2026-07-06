.PHONY: up down fresh logs restart

# Start all services (uses cache)
up:
	docker compose up --build

# Fresh rebuild — no cache, then start
fresh:
	docker compose down
	docker compose build --no-cache
	docker compose up

# Stop and remove containers
down:
	docker compose down

# Tail logs for all services
logs:
	docker compose logs -f

# Restart a specific service: make restart s=worker
restart:
	docker compose restart $(s)


🤖 Agentic Side
Orchestrator only coordinates, never writes content
Extractor pulls grounded claims from README into an insights file
3 writers (X, LinkedIn, article) draft only from insights, so they can't hallucinate
Reviewer verifies drafts and fact-checks via web search
Each subagent runs in an isolated context
Progressive disclosure: agents load only their own skill file
Shared per-job virtual filesystem instead of chat history
Human-in-the-loop: approve or request revision
Revisions spawn child jobs with previous output as context
⚙️ Backend
FastAPI validates, truncates, enqueues, and returns job_id instantly
Token caps and rate limiting on ingestion
Celery workers run the agent pipeline via Redis queue
REST APIs for jobs, projects, approvals, revisions
Redis holds queue, live status, results (TTL), LLM cache
PostgreSQL holds users, projects, jobs, revision chains
Full user history and versioning
Progress streamed to Redis, polled every 2s
Langfuse traces every stage by job_id
Swappable LLMs: Ollama / Groq / OpenAI / Anthropic
🖥️ Frontend
React SPA to submit, track live, approve or revise
nginx serves the SPA and proxies /api as the single entry point
🐳 Ops
5 Docker Compose services: frontend, API, worker, Postgres, Redis
One docker compose up and everything is wired