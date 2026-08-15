# DevVoice: Building an Agent Harness

## What This Document Covers

**DevVoice** turns a developer's README into reviewed, platform-native content for X (Twitter), LinkedIn, and dev.to. But the more interesting story is *how* it's built: DevVoice is a working implementation of the **Agent Harness** pattern — the scaffolding that surrounds an LLM agent so it behaves reliably in production.

This document explains, in order:

1. What an agent harness is and why DevVoice needed one
2. How we built the harness — the four pillars, with the actual code decisions behind each
3. How the full production architecture grew around the harness — API, queue, storage, caching, observability, frontend, and both deployment targets
4. The design rationale and trade-offs

---

## Part 0 — The Use Case

### Who it is for and what it does

Developers ship interesting work and then write nothing about it, because turning a project into a post is a different skill from building it — and the generic-LLM version of that post is worse than silence. It reads as marketing, invents details, and flattens the one thing worth reading: what was actually hard.

DevVoice takes what the developer already has and produces content grounded in it.

**Input.** A README (pasted or uploaded), a list of learnings, a list of hard parts, plus a tone, an audience, and the target platforms.

**Output.** One reviewed draft per requested platform:

| Platform | Shape |
| --- | --- |
| X (Twitter) | 6–10 tweet thread, hook first, per-tweet character counts |
| LinkedIn | 150–300 word post, personal narrative, short paragraphs |
| dev.to | 1000–1500 word article, Problem → What → How structure |

Plus `review_notes.md` — what the reviewer changed and why.

### The functional guarantees

Four properties are what make this a product rather than a prompt:

**Grounded, not invented.** Facts are extracted from the source into `extracted_insights.md` *first*, and the writers see only that file. A writer structurally cannot invent a benchmark number, because it never sees anything to embellish. The reviewer then checks each draft back against the insights and rewrites in place.

**Human-approved.** Jobs finish in `awaiting_approval`, never `completed`. Agent output is a draft until a person says otherwise.

**Revisable with context.** "Make it less formal" creates a *child job* carrying `parent_job_id`, seeded with the previous output and the instruction — so a revision refines rather than regenerating blind. Chains are fully reconstructable.

**Observable while it runs.** Progress is derived from which workspace files exist, so the UI shows extracting → writing → reviewing rather than a spinner.

### What it is not

Not a scheduler or publisher — it produces text, and posting stays manual. Not a research tool: the only outward-facing tool is `fact_check`, restricted to *verifying* a claim a draft already makes, never adding new ones. And not a general chat interface; the input shape is fixed because the grounding guarantee depends on knowing what the source is.

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
- **bedrock** — Amazon Bedrock via the Converse API. This is what the deployed stack runs. Credentials are never passed: boto3 resolves them from the ECS task role. `_CachingChatBedrock` applies the same cache breakpoints, but only for Anthropic model ids — other families reject `cachePoint` blocks outright.
- **bedrock_openai** — the OpenAI-compatible `bedrock-mantle` endpoint, required for models not served on Converse. Auth is a short-lived bearer token minted from the ambient IAM identity, not a stored key.

The layered-context design and prompt caching reinforce each other: because durable context is separated from per-job context, the cacheable prefix is large and stable.

**The model must support structured tool calling.** The orchestrator does all its work through tools — every draft is written with `write_file` — so a model that replies in prose produces an empty workspace and a blank result, with no error anywhere. `google.gemma-*` on Bedrock fails exactly this way: it replies in Google's own ` ```tool_code ` dialect, which AWS has no Converse adapter for, so the reply arrives as plain text with `stopReason: end_turn` and LangGraph has nothing to dispatch. Emitting one tool call is also not sufficient — sustaining a multi-step delegation across dozens of turns is a strictly harder capability, and models that pass the first test can still fail the second by looping on an already-completed step, re-reading a file it has already read or re-listing a directory whose contents it just received.

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

Structured JSON logs trace every stage — job lifecycle events plus a per-turn tool trace; two caching layers cut token cost. In AWS the same shape runs on ECS Fargate behind an ALB, with RDS and ElastiCache replacing the local Postgres and Redis containers.

### Why asynchronous: API and worker are separate processes

An agent pipeline takes minutes; an HTTP request should take milliseconds. So the API (`main.py`, `app/routes/`) does only cheap work — validation, token estimation, record creation, `generate_content_task.delay()` — and returns `{job_id, status: queued}` immediately. The Celery worker (`app/worker/tasks.py`) does everything expensive. The frontend polls `GET /result/{job_id}`.

Workers are stateless and scale horizontally: run more worker containers, jobs distribute automatically through the Redis broker.

**Bounding a job that will not end.** An agent loop has no natural terminating condition. LangGraph's `recursion_limit` (100) counts model→tool→model round trips, not seconds, so a run that stalls *between* turns runs forever and holds its concurrency slot; with `task_acks_late=True`, restarting the worker redelivers the task, which hangs again. Celery therefore sets a wall-clock backstop: `task_soft_time_limit` (900s) raises `SoftTimeLimitExceeded` **inside** the task, so the handler can record a real `JobTimeout` in Redis and Postgres, and `task_time_limit` (1020s) hard-kills the child if the soft limit is swallowed somewhere in the graph. `task_reject_on_worker_lost=False` ensures a hard-killed task fails once instead of being redelivered forever.

