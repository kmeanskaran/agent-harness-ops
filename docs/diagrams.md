# System Diagrams

---

## 1. Full System Architecture

```mermaid
graph TB
    subgraph Client["Client Layer"]
        C[HTTP Client]
    end

    subgraph API["FastAPI — HTTP Layer"]
        R1[POST /generate]
        R2[GET /result/:job_id]
        RL[Rate Limiter\nper user email]
        VAL[Token Validator\n+ Truncator]
    end

    subgraph Queue["Job Queue — Celery + Redis"]
        B[(Redis\nBroker)]
        W1[Worker — gevent pool\nconcurrency=32]
        W2[Worker — gevent pool\nconcurrency=32]
    end

    subgraph Store["State Stores"]
        RJ[(Redis\nJob Store\nTTL=2h)]
        PG[(Postgres\nDurable Record)]
    end

    subgraph Harness["Agent Harness"]
        ORCH[Orchestrator\nbuilt once via lru_cache]
        subgraph Workspace["StateBackend — Virtual Filesystem"]
            F1[/workspace/job_id/brief.md]
            F2[/workspace/job_id/extracted_insights.md]
            F3[/workspace/job_id/x_draft.md]
            F4[/workspace/job_id/linkedin_draft.md]
            F5[/workspace/job_id/devto_draft.md]
            F6[/workspace/job_id/review_notes.md]
        end
        subgraph Agents["Subagents — Isolated Contexts"]
            A1[extractor]
            A2[x-writer]
            A3[linkedin-writer]
            A4[devto-writer]
            A5[content-reviewer]
        end
        subgraph Skills["Skill Files"]
            SK1[/skills/extractor/SKILL.md]
            SK2[/skills/x-writer/SKILL.md]
            SK3[/skills/linkedin-writer/SKILL.md]
            SK4[/skills/devto-writer/SKILL.md]
            SK5[/skills/content-reviewer/SKILL.md]
        end
        MEM[/context/AGENTS.md\ndurable memory]
    end

    subgraph Cache["Caching Stack"]
        PC[Anthropic\nPrompt Cache\n90% off cached tokens]
        RC[(Redis\nLLM Response Cache\nTTL=24h)]
        EC[(Redis\nExtraction Cache\nTTL=7d)]
    end

    subgraph Obs["Observability"]
        LF[LangFuse\nFull call traces]
        LOG[Structured Logs\njob_id, status, elapsed]
    end

    C -->|POST readme + params| R1
    R1 --> RL
    RL --> VAL
    VAL -->|validate + truncate| B
    VAL -->|create job record| RJ
    VAL -->|create job record| PG
    R1 -->|job_id + queued| C
    C -->|poll| R2
    R2 -->|read status| RJ
    RJ -.->|fallback| PG

    B --> W1
    B --> W2
    W1 --> ORCH
    W2 --> ORCH

    ORCH --> F1
    ORCH -->|delegate| A1
    A1 -->|reads| F1
    A1 -->|writes| F2
    A1 -->|loads| SK1
    ORCH -->|delegate| A2
    A2 -->|reads| F2
    A2 -->|writes| F3
    A2 -->|loads| SK2
    ORCH -->|delegate| A3
    A3 -->|reads| F2
    A3 -->|writes| F4
    A3 -->|loads| SK3
    ORCH -->|delegate| A4
    A4 -->|reads| F2
    A4 -->|writes| F5
    A4 -->|loads| SK4
    ORCH -->|delegate| A5
    A5 -->|reads| F2
    A5 -->|reads| F3
    A5 -->|reads| F4
    A5 -->|reads| F5
    A5 -->|writes| F6
    A5 -->|loads| SK5
    ORCH --> MEM

    A1 <-->|check/write| EC
    W1 <-->|check/write| RC
    A1 & A2 & A3 & A4 & A5 <-->|system msg cache| PC

    W1 -->|progress + result| RJ
    W1 -->|progress + result| PG
    ORCH -->|trace| LF
    W1 -->|logs| LOG
```

---

