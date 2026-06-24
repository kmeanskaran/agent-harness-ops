# Creating Agent Harness App for Content Creation

## Thread 🧵

**Building DevVoice: A Multi-Agent Content Generation System**

---

## Part 1: The Problem

I needed to transform developer READMEs into platform-native content (X threads, LinkedIn posts, dev.to articles) without reinventing the wheel each time.

Simple approach? One big LLM call. Problem? It hallucinates, misses nuances, and wastes tokens on redundant work.

So I built something different: **Agent Harness**—a framework for coordinating multiple specialized agents to do one job well.

---

## Part 2: What is Agent Harness?

Think of it like a team of writers instead of one author:

- **Extractor** reads the README and pulls out real facts (no making stuff up)
- **X-Writer** specializes in tweets—threading, engagement, platform norms
- **LinkedIn-Writer** knows professional tone, hashtag strategy, length limits
- **DevTo-Writer** understands technical articles—code formatting, narrative flow
- **Reviewer** fact-checks everything against the original README

Each agent gets:
1. Its own skill file (role-specific instructions)
2. Access to shared context (project guidelines)
3. An isolated workspace (so jobs don't collide)

Result? Better content, fewer hallucinations, clear reasoning chain.

---

## Part 3: How I Built It With DeepAgents

I didn't build the agent coordination from scratch. I used **DeepAgents**—a framework that handles:

- **Agent definition** (who, what, how)
- **Tool registration** (give agents capabilities)
- **State management** (persistent memory per job)
- **Subagent delegation** (orchestrator spawns workers)

Here's the flow:

```
Orchestrator says to Extractor:
  "Read /workspace/{job_id}/brief.md and write extracted_insights.md"

Extractor runs, writes output

Orchestrator says to X-Writer:
  "Read extracted_insights.md and write x_draft.md"

X-Writer runs, writes output

[Same for LinkedIn and dev.to writers]

Orchestrator says to Reviewer:
  "Check all drafts against extracted_insights.md, fix them, write review_notes.md"

Reviewer runs, done.
```

All of this—state management, context loading, skill disclosure—DeepAgents handles. I just define who does what.

---

## Part 4: Making It Async With Celery

Here's the key: generation is **slow**. Why block the user waiting for an LLM?

I used **Celery** (distributed task queue) + **Redis** (message broker):

```
User submits README
     ↓
FastAPI validates, saves job to PostgreSQL
     ↓
Celery task is enqueued in Redis
     ↓
Worker picks up task (could be on a different machine)
     ↓
Worker calls DeepAgents orchestrator
     ↓
Orchestrator runs agents, writes results
     ↓
Results saved to PostgreSQL + Redis
     ↓
Frontend polls every 2 seconds: "Is it done?"
     ↓
When done, displays results
```

Why this matters:
- User gets instant feedback ("Your job is queued")
- Multiple jobs can run in parallel
- You can scale workers horizontally
- One server crashing doesn't lose jobs (Redis persists them)

---

## Part 5: Caching to Avoid Redundant Work

Problem: User submits same README twice → generates content twice → wastes tokens.

Solution: **Three-layer caching**

**Layer 1: Frontend Cache**
- Remember what you've generated
- "Hey, I already made X for this README"
- Auto-detect project from history
- If all platforms exist → load instantly (zero API calls)

**Layer 2: Redis LLM Cache**
- Every LLM call is cached by `SHA-256(model + prompt)`
- Same prompt twice? Return cached response, zero tokens
- 24-hour TTL
- Works with Groq, Ollama, OpenAI, Anthropic

**Layer 3: Anthropic Prompt Caching**
- Native caching for system messages
- Static parts cached for 5 minutes
- 90% token discount on cache hits
- Automatic, transparent

Result: Recurring work costs 10% of first-run cost.

---

## Part 6: The Complete Architecture

```
Frontend (React)
├─ Smart cache detection
├─ Clickable projects
└─ Per-platform version management
         ↓
API (FastAPI)
├─ Validates requests
├─ Enqueues jobs
└─ Polls for results
         ↓
Queue (Celery + Redis)
├─ Distributes work
└─ Persists job state
         ↓
Orchestrator (DeepAgents)
├─ Manages subagents
├─ Shares context
└─ Streams progress
         ↓
Cache (Redis + Anthropic)
├─ Stores responses
└─ Avoids redundant work
         ↓
Storage (PostgreSQL + Redis)
├─ Persists jobs
├─ Persists results
└─ Maintains history
```

Each layer has a job. None are overloaded. None are doing work they shouldn't.

---

## Part 7: How Users Interact With It

**Scenario 1: New README**
```
User: Paste README → Select platforms → Click Generate
System: Creates job → Queues in Redis → Workers run → Results in 30 seconds
Cost: Full LLM calls
```

**Scenario 2: Same README Again**
```
User: Paste same README → Click Generate
System: Detects project from history → Finds all platforms already exist
Result: Instant (cached results) — 0 seconds, $0.00
```

**Scenario 3: Update One Platform**
```
User: Has X, LinkedIn, dev.to. Wants new tone for LinkedIn only.
System: 
  - Detects project
  - Sees X and dev.to exist in cache
  - Only regenerates LinkedIn
Result: 10 seconds, 10% token cost
```

**Scenario 4: Explore History**
```
User: Clicks project name in sidebar
System: Opens new tab → Loads latest generation → Shows version labels
Result: Full view of all platforms, v1/3 for each
```

---

## Part 8: Why This Architecture?

**Separation of Concerns**
- Extractor focuses on accuracy
- Writers focus on platform norms
- Reviewer focuses on quality
- No agent does multiple jobs

**Scalability**
- Add more workers? Celery scales
- More users? FastAPI handles it
- Need more cache? Redis can grow

**Reliability**
- Jobs persisted in PostgreSQL (audit trail)
- Failed jobs stay in Redis (can retry)
- State isolation (one bad job doesn't break others)

**Cost Efficiency**
- Caching reduces token spend by 70%+ on recurring work
- Partial regeneration only updates what changed
- Smart prompts reduce hallucinations (fewer rewrites)

**User Experience**
- No blocking waits (async)
- Clear progress (polling)
- Instant results when cached
- Explore history freely

---

## Part 9: The Tech Stack

- **Frontend:** React + Vite + TypeScript (SPA workspace)
- **Backend:** FastAPI (lightweight API)
- **Queue:** Celery + Redis (async jobs)
- **Orchestration:** DeepAgents (multi-agent coordination)
- **LLM:** Anthropic, OpenAI, Groq, Ollama (pluggable)
- **Storage:** PostgreSQL (jobs), Redis (cache + state)
- **Caching:** RedisLLMCache + Anthropic Prompt Caching

Total lines of code? ~3000 (excluding UI). But the architecture scales.

---

## Part 10: How I Actually Made This

**Phase 1: Define the agents**
```
created files:
- /skills/extractor/SKILL.md
- /skills/x-writer/SKILL.md
- /skills/linkedin-writer/SKILL.md
- /skills/devto-writer/SKILL.md
- /skills/content-reviewer/SKILL.md
```

Each skill is 200-400 tokens. Clear instructions, no fluff.

**Phase 2: Build the orchestrator**
```
created: app/agent/orchestrator.py

Key function: run_job(job_id, brief, platforms)
- Seeds files (skills + brief)
- Creates state backend
- Delegates to subagents in sequence
- Assembles final result
- Handles errors gracefully
```

**Phase 3: Wire up Celery**
```
created: app/worker/celery_app.py, tasks.py

Key function: generate_content_task(job_id, payload)
- Receives job from Redis queue
- Builds brief from payload
- Calls run_job()
- Updates Redis with progress
- Stores result in PostgreSQL
```

**Phase 4: Build the API**
```
created: app/routes/content.py

Key endpoint: POST /generate
- Validates input
- Creates project record
- Enqueues Celery task
- Returns job_id immediately
- User polls GET /result/{job_id}
```

**Phase 5: Build the frontend**
```
created: frontend/src/App.tsx

Features:
- Input form (README, learnings, tone, audience, platforms)
- Progress display (real-time polling)
- Results panel (tabbed view per platform)
- History sidebar (projects grouped, expandable)
- Version tracking (v1/3 labels)
```

**Phase 6: Add smart caching**
```
modified: frontend/src/App.tsx, app/agent/cache.py

Features:
- Auto-detect projectId from history
- Load from cache if all platforms exist
- Partial regeneration for missing platforms
- Per-platform version swapping
```

Total time? Could do it in a week if you know the stack. I spent longer iterating on UX and adding polish.

---

## Part 11: What's Cool About This

**For Developers:**
- Reusable Agent Harness pattern (could use this for any multi-step task)
- Pluggable LLM providers (swap Anthropic for Groq with one env var)
- Horizontal scalability (add more workers, done)
- Testable agents (test each skill independently)

**For Users:**
- Grounded content (no hallucinations, everything sourced from README)
- Fast iteration (update one platform, keep others)
- Instant results (caching eliminates waiting)
- Full history (compare versions, explore old work)

**For My Wallet:**
- 70% token savings on recurring work
- Smart caching prevents redundant API calls
- Per-platform regeneration only pays for changes

---

## Part 12: The Key Insights

**Insight 1: Specialization beats generalization**
One agent doing five things → hallucinations. Five agents doing one thing → quality.

**Insight 2: State isolation enables scale**
Each job gets its own workspace. Jobs don't interfere. Workers can run in parallel.

**Insight 3: Caching compounds**
First-time cost is high. Second time is free. By user 100, cost per request is near zero.

**Insight 4: Async-first design**
Users don't wait. They do other work. You scale better. Everyone wins.

**Insight 5: Context engineering > longer prompts**
Give agents stable context (AGENTS.md) once. Load skills dynamically. Prompts stay small.

---

## Part 13: What's Next?

- **Template presets** (save "technical + CTOs" as shortcut)
- **Batch operations** (regenerate all platforms at once, show diffs)
- **Cache analytics** (see what's cached, estimate token savings)
- **Team workspaces** (share projects across email domains)
- **Streaming results** (get output as each agent completes)

---

## Part 14: TL;DR

I built **DevVoice** using the **Agent Harness** pattern:

1. Created specialized agents (extractor, writers, reviewer)
2. Built orchestrator to coordinate them (DeepAgents)
3. Made it async with Celery + Redis
4. Added multi-layer caching (Redis + Anthropic)
5. Built React frontend with smart cache detection
6. Result: Fast, cheap, reliable content generation

The system transforms READMEs into platform content, avoids hallucinations through grounding, scales horizontally, and costs 70% less on recurring work.

Not magic. Just good architecture.

---

## The Commit History

```
4df27b6 - Implement smart caching and project interaction features
5f744d4 - Expand documentation with Agent Harness and DeepAgents coverage
fa13b90 - Fix markdown formatting
```

---

**If you're building a multi-agent system, consider the Agent Harness pattern. If you want to reduce LLM costs, add intelligent caching. If you want to scale async work, use Celery.**

That's the foundation.

The rest is iteration. 🚀
