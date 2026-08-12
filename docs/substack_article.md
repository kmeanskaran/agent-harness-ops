# The Agent Harness: A Complete Engineering Guide

*From concept to production — how to design the infrastructure layer that makes multi-agent LLM systems fast, cheap, observable, and maintainable.*

---

Building a single LLM call into a product takes an afternoon. Building a multi-agent pipeline that works reliably under real conditions — with real users, real costs, real failure modes — takes a fundamentally different approach.

The difference is the harness.

This guide covers the complete engineering picture: what an Agent Harness is, the components that make it up, how to design the backend that supports it, and the optimizations that turn a working system into a production-grade one. Everything here is derived from building DevVoice, a five-agent system that converts GitHub READMEs into platform-native content.

---

## Part 1: The Agent Harness

### What it is

An **Agent Harness** is the infrastructure layer that wraps a language model into a useful system. It is not the model. It is not the prompt. It is the scaffolding that answers every question the model itself cannot:

- Where does work product live between agent steps?
- What context does each agent see, and what is it explicitly excluded from seeing?
- How do agents coordinate without stepping on each other's context windows?
- What happens when an agent produces bad output or a call fails?
- How is cost tracked, bounded, and controlled?

The LLM is a reasoning engine. The harness is the system that makes it useful. Every serious agent deployment is built on one — explicitly designed or accidentally accumulated. The explicit version is faster, cheaper, and easier to debug.

### The five components

A well-designed harness composes five concepts. Each one is a solution to a specific failure mode that emerges when you try to run agents in production.

