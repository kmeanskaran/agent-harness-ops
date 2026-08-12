# AWS Deployment Guide

This documents how to move the current Docker Compose stack — `app` (FastAPI),
`worker` (Celery), `postgres`, `redis`, `frontend` — onto AWS. It covers IAM,
ECR, ECS Fargate, RDS, ElastiCache, the Bedrock model provider path with
prompt caching, and whether to keep Celery+Redis or migrate to SQS.

Current stack recap (see [docker-compose.yml](../docker-compose.yml),
[app/config.py](../app/config.py)):
- FastAPI API (`app`) — validates, enqueues jobs, returns `job_id`
- Celery workers (`worker`) — run the agent pipeline, one Redis instance
  serves as broker + result backend + job store + LLM cache
- Postgres — users, projects, jobs, revision chains
- Redis — queue, live status (`app/redis_store.py`), LLM response cache
  (`app/agent/cache.py`)
- Model provider is pluggable (`app/agent/model.py`): Ollama / Groq / OpenAI
  / Anthropic today; Bedrock is a natural addition since it fronts Anthropic
  models with the same prompt-caching semantics already wired for the
  `anthropic` provider.

---

## 1. IAM roles

Never bake AWS credentials into the image or `.env`. Every AWS-facing
capability should come from an IAM role attached to the ECS task, not static
keys.

### Two roles per ECS service, not one

- **Task execution role** — used by the ECS agent *before* your code runs:
  pulling the image from ECR, writing container logs to CloudWatch, fetching
  secrets to inject as env vars.
- **Task role** — assumed by your application code at runtime: calling
  Bedrock, reading/writing S3, talking to RDS/ElastiCache (network only, not
  IAM-authenticated), publishing to SQS.

```
ExecutionRole (agent-harness-execution-role)
  - AmazonECSTaskExecutionRolePolicy (managed)
  - ecr:GetAuthorizationToken / BatchGetImage / GetDownloadUrlForLayer
  - logs:CreateLogStream / PutLogEvents
  - secretsmanager:GetSecretValue  (scoped to this app's secret ARNs only)

TaskRole (agent-harness-task-role)      <- attached to app + worker tasks
  - bedrock:InvokeModel / InvokeModelWithResponseStream
      Resource: arn:aws:bedrock:*::foundation-model/anthropic.claude-*
  - sqs:SendMessage / ReceiveMessage / DeleteMessage / GetQueueAttributes
      Resource: arn:aws:sqs:<region>:<acct>:agent-harness-*
  - (optional) s3:GetObject/PutObject if artifacts move to S3
```

Key points:
- Scope every policy to specific ARNs (queue names, model IDs, secret names)
  — never `Resource: "*"` for a service role.
- The **worker** task role needs Bedrock + SQS; the **app** (API) task role
  typically only needs SQS `SendMessage` (it enqueues, it doesn't consume
  model calls directly) — give it a narrower policy than the worker.
- RDS and ElastiCache access is controlled by **security groups**, not IAM,
  unless you turn on IAM database authentication for Postgres (optional,
  adds a `rds-db:connect` permission and swaps the password for a signed
  token — worth it if you want to drop `DATABASE_URL`'s embedded password
  from Secrets Manager entirely).
- Local dev keeps using `.env` / `AWS_PROFILE`; only the deployed tasks use
  roles. Don't try to unify these — it's the same pattern the app already
  uses for pluggable model providers (env var picks the path).

---

## 2. ECR

One repository per image (`agent-harness-api` — the app and worker share the
same image today per the [Dockerfile](../Dockerfile), so one repo covers
both; only the container `command` differs).

```bash
aws ecr create-repository --repository-name agent-harness-api \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256

aws ecr get-login-password --region <region> | \
  docker login --username AWS --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com

docker build -t agent-harness-api .
docker tag agent-harness-api:latest <acct>.dkr.ecr.<region>.amazonaws.com/agent-harness-api:latest
docker push <acct>.dkr.ecr.<region>.amazonaws.com/agent-harness-api:latest
```

- Enable `scanOnPush` — free vulnerability scanning on every push.
- Set a lifecycle policy to expire untagged images after N days so the repo
  doesn't grow unbounded from CI builds.
- Tag by git SHA (`:$(git rev-parse --short HEAD)`), not just `:latest` —
  ECS task definitions should pin an explicit tag so rollbacks are a
  one-line task-def revision change, not a rebuild.

