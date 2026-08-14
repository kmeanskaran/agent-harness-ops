# fix_dev — the dev environment does not generate content

**Status:** open · **Environment:** `dev` (AWS account `585662413932`, us-east-1)
**Opened:** 2026-08-14

The AWS dev stack deploys, runs, and passes every health check. It has **never
produced a piece of content.** Four separate bugs sit between "deployed" and
"working"; three are fixed, the fourth is open and is the reason this document
exists.

Nothing here is an infrastructure failure. ECS, RDS, ElastiCache, the ALB and
the nginx `/api` proxy all behave correctly. The stack faithfully runs an agent
that cannot complete its task.

---

## Current state

| | |
| --- | --- |
| Live URL | http://agent-harness-dev-alb-146865370.us-east-1.elb.amazonaws.com |
| `/api/health` | `{"status":"ok","redis":true}` |
| ECS services | api, worker, frontend — all 1/1, task definition **rev 7** |
| `MODEL_NAME` | `deepseek.v3.2` |
| Successful generations | **0** |
| Cost | ~$70–80/mo while running |
| prod | **not deployed** — deliberately parked until dev produces one real post |

---

## Why health checks did not catch this

Worth stating plainly, because it shaped the whole debugging session: every
check the pipeline runs passed on a completely broken app.

`/api/health` proves the API is up and can reach Redis. The ALB check proves
nginx serves the frontend. Neither touches Bedrock, the Celery worker, or the
agent. The post-deploy smoke test in `ci.yml` curls `/api/health` and stops
there.

**The only test that detects any of the four bugs below is submitting a real job
and asserting the returned content is non-empty.** Everything else is green
while the product does nothing.

---

## Bug 1 — Gemma cannot call tools (FIXED, `ffc4ee8`)

**Symptom.** Job `17fa720dc2f7` "succeeded" in 10 seconds. The API returned
`status: awaiting_approval` and `linkedin_post: ""`. The UI rendered a blank
post. Nothing errored anywhere — Bedrock returned 200, Celery logged `job_done`.