This is the difference between "a job failed" and "the worker silently degrades" — and it matters most exactly when the agent is misbehaving, which is when you least want to be debugging the queue as well.

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

   A cached reply is replayed to LangGraph *in place of* a real model response, so the round-trip must preserve `tool_calls` and `response_metadata`. These are not recoverable from `content` — providers populate them alongside it — and a cache hit that loses them reads as a plain final answer with nothing to dispatch, reproducing the blank-output failure intermittently and only once the cache is warm. `tests/test_cache.py` asserts the round-trip, because nothing raises when it breaks.
3. **Prompt cache (Anthropic)** — the stable context prefix (AGENTS.md, skills, system prompts) is cache-marked, giving ~90% off input tokens on repeat calls within 5 minutes.

### Observability — structured logs, with Langfuse shimmed out

Three layers, of which only the first two are currently live.

**1. Job-level events (live).** `app/worker/tasks.py` emits one structured JSON line per lifecycle transition — `job_start`, `job_progress`, `job_done`, `job_failed`, `job_timeout` — each carrying `job_id`, elapsed time, and platform. Queryable by `job_id` in CloudWatch Logs Insights.

**2. Tool-level trace (live).** `app/agent/tracing.py` registers a `ToolTraceHandler` callback on the graph run. It logs one `model_turn` line per model turn with the tool names, a 200-character argument preview, and `stopReason`, plus a `tool_result` line with the result size and preview.

This layer exists because of a specific failure. The logs previously recorded only *that* a Bedrock call happened — never which tool was requested or what came back. A run that burned ~90 turns without writing a single file was undiagnosable from logs alone: "the agent mangled the subagent request" and "the agent got a result and did not recognise it as done" produce identical output at that granularity. With argument previews, the two are one glance apart. Parsing is defensive throughout — tracing must never be able to break a run.

**3. Langfuse (wired, disabled).** Every `@observe` decorator and `update_current_trace(...)` call site is still in place across `main.py`, `app/routes/content.py`, `app/worker/tasks.py` and `app/agent/orchestrator.py`, keyed by `session_id = job_id`. But those modules import no-op stand-ins from `app/observability.py` rather than the real SDK, so the calls execute and do nothing.

It was disabled to eliminate it as a variable during debugging: the keys were `REPLACE_ME`, so it was reporting nowhere useful while still adding network calls and failure surface to jobs that were already failing. Swapping the imports rather than commenting out ~17 call sites kept the change to one line per module, in code paths that only execute in the deployed worker.

One subtlety in the shim: `observe()` returns the decorated function **completely unwrapped**. It sits beneath `@celery_app.task`, and any wrapper would change what Celery registers and hide `.delay`.

Re-enabling is one uncommented import per module, plus real values for `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` — procedure in the `app/observability.py` docstring, dependency still in `pyproject.toml`. Worth doing for token/cost accounting per job and a UI for stepping through traces; layer 2 already covers the "which tool, with what arguments" question more cheaply.

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

### Deployment 1 — Docker Compose (local)

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
MODEL_PROVIDER=ollama|groq|openai|anthropic|bedrock|bedrock_openai
MODEL_NAME=...                                # provider-specific model id
OLLAMA_BASE_URL=http://host.docker.internal:11434
DATABASE_URL=postgresql://...                 # overridden by compose
REDIS_URL=redis://...                         # overridden by compose
JOB_TTL_SECONDS=7200
JOB_SOFT_TIME_LIMIT=900                       # Celery soft limit, seconds
JOB_HARD_TIME_LIMIT=1020                      # Celery hard limit, seconds
LLM_CACHE_TTL_SECONDS=86400
SUMMARIZE_TRIGGER_TOKENS=...                  # thread compaction threshold
LANGFUSE_SECRET_KEY=... LANGFUSE_PUBLIC_KEY=... LANGFUSE_BASE_URL=...
TAVILY_API_KEY=...                            # reviewer's fact_check tool
```

Placeholder sentinels (`REPLACE_ME`, `changeme`, `TODO`) are normalised to `""` by `_secret()` in `app/config.py`. Terraform seeds unconfigured secrets with `REPLACE_ME`, which is a *truthy* string — so an `if not s.SOME_KEY` guard would pass and the code would call the API with a junk credential. Normalising at the boundary makes every existing truthiness guard correct at once.

### Deployment 2 — AWS (Terraform + GitHub Actions)

The same two images run on ECS Fargate. Everything is Terraform (`terraform/`), applied by CI; nothing is clicked in the console.

#### Topology

| Layer | Service | Notes |
| --- | --- | --- |
| Ingress | Application Load Balancer | Public. Routes to the frontend task; nginx in that container proxies `/api` → the API service. |
| Compute | ECS Fargate — `api`, `worker`, `frontend` | One task each. Service discovery via a Cloud Map private DNS namespace, so the frontend reaches `http://api.<namespace>:8000`. |
| Database | RDS PostgreSQL 16 | `db.t4g.micro`, single-AZ. |
| Cache / broker | ElastiCache Redis 7.1 | Single node. |
| Images | ECR — `api`, `frontend` | Tagged with the commit SHA. |
| Secrets | Secrets Manager | `DATABASE_URL`, `TAVILY_API_KEY`, both Langfuse keys — injected as task `secrets`, never baked into images. |
| Logs | CloudWatch `/ecs/agent-harness-<env>/<service>` | 7-day retention. |
| Guardrails | AWS Budgets + SNS email | Monthly threshold, plus an alarm on job failures. |