---

## 3. ECS Fargate

Two services from one task definition family, same pattern as compose's
`app` + `worker`:

| ECS Service      | Container command                                        | Scaling signal |
|-------------------|-----------------------------------------------------------|-----------------|
| `agent-harness-api`    | `uvicorn main:app --host 0.0.0.0 --port 8000`         | ALB request count / CPU |
| `agent-harness-worker` | `celery -A app.worker.celery_app worker --loglevel=info` | SQS/Redis queue depth (custom CloudWatch metric) |

Why two services instead of one: the API needs to be behind an ALB with a
stable, low task count; the worker is CPU/IO-bound on LLM calls and should
scale on **queue depth**, which Fargate doesn't expose natively — publish a
custom CloudWatch metric (queue length) and scale on that, or use
Application Auto Scaling with an SQS `ApproximateNumberOfMessagesVisible`
alarm if you migrate to SQS (see §6).

Task definition essentials:
- `executionRoleArn` / `taskRoleArn` from §1.
- Secrets (`DATABASE_URL`, `ANTHROPIC_API_KEY`, `REDIS_URL` if not using
  IAM/VPC-only access) injected via `secrets`, not `environment` — point at
  Secrets Manager ARNs, resolved at task start by the execution role.
- Health check for the API container should hit `/health`
  ([app/routes/health.py](../app/routes/health.py)) — same endpoint compose
  already uses.
- Put both services in **private subnets**, reach the internet (Bedrock,
  Anthropic/Groq/OpenAI APIs, Langfuse) via a NAT gateway. Only the ALB sits
  in public subnets.
- The frontend runs as a third ECS Fargate service — see §4 below. It keeps
  the existing nginx container as-is, so it slots into the same task
  definition / ALB / private-subnet pattern as `agent-harness-api` and
  `agent-harness-worker` above, rather than a different AWS service.

---

## 4. Frontend: ECS Fargate (reusing the existing nginx container)

The sibling `agent-harness-frontend` repo already builds a self-contained
image ([Dockerfile](../../agent-harness-frontend/Dockerfile),
[nginx.conf](../../agent-harness-frontend/nginx.conf)): `vite build` →
static output in `dist/`, served by nginx inside the container. On AWS,
that image runs unchanged as a third ECS service — no new AWS service to
learn, no rewrite of the nginx/Railway setup, just the same
build-a-container-run-it-on-Fargate pattern already used for `api` and
`worker`.

| ECS Service | Container command | Scaling signal |
|---|---|---|
| `agent-harness-frontend` | nginx, per existing `Dockerfile`/`nginx.conf` | ALB request count / CPU |

Setup shape:

- **Own ECR repo** (or a path in the same repo, tagged separately) — build
  and push `agent-harness-frontend` the same way as §2, from the
  `agent-harness-frontend` repo's own `Dockerfile`.
- **Same ALB as the API**, different routing rule: path-based
  (`/api/*` → API target group, everything else → frontend target group) or
  host-based (`api.yourdomain.com` → API, `app.yourdomain.com` → frontend) —
  host-based is usually cleaner for a SPA + API split since it avoids the
  SPA's client-side router fighting with ALB path rules.
- **nginx keeps proxying `/api`** internally to the API service if you go
  path-based and want same-origin requests from the browser (no CORS
  headers needed on FastAPI in that case) — nginx's `proxy_pass` just points
  at the ALB's internal DNS name or the API target group instead of a
  Docker Compose service name. If you go host-based instead, the browser
  calls `api.yourdomain.com` directly and you do need `CORSMiddleware`
  (§8) since it's now a cross-origin request.
- **Private subnet**, same as `api`/`worker` — the ALB is the only public
  entry point for all three services.
- No S3, CloudFront, or ACM-in-us-east-1 complexity to deal with — TLS
  termination happens once, at the ALB, shared across all three services.

Task definition essentials mirror §3: `executionRoleArn` pulls the image
from ECR and writes logs; this service doesn't need a `taskRoleArn` with
any AWS permissions (`bedrock:*` / `sqs:*` above) since nginx never calls
AWS APIs directly — give it the execution role only, no task role, or an
empty one if your tooling requires setting both.

---

## 5. RDS (Postgres)

Replaces the `postgres` compose service.

