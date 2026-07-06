# DevVoice: Building an Agent Harness

## What This Document Covers

**DevVoice** turns a developer's README into reviewed, platform-native content for X (Twitter), LinkedIn, and dev.to. But the more interesting story is *how* it's built: DevVoice is a working implementation of the **Agent Harness** pattern — the scaffolding that surrounds an LLM agent so it behaves reliably in production.

This document explains, in order:

1. What an agent harness is and why DevVoice needed one
2. How we built the harness — the four pillars, with the actual code decisions behind each
3. How the full production architecture grew around the harness — API, queue, storage, caching, observability, frontend
4. The design rationale and trade-offs

---

## Part 1 — The Agent Harness

### The problem a harness solves

A raw LLM call can draft a tweet. It cannot, by itself, run a five-stage pipeline where every claim is grounded in a source document, each stage has different instructions, failures are recoverable, progress is visible to a user, and cost stays bounded. The gap between "an LLM call" and "a dependable system" is filled by the **harness**: the state management, context engineering, tool wiring, and orchestration around the model.

DevVoice's core quality requirement drove the design: **grounded generation**. Content must come from the README and the user's stated learnings — never hallucinated. That forces a pipeline shape (extract facts → write drafts → review against facts) which in turn forces multi-agent coordination, which is exactly what a harness provides.

### The four pillars

The harness is built on DeepAgents (`create_deep_agent`) and lives in `app/agent/orchestrator.py`. Four decisions define it:

#### 1. State backend — a virtual filesystem per job

Every job gets an isolated, in-memory file workspace (`StateBackend`). Agents don't pass data through conversation history; they **read and write files**:

```
/workspace/{job_id}/
    brief.md                 ← seeded input: README, tone, audience, platforms
    revision_request.md      ← (revisions only) the user's instruction
    previous_output.md       ← (revisions only) prior drafts for context
    extracted_insights.md    ← written by extractor
    x_draft.md               ← written by x-writer
    linkedin_draft.md        ← written by linkedin-writer
    devto_draft.md           ← written by devto-writer
    review_notes.md          ← written by content-reviewer
/skills/<name>/SKILL.md      ← seeded role instructions
/context/AGENTS.md           ← seeded durable project guidance
```

Why files instead of chat history:

- **Isolation** — no state leaks between jobs; the workspace dies with the run.
- **Inspectability** — every intermediate artifact is a named file. Progress tracking falls out for free: the worker infers the current stage from *which files exist* in the streamed state (`extracted_insights.md` present → "extracting" done; `*_draft.md` → "writing"; `review_notes.md` → "reviewing").
- **Lean contexts** — a subagent reads only the files it needs, instead of inheriting the whole conversation.

`_seed_files()` copies skills and shared context from disk into this virtual filesystem at the start of every run, then adds the per-job brief.

#### 2. Context engineering — three deliberate layers

Instead of one giant prompt, context is split by *lifetime*:

| Layer | File | Lifetime | Purpose |
| --- | --- | --- | --- |
| Durable memory | `app/context/AGENTS.md` | Constant across all jobs | What DevVoice is, quality principles, tone guidance. Loaded via `memory=[...]` — and because it never changes, it's highly cacheable. |
| Per-job input | `brief.md` | One job | README, learnings, hard parts, tone, audience, platforms. The *only* task-specific context. |
| Role instructions | `skills/*/SKILL.md` | Per subagent | How to extract / write for X / write for LinkedIn / write for dev.to / review. |

On top of this, DeepAgents' built-in `SummarizationMiddleware` compacts the orchestrator thread if it grows large (tuned via `SUMMARIZE_TRIGGER_TOKENS` / `SUMMARIZE_KEEP_MESSAGES`). The separation is what keeps prompts maintainable: changing LinkedIn conventions touches one skill file, nothing else.

#### 3. Skills — progressive disclosure

Each subagent declares `skills=["/skills"]` and loads **only its own** `SKILL.md` (200–400 tokens each):

