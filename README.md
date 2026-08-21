# DevVoice on AWS — Agent Harness, deployed

> **You are on the `aws-deployment` branch.** This branch is about one thing:
> running the DevVoice agent harness on AWS as real infrastructure — ECS Fargate,
> RDS, ElastiCache, ALB, Bedrock — described in Terraform and deployed by GitHub
> Actions on push. For the application-only story (agents, prompts, local dev),
> see `master`.

Two isolated environments (`dev`, `prod`) from one codebase via Terraform
**workspaces**. No AWS keys anywhere: CI authenticates with GitHub OIDC, and the
app authenticates to Bedrock with its ECS task role — so there is no model API
key stored in the cluster either.

> **This is a POC.** Both workspaces are sized identically (smallest everything,
> single node, no HA) and both are built to be destroyed on demand. `prod` here
> means "a second isolated stack", not "hardened and durable". The knobs to
> restore for a real production environment are listed at the top of
> [terraform/locals.tf](terraform/locals.tf).

## The application, in one paragraph

DevVoice turns a GitHub README into a reviewed X thread, LinkedIn post, and
dev.to article. Five specialized agents (extract → write → review) keep every
claim grounded in the source, and a human approves before anything is final.
FastAPI takes the request and enqueues it; a Celery worker runs the DeepAgents
pipeline; Postgres holds users, jobs, and revision chains; Redis holds live job
state and the LLM response cache; a React + nginx frontend is the workspace.
That is the thing being deployed below.

---

## Architecture on AWS

```text
                          Internet
                             │
                    ┌────────▼────────┐
                    │  ALB (public)   │  HTTP :80 → frontend target group
                    └────────┬────────┘
              ┌──────────────▼───────────────┐
              │  VPC — 2 AZs, public subnets  │  IGW, no NAT
              │                              │
              │  ┌────────────────────────┐  │
              │  │ frontend (Fargate)     │  │  React + nginx
              │  │   nginx /api/* ────────┼──┼──┐
              │  └────────────────────────┘  │  │  Cloud Map DNS
              │  ┌────────────────────────┐  │  │  api.agent-harness-<env>.local:8000
              │  │ api (Fargate) ◄────────┼──┼──┘
              │  │   FastAPI :8000        │  │
              │  └───────┬────────┬───────┘  │
              │          │ enqueue│          │
              │  ┌───────▼────────▼───────┐  │
              │  │ worker (Fargate)       │──┼──► Bedrock (task role, no API key)
              │  │   Celery + DeepAgents  │  │
              │  └───────┬────────┬───────┘  │
              │          │        │          │
              │   ┌──────▼──┐  ┌──▼───────┐  │
              │   │ RDS PG  │  │ Redis    │  │  t4g.micro each
              │   └─────────┘  └──────────┘  │
              └──────────────────────────────┘
                             │
        CloudWatch logs (7d) · error alarm → SNS email · monthly budget alarm
```

**Why the ALB only knows about the frontend:** nginx already proxies `/api/*` to
the backend (stripping the prefix), exactly as it does in `docker compose`. The
ALB forwards everything to the frontend and nginx reaches the API internally over
Cloud Map. Same origin ⇒ no CORS, one target group, one listener.

**Model access:** `MODEL_PROVIDER=bedrock`, `MODEL_NAME=zai.glm-4.7` — a
tool-calling model, which matters (see the long note in
[terraform/variables.tf](terraform/variables.tf) for which models fail and why).
The task role mints a short-term bearer token at runtime, so no model API key is
stored anywhere.

### What Terraform creates

| File | Resources |
| --- | --- |
| [network.tf](terraform/network.tf) | VPC, IGW, 2 public subnets, route table (no NAT — saves ~$32/mo) |
| [security.tf](terraform/security.tf) | Security groups: alb, ecs, rds, redis |
| [alb.tf](terraform/alb.tf) | Public ALB, HTTP listener, frontend target group |
| [ecs.tf](terraform/ecs.tf) | Cluster, Cloud Map namespace, 3 task definitions + services |
| [rds.tf](terraform/rds.tf) | Postgres `db.t4g.micro`, generated password |
| [elasticache.tf](terraform/elasticache.tf) | Redis `cache.t4g.micro`, 1 node |
| [ecr.tf](terraform/ecr.tf) | 2 repos (api, frontend), lifecycle policies, `force_delete` |
| [iam.tf](terraform/iam.tf) | Execution role (pull images, read secrets) + task role (Bedrock invoke) |
| [secrets.tf](terraform/secrets.tf) | Secrets Manager; `DATABASE_URL` fully managed, rest placeholder-then-set |
| [logs.tf](terraform/logs.tf) | One CloudWatch log group per service, 7-day retention |
| [monitoring.tf](terraform/monitoring.tf) | ERROR metric filters, worker alarm → SNS, monthly budget alarm |
| [locals.tf](terraform/locals.tf) | Per-workspace sizing — the one place to change CPU/memory/counts |
| [bootstrap/](terraform/bootstrap/) | State bucket, lock table, GitHub OIDC provider, deploy role |