- Engine: PostgreSQL 16 (matches `postgres:16-alpine` in compose).
- Start with `db.t4g.micro`/`small` (Graviton, cheaper) — this workload
  (users, projects, jobs, revision chains) is metadata-light, not analytical.
- Multi-AZ only once this is genuinely production-critical; it roughly
  doubles RDS cost for automatic failover. Single-AZ + automated daily
  snapshots is a reasonable starting point.
- Put RDS in the same private subnets as the ECS tasks; security group
  allows inbound 5432 **only** from the ECS tasks' security group, not
  0.0.0.0/0 or even the whole VPC CIDR.
- Rotate credentials via Secrets Manager's native RDS rotation, or switch to
  IAM database auth (see §1) to remove the password from secrets entirely.
- `DATABASE_URL` env var format doesn't change — same
  `postgresql://user:pass@host:5432/db` shape the app already expects.

---

## 5. ElastiCache (Redis)

Replaces the `redis` compose service, but **audit its three jobs first**
before assuming a lift-and-shift:

1. Celery broker + result backend
2. Job/status store (`app/redis_store.py`) with a 2h TTL, no persistence
   needed
3. LLM response cache (`app/agent/cache.py`), 24h TTL

All three are fine on the same ElastiCache cluster since they're
namespaced by key prefix (`jobs:`, `llmcache:`) and none need cross-region
replication. Recommendations:

- **Engine**: ElastiCache for Redis (or Valkey, AWS's Redis fork, now the
  default engine option) — either works, nothing here uses Redis
  Enterprise-only features.
- **Node type**: `cache.t4g.small` to start; this is a queue + cache, not a
  primary datastore, so you don't need large memory unless job volume or
  cache hit rates justify it.
- **Cluster mode disabled** (single shard, with a replica for failover) is
  simplest and matches current usage — nothing here shards keys across
  nodes deliberately, and Celery's Redis transport doesn't support Redis
  Cluster hashtag-free key patterns cleanly.
- **Persistence**: not required. If the broker restarts, in-flight Celery
  messages are lost — acceptable if the API can re-enqueue on user-visible
  failure, worth deciding explicitly rather than defaulting.
- Security group: inbound 6379 only from ECS tasks, same pattern as RDS.
- **This is also exactly where the SQS tradeoff decision lives** — see §6.

---

## 6. SQS vs. Celery+Redis — the actual tradeoff

You already have Celery running on Redis as broker. The question is whether
to replace that transport with SQS (keeping Celery as the worker framework,
just swapping `redis://` for `sqs://` as the broker URL) or keep Redis.

### Keep Celery + Redis (ElastiCache)

**Pros**
- Zero code change — `celery -A app.worker.celery_app worker` and
  `app/redis_store.py` already assume Redis; SQS as a *broker* still leaves
  the job-status store and LLM cache on Redis anyway, so you'd run both
  services regardless.
- Full Celery feature set: `chain`/`group`/`chord` for multi-step agent
  pipelines (orchestrator → extractor → writers → reviewer, per your
  README), task revocation, rate limiting, `retry` with backoff, priority
  queues — SQS's Celery broker support is a thinner subset of these.
- Lower latency: Redis round-trip is sub-millisecond in-VPC; SQS is a
  managed HTTP API, tens of milliseconds per call, and Celery's SQS
  transport polls rather than gets push notifications, adding latency to
  task pickup.
- One less moving piece: Redis is already required for the job store and
  LLM cache, so removing it from the broker role doesn't remove the
  service, it just adds SQS alongside it.

**Cons**
- You own the ops: ElastiCache failover, backups (or explicit acceptance of
  none), and Celery's Redis broker has known sharp edges — messages can be
  redelivered on worker crash without `visibility_timeout` tuning, and long
  Redis outages can wedge the broker in a way SQS wouldn't.
- Scaling the worker fleet on "queue depth" requires you to build the
  CloudWatch metric yourself (poll `LLEN` on the Celery queue key and
  publish it) — SQS gives you `ApproximateNumberOfMessagesVisible` as a
  first-class CloudWatch metric for free, which plugs directly into
  Application Auto Scaling target-tracking.

### Migrate broker to SQS

**Pros**
- Fully managed, no capacity planning, virtually unlimited throughput,
  99.9%+ durability SLA — messages survive broker "restarts" because there's
  no broker to restart.
- Free-tier-friendly at low volume; scales to zero cost when idle (unlike an
  always-on ElastiCache node).