**Cause.** The orchestrator is a DeepAgents graph that does all its work through
tools; every draft is written with `write_file`. `google.gemma-3-12b-it` does not
emit structured tool calls on Bedrock. It replies in Google's own
` ```tool_code ` dialect and AWS never wrote the Converse adapter for it, so the
call arrives as **plain assistant text** with `stopReason: end_turn`. LangGraph
had nothing to dispatch, ended the graph after one turn, and no files were
written. `assemble_result` then read draft files that never existed and returned
empty strings.

**What made it silent.** Bedrock *accepts* a `toolConfig` for Gemma without any
validation error. Nothing in the request or response says "this model cannot use
tools."

**Verification.** Both `gemma-3-12b-it` and `gemma-3-27b-it` behave this way, so
it is a missing adapter and not a model-size limit. Prompting cannot work around
it — an explicit *"you must use the write_file tool"* still returned
`end_turn`. Every other open-weights family on Bedrock returns a real `toolUse`
block:

| Model | Tool calling |
| --- | --- |
| `google.gemma-3-12b-it` | ❌ text only, `end_turn` |
| `google.gemma-3-27b-it` | ❌ text only, `end_turn` |
| `deepseek.v3.2` | ✅ `tool_use` |
| `qwen.qwen3-32b-v1:0` | ✅ `tool_use` |
| `openai.gpt-oss-120b-1:0` | ✅ `tool_use` |
| `zai.glm-4.7` | ✅ `tool_use` |
| `minimax.minimax-m2.5` | ✅ `tool_use` |
| `moonshotai.kimi-k2.5` | ✅ `tool_use` |
| `nvidia.nemotron-super-3-120b` | ✅ `tool_use` |
| `mistral.mistral-large-3-675b-instruct` | ✅ `tool_use` |
| `mistral.ministral-3-8b-instruct` | ✅ `tool_use` |
| `meta.llama3-70b-instruct-v1:0` | ⚠️ `ValidationException` |
| `us.anthropic.claude-sonnet-4-6` | ❌ `INVALID_PAYMENT_INSTRUMENT` |

**Fix.** `MODEL_NAME` → `deepseek.v3.2` in `terraform/variables.tf`.

**Also fixed: the silence itself.** `assemble_result` now raises
`EmptyGenerationError` when every requested platform comes back empty, so this
class of failure can never again be stored as a successful blank post. Partial
output is deliberately left alone. The pre-existing test
`test_missing_draft_files_do_not_raise` asserted the old silent behaviour and was
replaced by its inverse.

---

## Bug 2 — the task role could not invoke the new model (FIXED, `14f3900`)

**Symptom.** Job `158894765a29` failed in 2.7s:

```
AccessDeniedException: assumed-role/agent-harness-dev-task is not authorized to
perform: bedrock:InvokeModel on resource: .../foundation-model/deepseek.v3.2
```

**Cause.** The task role's Bedrock policy allowed exactly two hardcoded families,
`anthropic.claude-*` and `google.gemma-*`. Nothing tied the IAM grant to
`MODEL_NAME`, so changing the model silently created a permissions mismatch.

**Fix.** `terraform/iam.tf` now derives an `InvokeConfiguredModel` statement from
`var.model_name`, so the grant follows the configured model by construction.
Both ARN shapes are covered, because an id can name a foundation model
(`deepseek.v3.2`) or a cross-region inference profile
(`us.anthropic.claude-sonnet-4-6` — which additionally needs invoke rights on the
underlying foundation model, hence stripping the `us.`/`eu.`/`apac.` prefix).

Adding a `deepseek.*` wildcard would have fixed the day and left the same trap
for the next model switch.

**Note.** This failure mode was *correct*: it raised, the worker logged
`job_failed` with the reason, and the job did not land as a blank success. This
is what bug 1's guard buys.

---

## Bug 3 — Langfuse ruled out (FIXED, `702e680`)

Langfuse's keys were `REPLACE_ME`, so it was never reporting anywhere useful
while still adding network calls and failure surface to jobs that were already
dying. It was disabled to remove it as a variable.

Rather than commenting out ~17 call sites — decorators stacked under
`@celery_app.task`, several multi-line `update_current_trace(...)` blocks, all in
code paths that only execute in the deployed worker — every call site was left
exactly as written and only the imports changed. `app/observability.py` supplies
no-op stand-ins for `Langfuse`, `langfuse_context` and `observe`.

`observe()` returns the decorated function **completely unwrapped**, because it
sits under `@celery_app.task`; a wrapper would change what Celery registers and
hide `.delay`.

**Re-enabling** is one uncommented import per module — procedure in the
`app/observability.py` docstring. The dependency stays in `pyproject.toml`.

**Result: this was not the cause.** The loop below is unchanged.

---

## Bug 4 — the agent loops without delegating (OPEN)

This is the live issue.

### What should happen

The orchestrator is told explicitly not to write content itself. It delegates,
in order, and each subagent saves its output as a file in the job workspace:

1. `extractor` → `extracted_insights.md`
2. `linkedin-writer` → `linkedin_draft.md`
3. `content-reviewer` → `review_notes.md`

`assemble_result` then reads `linkedin_draft.md` and that text becomes the post.

### What actually happens

The orchestrator never completes a handoff. It calls the model dozens of times
and **not one file is ever created**, so the extractor never produces insights,
the writer has nothing to write from, and there is no draft.

Progress reporting is inferred from which files exist
(`app/agent/orchestrator.py`), which is why the status sits on `orchestrator`
forever — the run never leaves stage one.

### Evidence across two runs

| Job | Outcome | Converse calls | Files written |
| --- | --- | --- | --- |
| `4d2784f0a82c` | `GraphRecursionError: Recursion limit of 100 reached` | ~50 | none |
| `6bbecee6a716` | **still `running` 15+ min later, then silent** | ~90 | none |

The recursion limit is a safety valve, not the disease — LangGraph counts
model→tool→model round trips and gives up at 100 on the assumption that anything
taking that many turns is circling rather than progressing.

The second run is arguably worse: it went round ~90 times, produced **zero log
lines for 5+ minutes**, and is still marked `running`. At least the recursion
limit reported something.

### What we know vs. what we do not

**Known:** the model *can* call tools (this is real progress over Gemma — bug 1
is genuinely fixed), but it cannot hold a multi-step delegation together.

**Not known:** precisely why it circles. CloudWatch records *that* a model call
happened, not *which* tool was requested or what came back. The likely
candidates — it mangles the subagent request, or it gets a result and does not
recognise it as done and asks again — cannot be distinguished from the logs we
have.

This is the visibility gap. Managing a team of subagents across dozens of turns
is a far harder capability than emitting one tool call, and this pipeline was
designed around Claude Sonnet, which is blocked by the Marketplace payment
issue.

---

## Supporting gap — a hung job never dies

`app/worker/celery_app.py` sets **no `task_time_limit` and no
`task_soft_time_limit`**. A hung job holds a worker slot forever; nothing will
kill it. With `task_acks_late=True`, restarting the worker redelivers the task,
which can then hang again.

Job `6bbecee6a716` is currently in exactly this state — one of two concurrency
slots permanently consumed, UI showing `running` indefinitely with no path to
failure.

Worth fixing regardless of which model is chosen. It is the difference between
"a job failed" and "the worker silently degrades."

---

## How to reproduce

```bash
export AWS_PROFILE=mgmt
URL=http://agent-harness-dev-alb-146865370.us-east-1.elb.amazonaws.com