State lives in S3 with a DynamoDB lock table; both workspaces share the bucket,
namespaced under `env:/<workspace>/<key>`.

---

## Deploy

Prerequisites: an AWS account with Bedrock model access enabled, the AWS CLI
configured (profile `mgmt` by default — override with `profile=`), Terraform
≥ 1.5, and push access to this repo on GitHub.

```bash
make aws-setup                # once per account — bootstrap + init, prints what GitHub needs
git push origin aws-deployment          # deploys dev
git tag prod-2026-08-22 && git push --tags   # promotes to prod (pauses for approval)
make aws-url                  # live URL + health check
make aws-destroy              # stop the meter (add only=prod to scope it)
```

Everything after `make aws-setup` is driven by git:

```text
push to aws-deployment   →  checks  →  build images  →  terraform apply  →  dev
push tag prod-*          →  checks  →  build images  →  ⏸ approval  →  prod
pull request             →  checks only
```

Checks are pre-commit (ruff, `terraform fmt`, secret scan) · `terraform validate`
· pytest · a `docker compose` smoke test that boots the real stack and asserts
the nginx `/api` proxy works — the same wiring the ALB depends on.

### GitHub setup (once)

`make aws-setup` prints the three values GitHub needs. Two are **variables**
(Settings → Secrets and variables → Actions → Variables):

| Name | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | the role ARN printed by `make aws-setup` |
| `AWS_REGION` | `us-east-1` |

One is a **secret**:

| Name | Value |
| --- | --- |
| `BUDGET_EMAIL` | address for AWS budget + error alerts |

Then Settings → **Environments**: create `dev` (no rules) and `prod` with
yourself as a **required reviewer** — that reviewer *is* the approval gate. An
environment with no protection rule does not pause; it looks identical in the
workflow file and runs straight through.

`BUDGET_EMAIL` is required and `var.budget_email` has no default, deliberately:
this repo is public and the address is a real inbox, so it is supplied at apply
time rather than committed. Without it the deploy fails at the `ecr` job, before
`deploy` runs (a `-target`ed apply still evaluates every variable). For local
applies, `export TF_VAR_budget_email=you@example.com`. Teardown is exempt —
`destroy-all.sh` supplies a placeholder, so a missing value can never block you
from stopping the meter.

### After the first apply

Terraform creates three secrets with `REPLACE_ME` placeholders and then stops
managing their values (`ignore_changes`), so setting them by hand sticks:

```bash
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_SECRET_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_PUBLIC_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/TAVILY_API_KEY      --secret-string '...'
```

Push again to roll the tasks onto the new values. And **confirm the SNS
subscription email**, or the error alerts you just configured are never
delivered.

Full guide — every step, every flag, every failure mode:
**[terraform/README.md](terraform/README.md)**.

---

## Operating it

All targets take `env=dev|prod` (default `dev`) and `profile=` (default `mgmt`).

| Command | What it does |
| --- | --- |
| `make aws-url` | Print the live URL and check `/` and `/api/health` |
| `make aws-status` | Task counts per service + the latest ECS event (where crash reasons appear) |
| `make aws-logs s=worker` | Live-tail one service (`s=api\|worker\|frontend`) |
| `make aws-errors` | ERRORs from all three services in the last 30 minutes |
| `make aws-arn` | Reprint the deploy role ARN without applying |
| `make aws-destroy` | Destroy the app stacks, keep the state backend |
| `make aws-nuke` | Destroy everything including the state backend |
| `make aws-verify-clean` | Prove nothing billable is left; exits non-zero if it finds anything |

Logs are structured JSON, one object per line, which is what lets a metric filter
alarm on the `level` field. In CloudWatch Logs Insights:

```sql
-- trace one job end to end
fields @timestamp, event, status, step, elapsed_s
| filter job_id = "<job_id>" | sort @timestamp asc

-- failures with reasons
fields @timestamp, job_id, error_type, error_msg
| filter event = "job_failed" | sort @timestamp desc
```

Alarm: worker logs 3+ `ERROR`s in 5 minutes → SNS email. Budget: monthly alarm at
80% actual / 100% forecast (default $50, `var.budget_limit_usd`). Langfuse still
traces every agent stage by `job_id` if you set its keys.

### Cost

Running 24/7 ≈ **$70–80/mo** per environment: ALB ~$17, RDS `t4g.micro` ~$14,
ElastiCache `t4g.micro` ~$12, three Fargate tasks ~$35, NAT gateway *$0 —
deliberately omitted*. Destroyed between sessions ≈ **$0** (the state bucket and
lock table are effectively free). Bedrock is billed per token, separately.

### Teardown

```bash
make aws-destroy              # dev + prod app stacks, keeps the state backend
make aws-destroy only=prod    # that workspace only, leaving the other running
make aws-nuke                 # ^ plus workspaces, state bucket, lock table
make aws-verify-clean         # confirm nothing billable survived
```