- Native CloudWatch queue-depth metric → trivial Fargate worker autoscaling
  policy, which matters here since worker scaling on LLM-call-bound queue
  depth is exactly the signal you want (§3).
- Dead-letter queue (DLQ) is a checkbox, not something you build — useful
  for a pipeline where a bad job (malformed README, hallucination loop, tool
  failure) should land somewhere inspectable instead of retrying forever.

**Cons**
- Celery's SQS transport (`kombu`) doesn't support `chord`/`group` result
  aggregation the way Redis does — if the reviewer stage needs to fan-in
  results from the 3 parallel writer subagents (X/LinkedIn/article, per your
  README), that pattern is meaningfully harder or requires restructuring
  around SQS-native fan-out + a separate results store (which you already
  have in Postgres/Redis, so it's a re-plumbing job, not a blocker).
- You still need Redis anyway for `app/redis_store.py` (live status,
  polled every 2s per your README) and `app/agent/cache.py` (LLM cache) —
  so SQS doesn't let you drop ElastiCache, it adds a second queueing system
  alongside it. Net infrastructure goes *up*, not down.
- FIFO ordering and exactly-once delivery cost more (FIFO queues) and cap
  throughput at 300–3000 msg/s per queue vs. Redis's effectively
  unbounded local throughput — irrelevant at this app's likely volume, but
  worth knowing.
- SQS message size cap is 256KB; large agent payloads (long READMEs,
  accumulated context) may need to go through S3 with SQS holding a
  pointer — an indirection Redis doesn't force on you.

### Recommendation

For this codebase specifically: **keep Celery + Redis on ElastiCache.**
The pipeline's fan-in/fan-out shape (orchestrator → 3 parallel writers →
reviewer) leans on Celery primitives that SQS supports poorly, and Redis is
already load-bearing for the job store and LLM cache regardless — so moving
the broker to SQS adds a second system without removing the first. Revisit
SQS only if: (a) job volume grows enough that ElastiCache ops burden (HA,
failover, capacity) becomes real work, or (b) you want autoscaling driven by
a first-class queue-depth metric badly enough to restructure the fan-in
logic around S3/Postgres instead of Celery `chord`.

If you do want SQS's autoscaling signal *without* the migration, the
middle path is: keep Celery/Redis as the broker, but publish your own
`LLEN`-derived CloudWatch metric for the worker's Application Auto Scaling
policy. That gets you the scaling benefit with none of the `chord`/DLQ
tradeoffs above.

---

## 7. Bedrock ecosystem + prompt caching

`app/agent/model.py` already has a provider abstraction
(`MODEL_PROVIDER=ollama|groq|openai|anthropic`) with a custom
`_CachingChatAnthropic` class that tags `SystemMessage`s with
`cache_control: {"type": "ephemeral"}` for Anthropic's native prompt
caching. Bedrock is a fifth provider, not a replacement — it's how you'd run
Claude models inside AWS with IAM auth instead of an API key, at the cost of
Bedrock's own quirks.

### Adding a `bedrock` provider

```python
if provider == "bedrock":
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=s.MODEL_NAME or "anthropic.claude-sonnet-4-6-v1:0",
        temperature=s.MODEL_TEMPERATURE,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        # credentials resolved from the ECS task role — no key/secret needed
    )
```

- Auth: no `ANTHROPIC_API_KEY` needed — the ECS task role's
  `bedrock:InvokeModel*` permission (§1) is sufficient. This is the main
  operational win over the direct Anthropic API: no key rotation, no
  secret in Secrets Manager for this provider.
- Model access must be explicitly enabled per-model in the Bedrock console
  ("Model access" page) before the first `InvokeModel` call — a one-time
  per-account/per-region step, easy to forget and the resulting error
  (`AccessDeniedException`) looks like an IAM problem, not a Bedrock
  console problem.

### Prompt caching on Bedrock

Bedrock supports Anthropic's prompt caching, but it is **not** automatic the
way the direct Anthropic API is becoming — you still need explicit
`cachePoint` blocks in the request, same idea as the existing
`_mark_system_cached` helper, just a different wire format
(`{"cachePoint": {"type": "default"}}` instead of
`{"cache_control": {"type": "ephemeral"}}`). `langchain_aws`'s
`ChatBedrockConverse` exposes this via the Converse API's native cache-point
support as of recent versions — worth checking the installed
`langchain-aws` version supports it before assuming parity with the
Anthropic-direct path.