- `extractor/SKILL.md` — how to pull claims grounded in the README
- `x-writer/SKILL.md` — thread conventions, 6–10 tweets
- `linkedin-writer/SKILL.md` — 150–300 words, professional register
- `devto-writer/SKILL.md` — 1000–1500 word article structure
- `content-reviewer/SKILL.md` — fact-check drafts against `extracted_insights.md`

This is progressive disclosure: instructions enter a context only when the role that needs them is active. The x-writer never pays tokens for dev.to formatting rules.

#### 4. Subagents — an orchestrator that never writes content

The orchestrator's system prompt is explicit: *"Your job is coordination and verification, NOT writing the content yourself."* It delegates:

```
Orchestrator (coordination only)
  ├─ 1. extractor          brief.md → extracted_insights.md
  ├─ 2. per platform:      insights → x_draft.md / linkedin_draft.md / devto_draft.md
  └─ 3. content-reviewer   verifies & corrects every draft in place → review_notes.md
                           (has the fact_check tool — Tavily search — but may
                            never add new claims)
```

Each subagent runs in an **isolated context** with the shared grounding rule: *"Stay strictly grounded in extracted_insights.md — never invent facts."* The reviewer is the only agent with a tool (`fact_check`), and its skill restricts it to verification, not addition.

Why this split matters:

- The orchestrator thread stays small — heavy token work happens in child contexts that are discarded after each delegation.
- Each role is independently testable and replaceable.
- The extract → write → review sequence *structurally* enforces grounding: writers can only see the insights file, not raw freedom to invent.

The compiled orchestrator graph is built once (`@lru_cache` on `build_orchestrator()`) and reused across jobs — only the seeded files differ per run.

### Model abstraction

`app/agent/model.py` makes the harness provider-agnostic via `MODEL_PROVIDER`:

- **ollama** (default) — local models, zero API cost, ideal for development
- **groq** / **openai** — hosted alternatives
- **anthropic** — with a custom `_CachingChatAnthropic` subclass that marks system messages with `cache_control: ephemeral`, so the stable context layers (AGENTS.md, skills, orchestrator prompt) hit Anthropic's prompt cache (~90% input-token discount, 5-minute TTL)

The layered-context design and prompt caching reinforce each other: because durable context is separated from per-job context, the cacheable prefix is large and stable.

---

## Part 2 — The Architecture Around the Harness

The harness answers "how do agents cooperate reliably." The rest of the architecture answers "how does this run as a real service" — and each component was added in response to a concrete constraint.

### The shape, end to end

```
Browser (React SPA, localhost:3000)
    ↓ HTTP (nginx reverse-proxies /api → app:8000)
FastAPI  — validate, rate-limit, estimate tokens, enqueue     [synchronous, fast]
    ↓ Celery task via Redis broker
Celery worker — build brief.md, run the harness               [asynchronous, slow]
    ↓
DeepAgents orchestrator → subagents → LLM provider
    ↓
Result → Redis (live state) + PostgreSQL (durable record)
    ↓ status: awaiting_approval
Human approves or requests a revision (loops back to enqueue)
```

Observability (Langfuse) traces every stage; two caching layers cut token cost.

### Why asynchronous: API and worker are separate processes

An agent pipeline takes minutes; an HTTP request should take milliseconds. So the API (`main.py`, `app/routes/`) does only cheap work — validation, token estimation, record creation, `generate_content_task.delay()` — and returns `{job_id, status: queued}` immediately. The Celery worker (`app/worker/tasks.py`) does everything expensive. The frontend polls `GET /result/{job_id}`.

Workers are stateless and scale horizontally: run more worker containers, jobs distribute automatically through the Redis broker.

### Two stores, two jobs

- **Redis** (`app/redis_store.py`) — *live* state: the Celery queue, job status/current-step (updated as workspace files appear), results with a TTL (`JOB_TTL_SECONDS`, default 2h), and the LLM response cache.
- **PostgreSQL** (`app/db.py`) — *durable* record: users, projects, jobs, revisions.