## 2. Agent Pipeline — Step by Step

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant Q as Celery Queue
    participant W as Worker
    participant O as Orchestrator
    participant E as Extractor
    participant WR as Writers (x/li/devto)
    participant RV as Reviewer
    participant WS as Workspace (StateBackend)
    participant RS as Redis Store

    C->>API: POST /generate {readme, platforms, ...}
    API->>API: validate + truncate README
    API->>RS: create_job(job_id, queued)
    API->>Q: enqueue task(job_id, payload)
    API-->>C: {job_id, status: queued}

    Note over C,RS: Client polls GET /result/:job_id

    Q->>W: pick up task
    W->>W: estimate_job_tokens()
    W->>RS: set_status(running)
    W->>O: run_job(job_id, brief_md)

    O->>WS: seed files (skills + AGENTS.md + brief.md)
    O->>RS: set_status(extracting)
    O->>E: delegate(job_id)
    E->>WS: read brief.md
    E->>WS: write extracted_insights.md
    E-->>O: "Wrote extracted_insights.md"

    O->>RS: set_status(writing)
    O->>WR: delegate x-writer(job_id)
    WR->>WS: read extracted_insights.md
    WR->>WS: write x_draft.md
    WR-->>O: "Wrote x_draft.md"

    O->>WR: delegate linkedin-writer(job_id)
    WR->>WS: read extracted_insights.md
    WR->>WS: write linkedin_draft.md
    WR-->>O: "Wrote linkedin_draft.md"

    O->>RS: set_status(reviewing)
    O->>RV: delegate content-reviewer(job_id)
    RV->>WS: read extracted_insights.md + all drafts
    RV->>WS: write review_notes.md
    RV-->>O: "Wrote review_notes.md"

    O-->>W: stream complete
    W->>WS: assemble_result(files, job_id, platforms)
    W->>RS: set_awaiting_approval(result)
    W-->>C: (via poll) {status: awaiting_approval, x_thread: [...], ...}
```

---

## 3. Caching Stack — Three Layers

```mermaid
graph LR
    REQ[Incoming\nLLM Call] --> L3

    subgraph L3["Layer 3 — Content Identity Cache"]
        EC_CHK{Extraction\ncached?\nsha256 of source}
        EC_HIT[Return cached\nextraction\nTTL=7d]
        EC_MISS[Run extraction\nagent]
        EC_WRITE[Cache\nextraction result]
    end

    subgraph L2["Layer 2 — Redis LLM Response Cache"]
        RC_CHK{Response\ncached?\nsha256 of messages\n+ model config}
        RC_HIT[Return cached\nresponse\nTTL=24h]
        RC_MISS[Make API call]
        RC_WRITE[Cache\nresponse]
    end

    subgraph L1["Layer 1 — Anthropic Prompt Cache"]
        PC_CHK{Prefix\ncached?\nbyte-identical\nstatic prefix}
        PC_HIT[Read cached\nKV tensors\n10% of normal cost]
        PC_MISS[Full token\ncompute\n100% cost]
        PC_WRITE[Write cache\nbreakpoint]
    end

    RESP[LLM\nResponse]

    EC_CHK -->|hit| EC_HIT
    EC_CHK -->|miss| EC_MISS
    EC_MISS --> L2
    EC_HIT --> RESP

    RC_CHK -->|hit| RC_HIT
    RC_CHK -->|miss| RC_MISS
    RC_MISS --> L1
    RC_HIT --> RESP
    EC_MISS --> RC_CHK

    PC_CHK -->|hit| PC_HIT
    PC_CHK -->|miss| PC_MISS
    PC_MISS --> RESP
    PC_HIT --> RESP
    RC_MISS --> PC_CHK

    RESP --> RC_WRITE
    RESP --> EC_WRITE
    PC_MISS --> PC_WRITE

    style EC_HIT fill:#22c55e,color:#fff
    style RC_HIT fill:#22c55e,color:#fff
    style PC_HIT fill:#22c55e,color:#fff
    style EC_MISS fill:#f97316,color:#fff
    style RC_MISS fill:#f97316,color:#fff
    style PC_MISS fill:#ef4444,color:#fff
