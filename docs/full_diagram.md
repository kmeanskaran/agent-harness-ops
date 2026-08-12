# DevVoice — Full System Diagram

Drop a README, get a reviewed X thread, LinkedIn post, and dev.to article.
Five containers on one Docker network, plus external LLM, observability, and search services.

## Container topology

```mermaid
flowchart TB
    subgraph host["Host machine"]
        browser["Browser<br/>localhost:3000"]
        ollama["Ollama (host process)<br/>:11434 — reach via host.docker.internal"]
    end

    subgraph docker["Docker network (docker compose)"]
        frontend["frontend<br/>nginx · 3000→80"]
        app["app<br/>FastAPI / uvicorn · 8000<br/>validation · rate limit 10/min · enqueue"]
        worker["worker<br/>Celery · generate_content_task"]
        postgres[("postgres:16-alpine<br/>users · projects · jobs · approvals")]
        redis[("redis:7-alpine<br/>Celery broker + live job store")]
    end

    subgraph external["External services"]
        llm["LLM provider<br/>MODEL_PROVIDER: ollama | groq | openai | anthropic"]
        langfuse["Langfuse Cloud<br/>us.cloud.langfuse.com<br/>traces · session_id = job_id"]
        tavily["Tavily<br/>web search tool"]
    end

    browser -->|HTTP| frontend
    frontend -->|"REST: /generate /revise /approve /history /result"| app
    app -->|"create_job + task.delay()"| redis
    app -->|"job record / user / project"| postgres
    redis -->|consume queue| worker
    worker -->|"status + result"| redis
    worker -->|progress + final state| postgres
    worker -->|chat completions| llm
    llm -.->|default provider| ollama
    app -.->|"@observe traces"| langfuse
    worker -.->|"@observe traces"| langfuse
    worker -.->|search| tavily
```

## Job lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User as Browser
    participant FE as frontend (nginx)
    participant API as app (FastAPI)
    participant R as redis
    participant PG as postgres
    participant W as worker (Celery)
    participant LF as Langfuse Cloud
    participant LLM as LLM provider

    User->>FE: submit README + options
    FE->>API: POST /generate
    API->>API: validate README (100KB / 12K tokens, truncate to 10K)
    API->>API: estimate job tokens
    API->>PG: upsert user/project, create job record
    API->>R: create_job + generate_content_task.delay()
    API-->>User: {job_id, status: queued}
    API--)LF: trace: enqueue_generation_job

    R->>W: deliver task
    W->>W: build brief.md
    W->>R: status = running / extracting / writing / reviewing
    W->>PG: update job progress
    W->>LLM: DeepAgents pipeline (extract → write → review)
    W--)LF: trace: generate_content_task + devvoice_pipeline
    W->>R: set awaiting_approval + result
    W->>PG: mark awaiting_approval

    loop poll
        User->>API: GET /result/{job_id}
        API->>R: read status/result
        API-->>User: status + drafts
    end

    alt approve
        User->>API: POST /approve/{job_id}
        API->>PG: approve job
        API->>R: approve job
    else revise
        User->>API: POST /revise/{job_id} (instruction)
        API->>PG: new job record (parent_job_id set)
        API->>R: enqueue revision with previous_result
    end
```

## Inside the worker — DeepAgents pipeline

```mermaid
flowchart TB
    task["Celery task<br/>generate_content_task(job_id, payload)"]
    brief["brief.md<br/>platforms · tone · audience · learnings · README"]
    orch["Orchestrator (create_deep_agent)<br/>coordinates only — never writes content"]

    task --> brief --> orch

    subgraph subagents["Subagents (isolated contexts, one skill each)"]
        extractor["extractor<br/>README → extracted_insights.md"]
        xw["x-writer<br/>→ x_draft.md"]
        lw["linkedin-writer<br/>→ linkedin_draft.md"]
        dw["devto-writer<br/>→ devto_draft.md"]
        reviewer["content-reviewer<br/>verifies & corrects all drafts<br/>→ review_notes.md"]
    end

    orch --> extractor
    extractor --> xw & lw & dw
    xw & lw & dw --> reviewer

    result["assemble_result()<br/>x_thread · linkedin_post · devto_article"]
    reviewer --> result
    result -->|awaiting_approval| task
```

## Key environment variables

| Variable | Purpose |
| --- | --- |
| `MODEL_PROVIDER` | `ollama` (default) \| `groq` \| `openai` \| `anthropic` (with prompt caching) |
| `OLLAMA_BASE_URL` | Must be `http://host.docker.internal:11434` from inside containers |
| `REDIS_URL` / `DATABASE_URL` | Overridden by compose to point at the `redis` / `postgres` services |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` | Observability — traces from API and worker |
| `TAVILY_API_KEY` | Web search tool for the agent pipeline |

Sources: `docker-compose.yml`, `Dockerfile`, `main.py`, `app/routes/content.py`, `app/worker/tasks.py`, `app/agent/orchestrator.py`, `app/agent/model.py`.