```sql
users     (email PK, created_at, updated_at)
projects  (id, user_email FK, readme, readme_hash, ...)
jobs      (job_id PK, user_email FK, thread_id, parent_job_id FK, project_id FK,
           status, current_step, request_json JSONB, result_json JSONB, error, ...)
revisions (id, parent_job_id FK, child_job_id FK, instruction, ...)
```

Two design details carry the product features:

- **`project_id = SHA-256(normalized_readme)[:24]`** — the same README always maps to the same project, so history groups naturally and duplicate work is detectable.
- **Jobs store both `request_json` and `result_json`** — a revision chain (`parent_job_id` links) is fully reconstructable: you can always see what was asked and what came back, at every step.

### Human in the loop: approval and revision

Finished jobs land in `awaiting_approval`, not `completed`. The human either:

- **Approves** (`POST /approve/{job_id}`) — finalizes the job, or
- **Revises** (`POST /revise/{job_id}` with an instruction) — creates a *child job* carrying `parent_job_id`. The harness seeds `revision_request.md` and `previous_output.md` into the new workspace, so subagents revise with full context instead of starting blind.

This is a deliberate harness feature: agent output is a draft until a person says otherwise, and every revision is a first-class, auditable job.

### Token cost control — three layers

Cost was engineered at three levels (`app/agent/token_utils.py`, `app/agent/cache.py`, `app/agent/model.py`):

1. **At the API boundary** — READMEs are validated (100KB / ~12K-token cap) and truncated to a 10K-token budget *before* queuing; total job tokens are estimated up front and attached to the trace. Oversized input never reaches the LLM.
2. **Response cache** — `RedisLLMCache`, registered globally via `set_llm_cache()`, keys on `SHA-256(model_config + prompt)` with a 24h TTL (`LLM_CACHE_TTL_SECONDS`). Works for every provider; a hit costs zero tokens. Resubmitting the same README makes the extractor call free.
3. **Prompt cache (Anthropic)** — the stable context prefix (AGENTS.md, skills, system prompts) is cache-marked, giving ~90% off input tokens on repeat calls within 5 minutes.

### Observability — Langfuse

Every stage is traced with `@observe` decorators, using **`session_id = job_id`** so one job's API enqueue, worker execution, and pipeline run stitch into a single session:

- `enqueue_generation_job` (API) — user, platforms, token estimate, whether the README was truncated
- `generate_content_task` (worker) — timing, token breakdown, success/failure
- `devvoice_pipeline` (harness) — platforms generated, duration

Traces go to Langfuse Cloud (`LANGFUSE_*` env vars). This is what makes the harness *debuggable*: when a job produces weak output, the trace shows which subagent ran, with what context, at what cost.

### Guardrails

- **Rate limiting** — 10–20 req/min per user/IP via `slowapi`
- **Prompt-injection boundary** — the README is seeded as a *workspace file*, never inlined into system prompts; instructions and user content stay structurally separate. Subagent prompts add "never invent facts, stay grounded in extracted_insights.md."
- **Input caps** — README size validation + truncation (above)
- **Data lifecycle** — Redis job state expires (2h default); PostgreSQL history persists until the user deletes a job or project

### Frontend

A React + Vite + TypeScript SPA (`frontend/`) served by nginx, which also reverse-proxies `/api` to the backend (single origin, no CORS). The workspace is tab-based:

- **Input** — README paste/upload, learnings, hard parts, tone, audience, platform checkboxes
- **Progress** — 2-second polling maps the harness's file-derived stages (extracting → writing → reviewing) to a live progress display
- **Results** — one tab per platform; tweet cards with character counts, copy buttons, version labels (v2/3) when multiple runs exist
- **History sidebar** — projects grouped by README hash, expandable runs, per-run Load / Load & Revise / Delete
- **Approval & revision** — approve button on `awaiting_approval`; revision box that creates child jobs