**Model access uses no keys.** The task role holds `bedrock:InvokeModel`, and boto3 resolves credentials from it. The grant is *derived* from `var.model_name` (`terraform/iam.tf`) rather than hardcoded, covering both ARN shapes — a foundation model (`zai.glm-4.7`) and a cross-region inference profile (`us.anthropic.claude-sonnet-4-6`, which additionally needs invoke rights on the underlying foundation model, hence stripping the `us.`/`eu.`/`apac.` prefix). Hardcoding model families here previously meant that changing `MODEL_NAME` produced a clean Terraform apply and a broken deploy.

**State.** An S3 bucket with a DynamoDB lock table, created once by `terraform/bootstrap`. The backend block is deliberately empty (partial config) because bucket names embed an account id and backend blocks cannot interpolate variables — supply it at init:

```bash
terraform init -reconfigure -backend-config=backend.hcl
```

**Environments are Terraform workspaces.** `dev` and `prod` share one bucket, namespaced under `env:/<workspace>/`. Sizing is keyed on the workspace in `locals.tf`. As a POC both are sized identically: smallest everything, single node, no HA, and built to be destroyed. `prod` here means "a second isolated stack", not "hardened" — making it real means restoring multi-AZ RDS, >1 Redis node, >1 task per service, deletion protection, final snapshots, and private subnets with a NAT gateway. Tasks currently run in **public** subnets with public IPs and no NAT, which saves ~$32/mo and is a deliberate POC trade-off.

**CI/CD** (`.github/workflows/ci.yml`). Auth is GitHub OIDC — a short-lived token per run, no AWS keys stored in GitHub; only the role ARN, as a repo *variable*. The ref decides the target:

```text
refs/heads/aws-deployment → dev    (deploys straight through)
refs/tags/prod-*          → prod   (pauses for a required reviewer)
```

Pipeline order: quality (pre-commit) · terraform validate · unit tests · smoke → ensure ECR repos → build both images → `terraform apply` → force a new ECS deployment. The prod approval gate is the `environment:` declaration on the deploy job, backed by a GitHub Environment with a required reviewer. Promotion is therefore a tag, not a merge:

```bash
git tag prod-2026-08-15 && git push origin prod-2026-08-15
```

Note that this stands up a *second complete stack* — its own RDS, Redis and ALB — roughly doubling spend, not a promotion of the dev one.

**Operations** (`Makefile`, all take `env=` and `profile=`):

```bash
make aws-bootstrap profile=mgmt   # one-time: state bucket, lock table, OIDC, deploy role
make aws-status  env=dev          # task counts + recent service events
make aws-url     env=dev          # ALB URL + health check
make aws-logs    env=dev s=worker # live tail
make aws-errors  env=dev          # errors across all services, last 30m
make aws-destroy                  # stop the meter
make aws-verify-clean             # prove nothing is still billing
```

**A warning the deployment learned the hard way.** Every health check passed while the product generated nothing at all. `/api/health` proves the API is up and can reach Redis; the ALB check proves nginx serves the frontend. Neither touches Bedrock, Celery, or the agent. **The only check that detects an agent-level failure is submitting a real job and asserting the returned content is non-empty** — everything else stays green on a completely broken app.

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
| Agent behavior must be debuggable | Structured per-turn tool traces in CloudWatch, keyed by job_id; Langfuse call sites retained behind no-op shims |
| Swappable LLM backends (local dev → hosted prod) | LangChain provider abstraction behind `MODEL_PROVIDER` |
| A stalled agent must fail, not hang | Celery soft/hard time limits; `EmptyGenerationError` when every platform comes back empty |
| Deploys must not need stored cloud credentials | GitHub OIDC for CI, ECS task role for Bedrock — no long-lived keys anywhere |
| Config that must agree cannot drift silently | IAM Bedrock grant derived from `var.model_name`; prompt placeholders asserted rendered by test |

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

**DevVoice** is both a production content tool and a reference implementation of the agent-harness pattern: state backend + layered context + skills + subagents on the inside; queue, dual storage, human approval, cost control, and tracing on the outside; Terraform, OIDC-authenticated CI, and two isolated environments underneath. The harness makes the agents reliable; the architecture makes the harness a service; the deployment makes it reproducible.

The recurring lesson across all three layers is the same: **the dangerous failures are the silent ones.** A model that cannot call tools, an IAM grant that drifts from the model it guards, a prompt placeholder nothing renders, a cache that drops tool calls, a job with no time limit — none of these raise. They produce green health checks and empty output. Every guard described here exists because something failed quietly first.