```

---

## 4. Context Engineering — What Each Agent Sees

```mermaid
graph TB
    subgraph Stable["Stable — loaded once, cached"]
        TD[Tool Definitions]
        SP[System Prompt]
        SK[Skill File\nfor this agent only]
        MEM[AGENTS.md\ndurable memory]
    end

    subgraph Dynamic["Dynamic — changes per job"]
        CH[Conversation History\ngrows per job]
        UM[User Message\nfully dynamic]
    end

    subgraph Budget["Context Budget"]
        CACHE_ZONE["▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ Cached prefix\n(90% cheaper)"]
        LIVE_ZONE["░░░░░░░░░░ Live tokens\n(full price)"]
    end

    TD --> CACHE_ZONE
    SP --> CACHE_ZONE
    SK --> CACHE_ZONE
    MEM --> CACHE_ZONE
    CH --> LIVE_ZONE
    UM --> LIVE_ZONE

    CACHE_ZONE -->|"static-before-dynamic\nrule enforced here"| LIVE_ZONE

    subgraph Wrong["❌ Wrong order — breaks cache"]
        direction LR
        W1[System prompt]
        W2[job_id in prompt]
        W3[Tool defs]
        W2 -.->|cache miss| W1
    end

    subgraph Right["✅ Right order — cache hits"]
        direction LR
        R1[Tool defs]
        R2[System prompt]
        R3[Skill file]
        R4[job_id in user turn]
        R1 --> R2 --> R3 --> R4
    end
```

---

## 5. Workspace State Machine — Job Lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued : POST /generate\nHTTP accepts immediately

    queued --> running : Worker picks up task\nvalidates + estimates tokens

    running --> extracting : Orchestrator delegates\nto extractor subagent

    extracting --> writing : extracted_insights.md\nappears in workspace

    writing --> reviewing : all platform draft files\nappear in workspace

    reviewing --> awaiting_approval : review_notes.md\nappears in workspace

    awaiting_approval --> completed : User approves\nPOST /approve/:job_id

    awaiting_approval --> running : User requests revision\nPOST /revise/:job_id\n(re-runs with previous output)

    running --> failed : Any unhandled exception\nor token budget exceeded
    extracting --> failed : Extraction fails
    writing --> failed : Writer fails
    reviewing --> failed : Reviewer fails

    completed --> [*]
    failed --> [*]

    note right of queued
        Redis + Postgres\ncreated here
    end note

    note right of awaiting_approval
        Result written to\nRedis (2h TTL)\n+ Postgres (permanent)
    end note
```

---

## 6. Worker Concurrency Model

```mermaid
graph TB
    subgraph API_Layer["FastAPI (sync)"]
        EP["/generate endpoint\nreturns in <50ms"]
    end

    subgraph Queue_Layer["Redis Broker"]
        Q[(Task Queue)]
    end

    subgraph Worker_Layer["Celery Worker — gevent pool"]
        direction TB
        W[Worker Process\n4 CPU cores]
        subgraph Coroutines["32 Concurrent Coroutines (gevent)"]
            T1[Task 1\nwaiting API response...]
            T2[Task 2\nwaiting API response...]
            T3[Task 3\nrunning extractor...]
            T4[Task 4\nwaiting API response...]
            TN[Task 5-32\n...]
        end
        W --> Coroutines
    end

    subgraph Time["Why 32 concurrency works"]
        direction LR
        IDLE["~75% of time:\nblocked on LLM API I/O\n(gevent yields here)"]
        ACTIVE["~25% of time:\nactual CPU work\n(parsing, serializing)"]
    end

    EP -->|fire and forget| Q
    Q --> W
    T1 & T2 & T3 & T4 & TN -.->|"asyncio.run()\nbridge"| ASYNC[Async LangChain\n+ DeepAgents]

    style IDLE fill:#94a3b8,color:#fff
    style ACTIVE fill:#3b82f6,color:#fff
```

---

## 7. Dual Store Pattern — Redis + Postgres

```mermaid
graph LR
    W[Worker\ncompletes job]

    subgraph Write["Write Path (always both)"]
        W -->|"set_status()\nset_result()"| RD
        W -->|"update_job_progress()\nmark_completed()"| PG
    end

    subgraph RD["Redis — Fast Path\nTTL = 2 hours"]
        RH[("jobs:{job_id}\nhash\n{status, result, step}")]
        RU[("user:{email}:active_jobs\nset")]
        RP[("project:{id}:jobs\nsorted set")]
    end

    subgraph PG["Postgres — Durable Path\nno TTL"]
        PJ[jobs table\nfull audit trail]
        PU[users table]
        PPJ[projects table]
    end

    subgraph Read["Read Path"]
        CLIENT[Client\npolling /result/:id]
        CLIENT -->|"sub-millisecond"| RH
        RH -->|"cache miss\n(after 2h)"| PJ
    end

    RH -.->|"expired after 2h\nsilent"| PJ
    PJ -->|"always available\nfor history"| CLIENT

    style RH fill:#dc2626,color:#fff
    style PJ fill:#1d4ed8,color:#fff
```