`aws-destroy` deliberately ignores `env=` and defaults to **all** environments —
"stop the meter" must not quietly leave a second stack billing. Narrowing is
opt-in via `only=`. Everything is built to destroy cleanly in both workspaces
(`force_delete` ECR, `skip_final_snapshot` RDS, 0-day secret recovery, no
deletion protection), which is also why there is **no** accidental-destruction
guard on `prod` — restore those knobs before it becomes a real environment.

---

## Running it locally

Still the fastest way to change the app before you deploy it. Note the local
stack uses `MODEL_PROVIDER=ollama` by default; AWS uses `bedrock`.

```bash
cp .env.example .env      # pick a provider, fill only its key
docker compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API + Swagger UI | <http://localhost:8000/docs> |
| PostgreSQL | localhost:5432 (`devvoice`/`devvoice`) |
| Redis | localhost:6379 |

For hot reload, run the pieces directly (`uv sync` first):

```bash
docker compose up postgres redis
uv run celery -A app.worker.celery_app worker --loglevel=info
uv run uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

Smoke test either environment — swap the host for the ALB URL from `make aws-url`:

```bash
curl -X POST http://localhost:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","readme":"# MyProject — uses Redis pub/sub","platforms":["x"]}'
curl http://localhost:8000/result/<job_id>   # poll until awaiting_approval
```

> **Ollama users:** inside containers `localhost` is the container. Set
> `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`.

### API reference

| Endpoint | Purpose |
| --- | --- |
| `POST /generate` | Enqueue generation for one or more platforms (`x`, `linkedin`, `devto`) |
| `GET /result/{job_id}` | Poll status, current step, and results |
| `POST /revise/{job_id}` | Create a revision (child job) with an instruction |
| `POST /approve/{job_id}` | Approve an `awaiting_approval` job |
| `GET /history/{email}` | All jobs for a user, grouped by project |
| `GET /health` | Service health (`/api/health` through the ALB) |

Statuses: `queued → running → extracting → writing → reviewing → awaiting_approval → completed` (or `failed`).
Behind the ALB every path is prefixed `/api`.

---

## Repository layout

```text
agent-harness-ops/
├── terraform/                   ← the deployment (start at terraform/README.md)
│   ├── *.tf                     VPC, ALB, ECS, RDS, ElastiCache, IAM, secrets, monitoring
│   ├── bootstrap/               state bucket, lock table, OIDC deploy role (applied once)
│   └── destroy-all.sh           teardown across both workspaces
├── .github/workflows/ci.yml     checks → ECR → build → apply → smoke test
├── scripts/aws-setup.sh         one-command bootstrap + init
├── scripts/aws-verify-clean.sh  proves nothing billable survived
├── Makefile                     the aws-* targets above
├── main.py                      FastAPI entry point
├── app/
│   ├── agent/                   orchestrator + 5 subagents, provider factory (incl. Bedrock)
│   ├── skills/*/SKILL.md        per-agent instructions
│   ├── routes/ · worker/        API surface · Celery tasks
│   └── db.py · redis_store.py   Postgres layer · live job state
├── frontend/                    React SPA + nginx (proxies /api → the API)
└── docs/                        architecture deep-dive, AWS write-ups, diagrams
```

## Branch & contribution notes

This branch carries the infrastructure; `master` carries the application. Deploys
happen from `aws-deployment` and from `prod-*` tags — nothing else triggers an
apply. When you touch Python dependencies, edit `pyproject.toml`, run `uv lock`,
and commit both; CI's dependency test fails otherwise.

Before pushing:

- [ ] `.env` is not staged (it's gitignored — keep it that way)
- [ ] No real keys in tracked files, and `.env.example` has blank secret values
- [ ] `uv lock --check` passes
- [ ] `terraform fmt -check` and `terraform validate` pass in `terraform/`
- [ ] `docker compose up --build` boots and `GET /health` returns OK

## Troubleshooting

| Symptom | Where to look |
| --- | --- |
| Deploy job skipped, checks green | `AWS_DEPLOY_ROLE_ARN` variable isn't set — see GitHub setup |
| Service never reaches `services-stable` | `make aws-status` — the ECS event line carries the real reason |
| ALB returns 502 | Frontend is up but nginx can't reach the API — `make aws-logs s=api`, check Cloud Map registration |
| Jobs run but produce empty drafts | `MODEL_NAME` doesn't emit tool calls — see the note in `terraform/variables.tf` |
| `terraform apply` blocked on a state lock | A cancelled apply stranded the lock: `terraform force-unlock <id>` |
| Bedrock `INVALID_PAYMENT_INSTRUMENT` | Marketplace-subscription models need a payment method; GLM/Kimi/DeepSeek don't |
| No alert emails | The SNS subscription was never confirmed — check the inbox from the first apply |
| Worker never picks up jobs (local) | Is Redis up? `uv run celery -A app.worker.celery_app inspect ping` |

## License

[MIT](LICENSE) © Karan Shingde