> **[IMAGE: Overall Architecture — see diagram prompt #1]**

The five components are:

- **Orchestrator** — reads the brief, delegates in sequence, verifies completion, reports done
- **Subagents** — isolated execution contexts, each with one job and one output artifact
- **Skills** — per-agent knowledge documents that define role, output format, and rules
- **Backend** — the shared virtual filesystem where agents pass work product between steps
- **Context Engineering** — the discipline of controlling what each agent sees, when, and in what order

Understanding why each component exists is more useful than memorizing the API. The design decisions that follow from understanding the *why* are the ones that scale.

---

## Part 2: Backends

The backend is the state management layer of the harness. It answers the question every multi-agent system must answer: **where does work product live?**

### The problem with message-passing state

The naive approach is to pass agent outputs through conversation messages. Agent A produces structured insights and returns them. The orchestrator stores the response and passes it to Agent B as message content.

This creates three compounding problems.

**Context bloat.** Every message in the orchestrator's thread costs tokens on every subsequent call. After four agents have run and echoed their outputs back, the orchestrator is carrying thousands of tokens of content that only the next agent will need. You pay for it on every call until the job ends.

**No inspection surface.** There is no way to read what Agent A produced without parsing the orchestrator's conversation history. Debugging means wading through reasoning traces.

**Coupling.** Agent B's behavior depends on the exact format of Agent A's response appearing in the conversation. A format change in A's output schema breaks B. The coupling is invisible until it fails.

### The virtual filesystem

The `StateBackend` solves all three problems by giving every job a virtual filesystem — an in-memory workspace scoped to the duration of the run.

Agents don't pass content to each other through messages. They write files to the workspace and read from it.

> **[IMAGE: Backend / Virtual Filesystem — see diagram prompt #2]**

A typical workspace for a five-agent pipeline looks like this: a `brief.md` seeded at job start (the only input), then one file written per agent — extracted insights, drafts for each platform, and a final review notes file. When the extractor finishes, it writes its output file and confirms in one sentence. The orchestrator stores one line in its thread — not the content. The next agent reads directly from the file when it runs.

This single change reduces the orchestrator's accumulated context by roughly 85% on a five-agent pipeline. It makes every intermediate output inspectable. And it decouples agents from each other — each agent reads a file by path, not a message by position.

### Seeding and result assembly

The workspace starts empty. Before the orchestrator runs, seed it with everything the pipeline needs: skill files, shared context documents, and the per-job brief. Seeding separates the file system setup from the agent's runtime — the workspace is fully defined before the first LLM call is made.

When the pipeline finishes, read the workspace to assemble the structured result. This is the only place where file content is read by the calling code.

**Best practice:** never read workspace content during the pipeline run from the orchestrator's code. The orchestrator infers progress from file existence — which files have appeared — not file content. Content is read exactly once, at the end.

### Progress inference from the workspace

One underappreciated property of the file-based workspace: you can infer pipeline progress from which files exist. No explicit progress callbacks needed in the agent code. The workspace state *is* the progress state.

---

## Part 3: Skills

### What skills are

Every agent has a specific job. The job description — what to produce, what format it should take, what rules to follow — lives in a **Skill file**. Skills are markdown documents loaded into the agent's context alongside its system prompt.

The key design decision is **progressive disclosure**: each agent loads only the skill it needs.

The naive approach is to include all skills for all agents. This is wrong for two reasons.

**Token cost.** Skills are static context loaded on every call. An X writer loading LinkedIn formatting instructions pays for those tokens every time it runs — contributing nothing to the output.

**Focus degradation.** Models occasionally apply instructions from the wrong context. An agent carrying instructions it doesn't need will, with some non-zero probability, produce output influenced by those instructions. The more irrelevant context an agent carries, the worse this gets.

Each agent declares exactly which skill it loads. The skill resolver loads only the matching file. Five agents. Five skills. Each agent sees only its own.

### Tool scoping follows the same principle

Tools are an extension of the skills concept. Like skills, they add tokens (tool definitions count toward input) and add behavioral surface area.

Give agents only the tools they can actually use. The reviewer agent gets a fact-checking tool — it's the only one that verifies external claims. No other agent gets it. A writer that can't call external APIs gets no tools. A tool it can't use is overhead: tokens paid, behavioral risk incurred, no upside.

**Best practice:** the skill and tool set of an agent should be the minimum required to do its specific job. Expand scope only when a specific task demands it.

---

## Part 4: Subagents and Isolated Contexts

### Why shared context windows fail

When you run a multi-agent pipeline in a single conversation thread, every agent accumulates the full history. By the time the reviewer runs, it's carrying the orchestrator's planning reasoning, every writer's output confirmation, and any back-and-forth from corrections. You pay for every one of those tokens. Quality degrades because the reviewer is reasoning in a context full of content that has nothing to do with its job.

### Subagents run in isolation

Each subagent gets a fresh conversation: its own system prompt, its own skill, and only what it explicitly reads from the workspace.

> **[IMAGE: Subagent Isolation — see diagram prompt #3]**

The orchestrator maintains a flat list of agent descriptions. When it decides to delegate, it picks by description. The subagent runs in its own context, does its work, writes to the workspace, and its context is garbage-collected when done.

The cost difference is significant. A five-agent pipeline run entirely in one shared thread accumulates 15,000–30,000 tokens of history by the final step. The same pipeline with isolated subagents keeps each agent's context at 2,000–5,000 tokens. The orchestrator's thread stays lean because it accumulates file paths and one-line confirmations, not content.

**Best practice:** design subagents to have exactly one output artifact in the workspace. One job, one file. This makes progress tracking trivial and outputs inspectable.

---

## Part 5: Context Engineering

Context engineering is the discipline of controlling what enters an agent's context window, when, and in what order. It has more impact on cost and quality than any other engineering decision.

### The static-before-dynamic rule

This is the foundational rule. It must be followed without exception.

**Static content** is anything identical across many requests: system prompts, skill files, tool definitions, shared context documents. **Dynamic content** is anything that changes per request: job IDs, user input, timestamps, per-job parameters.

The correct ordering is: tool definitions first (most stable), then system prompt, then skill files, then conversation history, then the current user message (fully dynamic, never cached).

Provider-level prompt caching stores computed tensor representations of the prefix up to the first dynamic content. A cache read costs 10% of normal input price. A cache miss costs 100%.

Every violation of static-before-dynamic breaks the cache prefix. Common violations: putting a job ID or timestamp in the system prompt, embedding user-specific data in a skill file path, including environment-specific flags in system messages, or changing tool definitions between requests. The fix is always the same — move the dynamic value to the user turn message.

### Durable memory vs. per-job context

Not all context ages the same way.

**Durable memory** is stable across every job: project conventions, behavioral guidelines, how agents should handle edge cases. This lives in a shared document loaded as memory at graph construction time. It gets computed and cached once per worker process.

**Per-job context** is task-specific: the user's README, the requested platforms, the tone. This belongs in a brief document seeded into the workspace at job start — the only dynamic input to the pipeline.

The test for which category a piece of context belongs in: would it be identical across 1,000 different jobs? If yes, it's durable memory. If it changes per job, it belongs in the brief and should never appear in the system prompt.

### Thread compaction

For long-running pipelines, conversation threads grow. Older turns are less relevant than recent turns but still cost tokens on every subsequent call.

Thread summarization middleware handles this automatically. When the thread exceeds a configurable token threshold, older turns are compacted into a summary paragraph. The last N messages stay verbatim — recent context is the most relevant.

**Best practice:** don't set the summarization threshold too low. Summarizing at 80% of context capacity gives the agent room to work without constantly compacting. Summarizing at 40% wastes tokens on summary overhead.

---

## Part 6: The Orchestrator

### Coordination, not execution

The orchestrator's role is exactly one thing: **read the brief, delegate in sequence, verify completion, report done**.

It explicitly does not produce content. This is a hard architectural constraint, not a guideline.

The orchestrator has the broadest context in the system. If it starts reasoning about domain-specific tasks — writing content, making factual judgments, formatting outputs — it will produce adequate results at the cost of long reasoning traces filling its context window, confusion between its coordination role and the domain role it just assumed, and bypassing the quality controls that subagents implement. Any time the orchestrator is tempted to produce domain-specific output, a subagent is missing from the design.

### Build once, reuse always

The orchestrator's construction is expensive: loading skill files from disk, initializing the model client, compiling the graph. Cache it at the process level. Build once per worker, reuse across every job.

A worker processing 40 jobs per hour builds the graph once and reuses it 40 times. A module-level singleton is Python's simplest and most reliable pattern here.

### Enforcing pipeline invariants in the prompt

The orchestrator's system prompt is where pipeline rules are codified: only generate platforms listed in the brief, always run verification last, pass the job ID explicitly to every subagent, never write draft files directly, confirm file existence before reporting done.

These are coordination rules, not hints. Make them explicit and direct. The orchestrator's prompt should read like a technical runbook, not a creative brief.

---

## Part 7: The Caching Stack

Caching in agent systems has more leverage than in traditional applications because you can avoid work at multiple levels. Each level has different cost savings, different hit rates, and different implementation complexity.

> **[IMAGE: Three-Layer Caching Stack — see diagram prompt #4]**

### Layer 1: Provider prompt caching

Anthropic's prompt cache stores computed KV tensor representations of the stable prompt prefix. Subsequent requests with identical prefixes read from cache at **10% of normal input token price** — a 90% discount.

The prerequisite is strict adherence to the static-before-dynamic ordering. Cache control is applied transparently on every system message — the call site doesn't change.

Critical constraints engineers miss: the minimum token threshold is 1,024 tokens. Content below this fails to cache silently — no error, no warning, just a cache miss and full-price billing. Tool definition changes invalidate the entire cache hierarchy. You get at most four cache breakpoints per request.

### Layer 2: Redis LLM response cache

Prompt caching reduces token cost but doesn't eliminate API latency — you still make an HTTP call and wait for a response. A Redis response cache operates upstream of the API entirely: a cache hit means no HTTP call, no latency, zero cost.

Every LLM call in the system — orchestrator and all subagents — automatically checks Redis before making any API call. The cache key is a hash of the full serialized message list combined with the model configuration. Including the model configuration in the key means a model upgrade creates new keys automatically.

**Version your keys on prompt changes.** Without versioning, a broken prompt gets cached and served for hours. A version bump at deploy time flushes the entire cache without touching Redis directly.

**TTL by environment:** Development at 5 minutes (prompt edits visible immediately), Staging at 1 hour (stable enough to catch regressions), Production at 24 hours (maximize cost savings).

### Layer 3: Content identity cache

For systems where the same source material recurs — popular open-source repos submitted by different users, documents processed multiple times — a content-identity cache can eliminate the most expensive pipeline step entirely.

Hash the raw source content. The same document with different user-specified parameters hashes to the same key because the source content is identical. This cache operates on content identity, not prompt identity. It bypasses the LLM entirely on a hit: no API call, no tokens, no latency. TTL can be much longer — seven days is reasonable for most content.

**Cost profile with all layers active:**

| Scenario | Approximate cost |
|----------|-----------------|
| First request, cold caches | $0.18–0.22 |
| Same request, prompt cache only | $0.04–0.06 |
| Same request, response cache hit | $0.00 |
| Different request, extraction cache hit | $0.02–0.04 |

---

## Part 8: Token Optimization

Tokens are the cost unit of LLM systems. Every inefficiency compounds across every user, every request, every retry.

### Estimate before you execute

Never run a job without estimating its token cost first. A rough estimator uses character count divided by four (a reliable approximation for English text) plus fixed overhead for skills and context files. Log this for every job. After a week of production traffic you have real P50/P95 data — the numbers that let you set alert thresholds with confidence instead of guesswork.

### Validate and truncate at the boundary

Validate input size before the job enters the queue. When input is oversized, truncate rather than reject — users with large inputs should still get results, just from the most information-dense portion of their content.

Snap truncation to a structural boundary (paragraph break, section heading) so the model doesn't receive mid-sentence content. Append a truncation marker so the model knows the document is incomplete.

### Model routing by task

Not every agent in your pipeline needs the most capable (and expensive) model. Structured extraction from a markdown document is something a smaller model handles well. Multi-document cross-referencing with judgment calls benefits from stronger reasoning.

Route cheaper models to extraction, classification, and format validation. Reserve capable models for final review and complex multi-step reasoning. Done correctly, this reduces total pipeline cost by 40–60% with no quality reduction on the overall output.

---

## Part 9: The Async Job Architecture

### Why you need a job queue

Agent pipelines take 45–120 seconds for non-trivial work. HTTP connections timeout in 30 seconds by default. Even if they don't, holding a connection open per active job is a poor use of resources.

The correct architecture: accept the request immediately, return a job ID, run the pipeline asynchronously. The client polls for status. The result is written to a fast store the moment the worker completes. Total overhead for the poll loop: milliseconds.

> **[IMAGE: Async Job Architecture — see diagram prompt #5]**

### Celery for LLM workloads

LLM tasks are I/O-bound, not CPU-bound. A worker thread spends most of its time waiting for API responses. This means you can run far more concurrency than CPU cores. The `gevent` pool uses cooperative multitasking — threads yield during I/O waits, allowing other tasks to run. A 4-core machine running 32 concurrent LLM jobs is reasonable when each job spends 70–80% of its time waiting for API responses.

### The dual-store pattern

Redis is fast but ephemeral. Postgres is durable but slower. Use both for different purposes.

| Store | Holds | TTL |
|-------|-------|-----|
| Redis | Job status, current step, result | 2 hours |
| Postgres | Full job record, payload, result, audit trail | Permanent |

Redis handles the real-time polling use case — clients check status every few seconds and need sub-millisecond responses. Postgres handles the historical use case — user job history, billing, debugging jobs from yesterday.

The write pattern: write to both on every state change. The read pattern: check Redis first, fall back to Postgres if the key has expired. Never make Redis your source of truth. TTL expiration is silent.

---

## Part 10: Development Workflow

### Local model first, cloud model for validation

Separate development iteration from cost by building your harness to accept any LangChain-compatible model. Use a local Ollama model during development — free, fast, no API key needed.

Local output is lower quality than frontier models. It is good enough to verify that files are written to the correct workspace paths, the orchestrator delegates in the correct sequence, result assembly parses workspace files into the expected structure, and error handling works as designed.

When a skill file change needs quality validation, flip to the cloud provider for a single test run. Switch back immediately. This separation makes the iteration cycle for prompt and skill development essentially free.

### Testing the harness, not the model

Unit tests for an agent harness should test harness behavior, not model output. The model is non-deterministic; the harness is not.

What to test: workspace seeding produces the expected file structure, result assembly correctly reads each file type, token estimation returns correct totals for known inputs, truncation snaps to paragraph boundaries correctly, cache key generation is deterministic, and state transitions follow the defined valid transition map.

What not to test at the unit level: whether the model produces good content. That's integration testing with a real model, run periodically, not on every commit.

---

## Part 11: Observability

Observability in LLM systems is harder than in traditional systems because the most important failure mode — qualitative degradation — is invisible without the right tooling. A slow API call shows up in latency metrics. An agent that produces subtly wrong content doesn't.

### Structured logs

Every log line should be machine-parseable. Consistent field names across all log lines — job ID, status, step, elapsed time, whether the response was cached — means you can grep, filter, and aggregate across your entire log history without a structured logging system. With this format, extracting P95 latency is a shell one-liner against your log file.

### LLM call tracing

Structured logs give you job-level visibility. A tracing layer gives you call-level visibility: the full prompt, the response, actual token counts, per-call latency broken down by time-to-first-token and generation time, and the complete call tree across orchestrator and subagents.

When a user reports wrong output, you open the trace for their job ID and see exactly what prompt produced the problem. Without this, debugging hallucinations or incorrect agent behavior is guesswork.

### Cache hit rate as a cost signal

Track cache performance explicitly. A sudden drop in LLM response cache hit rate is a signal that a prompt changed — which usually means a dynamic value leaked into a previously static section, a model was upgraded, or a skill file was accidentally modified. Alert on this. It's a cost event that's easy to miss until the billing cycle closes.

---

## Summary: Design Principles

Every decision in this guide comes from one of five principles.

**Minimize accumulated context.** Agents that carry less context are cheaper, faster, and more focused. Every component — the workspace backend, subagent isolation, thread compaction — serves this principle.

**Static before dynamic, always.** Prompt caching is the highest-ROI optimization in a deployed agent system. It requires static content to come before dynamic content in every prompt, without exception.

**Scope knowledge to role.** Agents should know exactly what they need to do their job. Skills, tools, and context files should be narrowed to the minimum. Unnecessary context costs tokens and degrades focus.

**Separate concerns cleanly.** Orchestrators coordinate. Subagents execute. Backends hold state. These roles should not overlap. When they do, debugging becomes significantly harder.

**Estimate, validate, and bound before spending.** Token costs compound. Input validation, pre-execution estimation, and hard ceilings prevent runaway spend from becoming a production incident.

The infrastructure described here is not glamorous. None of it shows up in a demo. All of it is the difference between an agent that works on your laptop and a system that serves real users reliably.

---

## Closing Thoughts

There is a version of AI agent development where you build a demo, film it looking great, and ship. A lot of what's published about agents is written from that perspective — optimized for the moment the model says something impressive.

This guide is written from the other perspective: the one where you have real users, real costs, and a system that has to work at 3am when you're not watching it.

The harness is what makes that possible. Not because it's clever, but because it's explicit. Every failure mode documented here — context bloat, cache-busting prompts, cold-start latency, runaway token costs, qualitative drift invisible to metrics — exists in every agent system. In an undesigned system they show up as incidents. In a designed one they show up as handled edge cases.

The five components don't solve interesting AI problems. They solve boring infrastructure problems. The boring problems are the ones that kill production systems.

If you're building something on top of LLMs that has to work for real people: design the harness first. Get the workspace pattern right before you write a single skill file. Get the cache ordering right before you worry about model selection. Get the job queue right before you tune the orchestrator prompt.

The model is the easy part. It was always the easy part.

---

*If you found this useful, I write about building production AI systems — the engineering, the tradeoffs, and the things that don't make it into the demos. Follow along for the next one.*

---

**Further reading:**

- [Externalization in LLM Agents: Memory, Skills, Protocols and Harness Engineering (arXiv 2604.08224)](https://arxiv.org/pdf/2604.08224)
- [Prompt Caching — Anthropic API Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Don't Break the Cache: Prompt Caching for Long-Horizon Agentic Tasks (arXiv 2601.06007)](https://arxiv.org/pdf/2601.06007)
- [Optimizing Sequential Multi-Step Tasks with Parallel LLM Agents (arXiv 2507.08944)](https://arxiv.org/pdf/2507.08944)
- [Context Window Overflow — Redis Blog](https://redis.io/blog/context-window-overflow/)
- [Taming the AI Inference Queue: Redis, Celery & RabbitMQ at Scale](https://medium.com/@ramadnsyh/taming-the-ai-inference-queue-redis-celery-rabbitmq-at-scale-84798bb21beb)

---

---

# Image Generation Prompts

---

## Diagram 1 — Overall Agent Harness Architecture

**Place in article:** After "The five components" section in Part 1.

**Prompt:**

> A clean, modern technical architecture diagram on a dark navy (#0D1117) background. Title at top: "Agent Harness". Five labeled rectangular components arranged in a clear layout: "Orchestrator" in the center-top (teal accent, slightly larger), connected by directional arrows to "Subagents" on the right, "Skills" on the far right, "Backend" on the lower left, and "Context Engineering" on the lower right. Each box has a one-line subtitle in smaller gray text: Orchestrator = "coordinates, never executes"; Subagents = "isolated contexts, one job each"; Skills = "per-agent knowledge files"; Backend = "shared virtual filesystem"; Context Engineering = "what agents see, when, in what order". Arrows show data flow direction. Color palette: dark navy background, white text, teal (#00B4D8) for component borders, soft gray connectors. Minimal, professional, no gradients, no clipart. Style: engineering whitepaper diagram.

---

## Diagram 2 — Backend / Virtual Filesystem

**Place in article:** After "The virtual filesystem" section in Part 2.

**Prompt:**

> A clean technical diagram on a dark background (#0D1117) illustrating a virtual filesystem workspace for a generic multi-agent pipeline. Left column shows three agent nodes stacked vertically — "Agent 1", "Agent 2", "Agent 3" — each in a rounded rectangle with a teal border. Right column shows a vertical file tree panel labeled "/workspace/job_id/" containing four indented file rows: input.md, output_1.md, output_2.md, review.md. Each file row has a small file icon. Arrows from each agent point to specific files — Agent 1 writes output_1.md; Agent 2 reads output_1.md and writes output_2.md; Agent 3 reads output_1.md and output_2.md and writes review.md. Write arrows are solid teal. Read arrows are dashed gray. A text callout at bottom reads: "Agents coordinate via files, not messages." Dark navy background, white text, clean sans-serif font. Flat design, no shadows, no gradients.

---

## Diagram 3 — Subagent Isolation

**Place in article:** After "Subagents run in isolation" in Part 4.

**Prompt:**

> A side-by-side comparison diagram on a dark navy background showing two approaches to multi-agent context. Left panel labeled "❌ Shared Thread" shows a single large conversation box with five generic labels stacked inside — "Orchestrator", "Agent 1", "Agent 2", "Agent 3", "Agent 4" — all sharing one box, with a cumulative token counter at the bottom showing "~25,000 tokens". The box has a red border. Right panel labeled "✓ Isolated Contexts" shows an "Orchestrator" box at top connected by thin arrows to four small separate boxes below labeled "Agent 1", "Agent 2", "Agent 3", "Agent 4", each with its own small token counter showing "~3,000 tokens". Right panel has a teal border. A cost annotation between the panels reads "5–10x cost difference." Clean flat design, white text, dark background, teal and red accent colors, no gradients, professional technical style.

---

## Diagram 4 — Three-Layer Caching Stack

**Place in article:** At the start of Part 7, before Layer 1.

**Prompt:**

> A vertical layered diagram on a dark navy background showing three stacked horizontal bands representing a generic LLM caching stack, top to bottom. Top band (lightest teal): "Layer 1 — Provider Prompt Cache" with subtitle "90% discount on static prefix tokens" and a small label "10% of input cost on hit". Middle band (medium teal): "Layer 2 — Response Cache (Redis)" with subtitle "Zero API calls on hit — full latency eliminated" and label "0 tokens, 0 latency". Bottom band (dark teal/blue): "Layer 3 — Content Identity Cache" with subtitle "Same input? Skip the most expensive step" and label "Bypasses LLM entirely". A vertical arrow on the left side points downward labeled "Hit Rate" with values decreasing top to bottom. A vertical arrow on the right points upward labeled "Cost Savings" increasing bottom to top. Small cost annotations on the right: "Cold: $0.20", "L1 hit: $0.05", "L2 hit: $0.00", "L3 hit: $0.02". Clean, flat, minimal design. Professional engineering diagram style.

---

## Diagram 5 — Async Job Architecture

**Place in article:** After "Why you need a job queue" in Part 9.

**Prompt:**

> A horizontal flow diagram on a dark navy background showing a generic async agent job pipeline from left to right. Six labeled nodes connected by arrows: (1) "Client" (browser icon) → POST /jobs → (2) "API Server" (server icon, returns job_id immediately, annotated "< 100ms") → enqueues → (3) "Job Queue" (queue icon, teal) → dispatches → (4) "Worker" (gear icon, annotated "runs agent pipeline, 45–120s") → writes result to → (5a) "Fast Store" (lightning bolt icon, labeled "Redis — real-time polling, short TTL") and (5b) "Durable Store" (database icon, labeled "Postgres — permanent audit trail"). A dashed return arrow from Fast Store back to Client labeled "GET /jobs/{id} — polling". All component labels are generic — no product names. White text, teal accent arrows, flat icon style, no gradients, clean professional look.

---

## Diagram 6 — Development Workflow

**Place in article:** After "Local model first, cloud model for validation" in Part 10.

**Prompt:**

> A two-phase horizontal workflow diagram on a dark navy (#0D1117) background. Title at top: "Development → Production". Left phase box labeled "Development" with a warm amber border: contains three stacked items — "Local Model" (laptop icon, labeled "free, instant, no API key"), "Harness Behavior Tests" (checkmark icon, labeled "file paths, delegation order, assembly"), "Skill Iteration" (edit icon, labeled "prompt changes cost nothing"). Right phase box labeled "Production" with a teal border: contains three stacked items — "Cloud Model" (cloud icon, labeled "quality validation"), "Integration Tests" (test tube icon, labeled "run periodically, not on every commit"), "Provider Swap" (swap arrows icon, labeled "one env var change"). A large horizontal arrow between the two boxes labeled "flip MODEL_PROVIDER". Below both boxes, a shared band labeled "Same harness code — zero changes between phases". Dark background, white text, amber (#F59E0B) for dev phase, teal (#00B4D8) for prod phase, flat design, no gradients, clean professional style.

---

## Diagram 7 — Observability Stack

**Place in article:** After "Structured logs" in Part 11.

**Prompt:**

> A vertical three-layer observability stack diagram on a dark navy (#0D1117) background. Title at top: "Observability Stack". Three horizontal layers stacked top to bottom, each a distinct panel. Top layer labeled "Job-Level Logs" (terminal icon, lightest teal border): shows a sample structured log line with consistent fields — job_id, status, elapsed, step — and a note "greppable, parseable, no tooling needed". Middle layer labeled "LLM Call Traces" (hierarchy/tree icon, medium teal border): shows a small call tree — "Orchestrator" branching to "Agent 1 → LLM Call", "Agent 2 → LLM Call → Tool Call" — with annotations "full prompt + response", "actual token counts", "per-call latency". Bottom layer labeled "Cache Hit Rate Monitor" (graph icon, dark teal border): shows a simple line chart with a sudden dip and a red alert marker, annotated "hit rate drop = prompt changed or model upgraded — check before billing cycle closes". White text, teal accent colors, flat design, no gradients, professional engineering diagram style.

---

## Thumbnail — Article Cover (5:2 aspect ratio)

**Dimensions:** 1500 × 600 px (or any 5:2 ratio)

**Place:** Substack cover image / article header.

**Prompt:**

> A bold, graphic cover image at 5:2 aspect ratio (1500×600px). Dark near-black background (#0A0F1A). Layout: left two-thirds is pure typography, right one-third is a minimal abstract graphic.
>
> **Typography (left side):**
> Top-left corner: small all-caps label in teal (#00B4D8) monospace font — "ENGINEERING GUIDE". Below it, the main title in two lines of heavy white sans-serif (weight 800+): "THE AGENT" on line one, "HARNESS" on line two — "HARNESS" is slightly larger, filling its line edge to edge. Below the title, a single short subtitle line in light gray (#94A3B8), regular weight: "Build multi-agent LLM systems that actually work in production." Bottom-left: a thin teal horizontal rule, then two small tags in teal pill badges: "Backends" · "Caching" · "Context Engineering".
>
> **Graphic (right side):**
> A minimal node-graph illustration using only dots and lines — five circular nodes arranged loosely, connected by thin teal lines, suggesting an agent pipeline. The central node is slightly larger and brighter (pure white). Outer nodes are dimmer (muted teal/gray). A very subtle radial glow behind the central node in deep teal, low opacity. No labels on the nodes. The graph bleeds softly off the right edge.
>
> **Style:** Bold editorial graphic design. Graffiti-influenced typography weight (thick strokes, strong contrast) but clean and digital. No gradients on text. No clip art, no illustrations, no photos. The overall feel is a high-end engineering publication cover — the kind that gets shared on X/LinkedIn by developers. Color palette strictly: #0A0F1A background, #FFFFFF primary text, #00B4D8 teal accents, #94A3B8 secondary text.