Tradeoffs vs. calling Anthropic directly:
- **Pro**: IAM-based auth (no key management), spend shows up on the AWS
  bill (useful if procurement/finance wants single-vendor billing), data
  stays in-region without crossing to Anthropic's endpoints if that matters
  for compliance.
- **Con**: Bedrock typically trails the direct API by weeks on new model
  releases; cache TTL and minimum cacheable token count can differ from
  Anthropic-direct; Bedrock pricing for cached tokens has historically
  lagged the direct API's cache-read discount in some regions — check
  current pricing before assuming parity.
- **Con**: cross-region inference profiles (needed for higher throughput
  quotas) add another ARN/config surface (`us.anthropic.claude-*` style
  inference profile IDs) that the direct API doesn't have.

### Semantic caching vs. the existing exact-match cache

`app/agent/cache.py` is an **exact-match** cache keyed on
`sha256(llm_string + prompt)` — a hit requires the identical prompt string,
so it helps with retries, idempotent re-runs, and repeated identical calls
within the TTL, but does nothing for prompts that are *semantically* similar
but not byte-identical (e.g., two READMEs with the same structure but
different project names).

If you want semantic caching, Bedrock Knowledge Bases don't provide this
directly — you'd add:
- An embedding step (Bedrock Titan Embeddings or Cohere Embed via Bedrock)
  on each incoming prompt.
- A vector store for similarity lookup — OpenSearch Serverless (AWS-native,
  integrates with Bedrock Knowledge Bases) or pgvector on the existing RDS
  Postgres instance (cheaper, no new service, and you already have
  `psycopg` as a dependency).
- A similarity threshold below which you treat it as a cache hit and skip
  the LLM call — this trades a small amount of response staleness/drift for
  a much higher cache-hit rate than exact-match.

Given this app already has Postgres in the stack, **pgvector on RDS** is the
lower-lift path if semantic caching becomes worth building — it avoids
standing up OpenSearch Serverless for what would likely be a
low-cardinality embedding index (cached prompts, not a general knowledge
base). Only worth doing if the exact-match cache's hit rate (visible via
Langfuse traces, which already tag every stage by `job_id`) turns out to be
low enough to matter.

---

## 8. Minimal production-readiness checklist

This is a learning project, not a multi-tenant SaaS — nobody else's data is
at stake. So this section is the **mandatory floor**, not the full
enterprise checklist: the smallest change to each item that stops the app
from actively breaking, leaking, or losing data once it's on a real domain.
Each one maps to a specific gap in the current code.

### Auth