curl -sS -X POST "$URL/api/generate" \
  -H 'Content-Type: application/json' \
  -H 'x-user-email: you@example.com' \
  -d '{"email":"you@example.com","readme":"# Test\n\nSome project description.",
       "learnings":["a"],"hard_parts":["b"],
       "tone":"honest and practical","audience":"intermediate developers",
       "platforms":["linkedin"]}'

curl -sS "$URL/api/result/<job_id>"          # watch status / linkedin_post
make aws-logs env=dev profile=mgmt s=worker  # follow the worker
```

Failure signature: `status` stays `running` with `current_step: orchestrator`,
`linkedin_post` stays `""`, and the worker logs repeated
`Using Bedrock Converse API to generate response` with no `job_progress` events
beyond the first.

---

## Options

**A. Switch to a model trained for agentic loops.** `moonshotai.kimi-k2.5` or
`zai.glm-4.7` — both verified `tool_use` in this account, both built for long
tool-calling loops. One line in `terraform/variables.tf` plus a push. Cheapest
thing left to try, but if it also loops we are still blind.

**B. Get tool-level visibility.** Re-enable Langfuse with real keys, or run the
pipeline locally where the agent loop prints to stdout. A local repro iterates in
seconds instead of a ~6 minute deploy cycle. This is what actually answers *why*.

**C. Unblock Claude.** Put a valid payment instrument on the account and switch
to `us.anthropic.claude-sonnet-4-6`. This pipeline was designed around Sonnet and
is most likely to work as-authored. Re-verified 2026-08-14: still
`INVALID_PAYMENT_INSTRUMENT`.

**D. Add the Celery timeout** regardless of A–C, so hangs fail loudly.

Recommended: **D + A together**, then **B** if the loop persists.

---

## Do not promote to prod yet

`prod` is a **second full stack**, not a promotion of dev — its own RDS,
ElastiCache and ALB, roughly **doubling spend to ~$140–160/mo**. Tagging today
would stand that up around a pipeline with no proven working path.

Gate: **one job returning non-empty content in dev.** Then
`git tag prod-YYYY-MM-DD && git push origin <tag>`.

---

## Commands

```bash
export AWS_PROFILE=mgmt
make aws-status  env=dev profile=mgmt          # task counts + events
make aws-url     env=dev profile=mgmt          # URL + health
make aws-logs    env=dev profile=mgmt s=worker # live tail
make aws-errors  env=dev profile=mgmt          # errors, last 30m
make aws-destroy                               # stop the meter
make aws-verify-clean                          # prove nothing is still billing
```

Secrets still unset (`REPLACE_ME`): `TAVILY_API_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_PUBLIC_KEY`. Note `fact_check` in `app/agent/tools.py` guards on the
key being *empty*, and `REPLACE_ME` is truthy — so it would call Tavily with an
invalid key rather than skipping, and `client.search(...)` is uncaught. Latent,
not yet observed to fire.

---

## Commits

| SHA | Change |
| --- | --- |
| `ffc4ee8` | Gemma → DeepSeek; `EmptyGenerationError` guard; tests |
| `14f3900` | Task-role Bedrock grant follows `var.model_name` |
| `702e680` | Langfuse disabled behind no-op shims |