### Deployment — Docker Compose

Five services (`docker-compose.yml`), all health-checked and dependency-ordered:

| Service | Image / build | Port | Role |
| --- | --- | --- | --- |
| `frontend` | `frontend/Dockerfile` (nginx) | 3000→80 | SPA + reverse proxy |
| `app` | `Dockerfile` (uvicorn) | 8000 | FastAPI API |
| `worker` | same image, `celery -A app.worker` | — | Runs the harness |
| `postgres` | `postgres:16-alpine` | 5432 | Durable storage |
| `redis` | `redis:7-alpine` | 6379 | Broker + live state + LLM cache |

Compose overrides `REDIS_URL` and `DATABASE_URL` to point at the service names. One gotcha: with `MODEL_PROVIDER=ollama`, Ollama runs on the *host*, so containers must use `OLLAMA_BASE_URL=http://host.docker.internal:11434` — `localhost` inside a container is the container.

Key configuration (`.env`, read by `app/config.py`):

```bash
MODEL_PROVIDER=ollama|groq|openai|anthropic   # default: ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
DATABASE_URL=postgresql://...                 # overridden by compose
REDIS_URL=redis://...                         # overridden by compose
JOB_TTL_SECONDS=7200
LLM_CACHE_TTL_SECONDS=86400
SUMMARIZE_TRIGGER_TOKENS=...                  # thread compaction threshold
LANGFUSE_SECRET_KEY=... LANGFUSE_PUBLIC_KEY=... LANGFUSE_BASE_URL=...
TAVILY_API_KEY=...                            # reviewer's fact_check tool
```

See `docs/full_diagram.md` for the Mermaid diagrams of the topology, job lifecycle, and pipeline.

---

## Part 3 — Design Rationale

### How the pieces were chosen

Each architectural decision traces back to a requirement:

| Requirement | Decision |
| --- | --- |
| Content must be grounded, not hallucinated | Extract → write → review pipeline; writers only see `extracted_insights.md` |
| Multi-stage pipeline with different instructions per stage | Subagents with per-role skills (progressive disclosure) |
| Jobs take minutes; UI must stay responsive | Celery + Redis async queue; API only enqueues |
| Users need progress, not a spinner | File-based workspace → stage inferred from which files exist |
| Output is a draft until a human agrees | `awaiting_approval` status + approve/revise endpoints; revisions are child jobs |
| Token cost must stay bounded | Input caps + truncation, Redis response cache, Anthropic prompt cache |
| Agent behavior must be debuggable | Langfuse traces at API, worker, and pipeline levels, keyed by job_id |
| Swappable LLM backends (local dev → hosted prod) | LangChain provider abstraction behind `MODEL_PROVIDER` |

### Trade-offs accepted

- **Complexity vs. flexibility** — the harness adds layers over a single prompt. In exchange: composable skills, testable roles, and a framework reusable beyond DevVoice.
- **Latency vs. accuracy** — sequential extract → write → review is slower than single-shot generation, but structurally suppresses hallucination and produces an auditable reasoning chain.
- **Operational surface vs. durability** — PostgreSQL + Redis + two caches is more to run than an ephemeral service; the payoff is history, version comparison, revision chains, and an audit trail.

### Future extensions

- **Team workspaces** — share projects across an email domain
- **Per-brand context** — customize AGENTS.md and skills per user
- **Parallel writers** — platform writers are independent after extraction and could fan out concurrently
- **Streaming results** — surface each draft as its subagent finishes instead of after review
- **A/B tone runs** — multiple tone/audience combos in parallel, pick the best
- **Analytics** — track which platforms and tones perform

---

**DevVoice** is both a production content tool and a reference implementation of the agent-harness pattern: state backend + layered context + skills + subagents on the inside; queue, dual storage, human approval, cost control, and tracing on the outside. The harness makes the agents reliable; the architecture makes the harness a service.