Today, `x-user-email` ([content.py:35](../app/routes/content.py#L35)) is
trusted as identity with no verification — anyone can claim to be anyone.
Minimal fix: a single static API key, checked via a FastAPI dependency.

```python
# app/auth.py
import os, secrets
from fastapi import Header, HTTPException

_API_KEY = os.getenv("API_KEY", "")


def require_api_key(x_api_key: str = Header(...)) -> None:
    if not _API_KEY or not secrets.compare_digest(x_api_key, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
```

Add `dependencies=[Depends(require_api_key)]` to the routers in
[content.py](../app/routes/content.py) and [result.py](../app/routes/result.py)
(leave `/health` open). `API_KEY` comes from Secrets Manager, one value,
rotated by hand if it ever leaks. That's it — no user table, no OAuth, no
JWT for a project nobody but you is hitting.

### Rate limiter

`slowapi`'s in-memory store ([main.py:24](../main.py#L24)) only limits per
ECS task — with 2+ tasks the effective limit multiplies. Minimal fix: point
it at the Redis you already run.

```python
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=get_settings().REDIS_URL,
    default_limits=["10/minute"],
)
```

One line changed, same `slowapi` dependency, no new service.

### CORS

No `CORSMiddleware` exists today; it works only because nginx proxies
same-origin. Once the frontend and API sit on separate subdomains
(`app.yourdomain.com` / `api.yourdomain.com`, §9), this breaks. Minimal fix:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

One explicit origin from an env var — not `["*"]`, since credentials/API
keys are involved.

### Versioned DB migrations

[db.py](../app/db.py)'s `CREATE TABLE IF NOT EXISTS` list has no path for
changing an existing column without touching prod data by hand. Minimal
fix: add Alembic, generate one baseline migration from the current schema,
and run `alembic upgrade head` as an ECS one-off task (or an init container)
before the API/worker start — not inside `startup()`, so a bad migration
fails the deploy instead of half-starting the app.

### Logging collection

`logging.getLogger(__name__)` is called throughout but nothing calls
`logging.basicConfig(...)` ([main.py](../main.py) never sets a level), so
most `logger.info`/`.debug` calls are silently dropped. Minimal fix: one
call at startup —

```python
logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
```

On Fargate, anything written to stdout/stderr is already picked up by the
`awslogs` log driver into CloudWatch Logs automatically — no agent, no
extra infra, just set the log group/stream prefix in the task definition.

### Job data durability

Redis job records TTL out after `JOB_TTL_SECONDS` (2h,
[redis_store.py](../app/redis_store.py)) by design — that's fine for live
status polling. The thing to actually verify: `result_json` and `error` are
written to the `jobs` table in Postgres ([db.py](../app/db.py)) on **every**
terminal state (success *and* failure), not just the happy path — check
[app/worker/tasks.py](../app/worker/tasks.py) wraps the pipeline in
try/except and always persists to Postgres before Redis can expire.
Postgres is already the durable copy; nothing new to stand up.

### CloudWatch

Minimal, not full observability: rely on the `awslogs` driver (logging,
above) for logs, plus **two** alarms — ECS service `RunningTaskCount < desired`
(task keeps crashing) and RDS `FreeStorageSpace` below a threshold (disk
fills silently otherwise). Both are a handful of `aws_cloudwatch_metric_alarm`
resources in Terraform. Skip dashboards, custom metrics, and distributed
tracing — Langfuse already covers LLM-pipeline observability.

### DLQ

Without one, a poison job (bad README, tool crash) retries per Celery's
default policy and then either loops or vanishes with no record. Minimal
fix if staying on Celery+Redis (§6 recommends this): set an explicit
`task_annotations` retry cap in `celery_app.py` (e.g. `max_retries=3`) and
catch-all in [tasks.py](../app/worker/tasks.py) to write `status="failed"`
and `error` to Postgres on final failure — Postgres *is* your DLQ, you
don't need SQS's for a single-worker learning project. Only add a real SQS
DLQ if you actually migrate the broker to SQS.

### Backup

RDS: turn on automated backups with a short retention (`backup_retention_period
= 3` days is enough for a personal project) — one Terraform argument on the
`aws_db_instance` resource, no separate service. ElastiCache and the Redis
job store are explicitly disposable (§5) — don't back those up, that's the
point of them being a cache.

### Guardrails (cost)

One AWS Budget with an email alert at a fixed dollar threshold
(`aws_budgets_budget`, a few lines of Terraform) is the mandatory floor —
Bedrock/Anthropic + Fargate + RDS can run up a bill unattended if a bug
causes a retry storm. That's the whole ask for a learning project: get
notified before it's a surprise, not a full FinOps setup.

### Multi-env separation

You don't need separate AWS accounts for a solo learning project — that's
overkill. Minimal separation: one Terraform **workspace** (or a `dev`/`prod`
variable + `.tfvars` file) per environment, each with its own state file
(different S3 key, same bucket) and its own `.env`-equivalent in Secrets
Manager (`agent-harness/dev/*` vs `agent-harness/prod/*`). That's enough to
stop a `terraform apply` meant for dev from touching the domain that's
actually live.

---

## 9. Suggested rollout order

1. ECR repo + IAM roles (execution + task) — no running infra yet, just the
   permission surface.
2. RDS + ElastiCache in private subnets, security groups locked to
   (not-yet-existing) ECS tasks' SG. Enable RDS automated backups here.
3. ECS Fargate `api` service behind an ALB, pointed at the new RDS/Redis —
   validate `/health` and one end-to-end job before touching the worker.
   Apply the auth/CORS/rate-limiter/logging changes from §8 before this
   goes anywhere near a public domain.
4. ECS Fargate `worker` service, same task role plus Bedrock/SQS
   permissions as needed. Wire the DLQ/retry-cap behavior from §8.
5. Cut the frontend over (S3+CloudFront or its own Fargate service) once
   the ALB is routing `/api` correctly.
6. Wire the two CloudWatch alarms and the budget alarm from §8.
7. Only then evaluate Bedrock provider / semantic caching / SQS migration —
   these are optimizations on a working deployment, not prerequisites for
   one.
