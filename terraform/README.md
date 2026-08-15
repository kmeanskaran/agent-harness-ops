# AWS Deployment — agent-harness

ECS Fargate infrastructure for the DevVoice agent harness. One codebase, two
isolated environments (`dev`, `prod`) via Terraform **workspaces**, deployed by
GitHub Actions on push. No AWS keys anywhere: CI authenticates with OIDC, and
the app authenticates to Bedrock with the ECS task role.

> **This is a POC.** Both workspaces are sized identically (smallest everything,
> single node, no HA) and both are built to be destroyed on demand. `prod` here
> means "a second isolated stack", not "hardened and durable". The knobs to
> restore for a real production environment are listed at the top of
> [`locals.tf`](locals.tf).

---

## Contents

- [Architecture](#architecture) · [What Terraform creates](#what-terraform-creates)
- [Deploy](#deploy) — [bootstrap](#step-1--bootstrap-local-once-per-aws-account) · [GitHub setup](#step-2--github-setup-once) · [push](#step-3--deploy-dev-just-push) · [promote](#step-4--promote-dev--prod-tag-the-commit) · [secrets](#step-5--set-the-real-secret-values-once-per-environment)
- [Operating it](#operating-it) — [make targets](#make-targets) · [logs & alarms](#logs--alarms)
- [Cost](#cost) · [Teardown](#teardown) · [Troubleshooting](#troubleshooting)

---

## Architecture

```text
                          Internet
                             │
                    ┌────────▼────────┐
                    │  ALB (public)   │  HTTP :80 → frontend target group
                    └────────┬────────┘
              ┌──────────────▼──────────────┐
              │  VPC — 2 AZs, public subnets │  IGW, no NAT
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
the backend (stripping the prefix), exactly as it does in `docker compose`. So
the ALB forwards everything to the frontend and nginx reaches the API internally
over Cloud Map. Same origin ⇒ no CORS, one target group, one listener.

**Model access:** `MODEL_PROVIDER=bedrock`, `MODEL_NAME=zai.glm-4.7` (a
tool-calling model — see the long note in [`variables.tf`](variables.tf) for why
that matters and which models fail). The task role mints a short-term bearer
token at runtime, so **no model API key is stored anywhere**.

### What Terraform creates

| File | Resources |
| --- | --- |
| `network.tf` | VPC, IGW, 2 public subnets, route table (no NAT — saves ~$32/mo) |
| `security.tf` | Security groups: alb, ecs, rds, redis |
| `alb.tf` | Public ALB, HTTP listener, frontend target group |
| `ecs.tf` | Cluster, Cloud Map namespace, 3 task definitions + services (api, worker, frontend) |
| `rds.tf` | Postgres `db.t4g.micro`, generated password |
| `elasticache.tf` | Redis `cache.t4g.micro`, 1 node |
| `ecr.tf` | 2 repos (api, frontend) with lifecycle policies, `force_delete` |
| `iam.tf` | Execution role (pull images, read secrets) + task role (Bedrock invoke) |
| `secrets.tf` | Secrets Manager entries; `DATABASE_URL` fully managed, the rest placeholder-then-set |
| `logs.tf` | One CloudWatch log group per service, 7-day retention |
| `monitoring.tf` | ERROR metric filters, worker-error alarm → SNS email, monthly budget alarm |
| `locals.tf` | Per-workspace sizing — the one place to change CPU/memory/counts |
| `bootstrap/` | State bucket, lock table, GitHub OIDC provider, deploy role (applied by hand, once) |

State lives in S3 (`backend.hcl`) with a DynamoDB lock table. Both workspaces
share the bucket; Terraform namespaces them under `env:/<workspace>/<key>`.

---

## Deploy

Deployment is driven by git. [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
runs the checks and then deploys — there is exactly **one** command you ever run
locally, and only once.

```text
push to aws-deployment   →  checks  →  build images  →  terraform apply  →  dev
push tag prod-*          →  checks  →  build images  →  ⏸ approval  →  prod
pull request             →  checks only
```

Checks: pre-commit (ruff, `terraform fmt`, secret scan) · `terraform validate` ·
pytest · a `docker compose` smoke test that boots the real stack and asserts the
nginx `/api` proxy works — the same wiring the ALB depends on.

### Step 1 — bootstrap (local, once per AWS account)

Creates the Terraform state bucket, the lock table, and the GitHub OIDC deploy
role. It has to be local: GitHub cannot authenticate to AWS until the role it
assumes exists. Idempotent, and the ARN is identical every time.

```bash
make aws-setup                # bootstrap + terraform init + print what GitHub needs
make aws-setup args=--check   # report what exists, change nothing
```

`aws-setup` also runs `terraform init -reconfigure -backend-config=backend.hcl`
against the bucket it just created, so the main config is ready to use locally.
If you only want the bootstrap half:

```bash
make aws-bootstrap            # prints the role ARN to paste into GitHub
make aws-arn                  # print it again later, without applying
```

### Step 2 — GitHub setup (once)

Settings → Secrets and variables → Actions → **Variables**:

| Name | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | the output from step 1 |
| `AWS_REGION` | `us-east-1` |

Settings → Secrets and variables → Actions → **Secrets**:

| Name | Value |
| --- | --- |
| `BUDGET_EMAIL` | address for AWS budget + error alerts |

Settings → **Environments**: create `dev` (no rules) and `prod` (add yourself as
a **required reviewer** — that is the approval gate). Note that an environment
with *no* protection rule does not pause: the `environment: prod` job resolves
and runs straight through, looking identical in the workflow file to a gated one.

**Why `BUDGET_EMAIL` is a secret and the other two are variables.** Variables are
readable by anyone and printed in logs; the role ARN and region are identifiers,
not credentials, so that is fine. The alert address is a real inbox and this repo
is public, so `var.budget_email` deliberately has **no default** — nothing to
leak, and a missing value fails loudly instead of quietly mailing a stale
address. CI passes it as `TF_VAR_budget_email` in both the `ecr` and `deploy`
jobs. Both are needed: a `-target`ed apply still evaluates every variable, so
without it the `ecr` job fails *before* `deploy` ever runs.

Locally, export it before any apply:

```bash
export TF_VAR_budget_email="you@example.com"
```

Teardown is exempt — `destroy-all.sh` supplies a placeholder, so a missing value
can never block you from stopping the meter.

Beyond that, no GitHub secrets are needed: CI auth is OIDC and the app's own
secrets live in AWS Secrets Manager. Until `AWS_DEPLOY_ROLE_ARN` is set the
pipeline runs checks only and stays green.

### Step 3 — deploy dev: just push

```bash
git push origin aws-deployment
```

The pipeline creates the ECR repos if missing, builds both images (tagged with
the commit SHA), applies Terraform, rolls the ECS services, waits for
`services-stable`, and curls `/api/health` through the ALB. The run summary
prints the live URL.

Every later push repeats this. Terraform is declarative, so a push with no infra
change only rolls new images.

### Step 4 — promote dev → prod: tag the commit

```bash
git tag prod-2026-08-16 && git push origin prod-2026-08-16
```

Same pipeline, `prod` workspace, same commit SHA so the images are identical.
The deploy job **pauses for approval** in the Actions tab.

### Step 5 — set the real secret values (once per environment)

Terraform creates three secrets with `REPLACE_ME` placeholders and then stops
managing their values (`ignore_changes`), so setting them by hand sticks:

```bash
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_SECRET_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_PUBLIC_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/TAVILY_API_KEY      --secret-string '...'
```

Then push again (or re-run the workflow) to roll the tasks onto the new values.
Also **confirm the SNS subscription email** after the first apply, or error
alerts won't be delivered.

---

## Operating it

### Make targets

All take `env=dev|prod` (default `dev`) and `profile=` (default `mgmt`).

| Command | What it does |
| --- | --- |
| `make aws-url` | Print the live URL and check `/` and `/api/health` |
| `make aws-status` | Task counts per service + the latest ECS event (where crash reasons appear) |
| `make aws-logs s=worker` | Live-tail one service (`s=api\|worker\|frontend`) |
| `make aws-errors` | ERRORs from all three services in the last 30 minutes |
| `make aws-bootstrap` / `aws-arn` | One-time backend + OIDC role / reprint the ARN |
| `make aws-destroy` | Destroy the app stacks, keep the state backend |
| `make aws-nuke` | Destroy everything including the state backend |
| `make aws-verify-clean` | Prove nothing billable is left; exits non-zero if it finds anything |

### Logs & alarms

Logs are structured JSON, one object per line (`app/logging_config.py`), which
is what lets a metric filter alarm on the `level` field.

```bash
aws logs tail /ecs/agent-harness-dev/worker --follow
aws logs tail /ecs/agent-harness-dev/api --since 10m
```

CloudWatch Logs Insights:

```sql
-- trace one job end to end
fields @timestamp, event, status, step, elapsed_s
| filter job_id = "<job_id>" | sort @timestamp asc

-- failures with reasons
fields @timestamp, job_id, error_type, error_msg
| filter event = "job_failed" | sort @timestamp desc
```

Alarm: worker logs 3+ `ERROR`s in 5 minutes → SNS email. Budget: monthly alarm at
80% actual / 100% forecast (default $50, `var.budget_limit_usd`).

---

## Cost

Running 24/7 ≈ **$70–80/mo** per environment:

| | ~$/mo |
| --- | --- |
| ALB | 17 |
| RDS `t4g.micro` | 14 |
| ElastiCache `t4g.micro` | 12 |
| 3 Fargate tasks | 35 |
| NAT gateway | *0 — deliberately omitted* |

Destroyed between test sessions ≈ **$0** (the state bucket and lock table are
effectively free). Bedrock is billed per token, separately.

---

## Teardown

**Both environments, one command:**

```bash
make aws-destroy              # dev + prod app stacks, keeps the state backend
make aws-destroy only=prod    # that workspace only, leaving the other running
make aws-nuke                 # ^ plus workspaces, state bucket, lock table
make aws-verify-clean         # confirm nothing billable survived
```

`aws-destroy` deliberately ignores `env=` and defaults to **all** environments —
"stop the meter" must not quietly leave a second stack billing. Narrowing is
opt-in via `only=`. `--nuke` always spans both workspaces because it removes the
shared backend; it also empties every object *version* from the state bucket
first, which is why `cd bootstrap && terraform destroy` on its own fails with
`BucketNotEmpty`.

Single environment by hand — `terraform destroy` is **workspace-scoped**, so it
can only affect the selected environment:

```bash
terraform workspace select dev && terraform destroy
```

Faster restarts — kill only the expensive resources, keep VPC/ECR/IAM:

```bash
terraform destroy \
  -target=aws_ecs_service.api -target=aws_ecs_service.worker \
  -target=aws_ecs_service.frontend -target=aws_db_instance.postgres \
  -target=aws_elasticache_replication_group.main -target=aws_lb.main
```

Everything is built to destroy cleanly in **both** workspaces (`force_delete`
ECR, `skip_final_snapshot` RDS, 0-day secret recovery, no deletion protection).
Nothing survives a destroy and keeps billing.

The trade-off is deliberate and POC-only: there is **no** accidental-destruction
guard on `prod`. Before that becomes a real environment, restore
`deletion_protection`, `skip_final_snapshot = false`, and ECR
`force_delete = false` for the `prod` workspace.

---

## Troubleshooting

| Symptom | Where to look |
| --- | --- |
| Deploy job skipped, checks green | `AWS_DEPLOY_ROLE_ARN` variable isn't set — see step 2 |
| Service never reaches `services-stable` | `make aws-status` — the ECS event line carries the real reason (image pull, secret access, health check) |
| ALB returns 502 | Frontend task is up but nginx can't reach the API — check `make aws-logs s=api` and that the api service is registered in Cloud Map |
| Jobs run but produce empty drafts | `MODEL_NAME` doesn't emit tool calls — read the note in `variables.tf`; only tool-calling models work |
| `terraform apply` blocked on a state lock | A cancelled apply stranded the DynamoDB lock: `terraform force-unlock <id>` |
| Bedrock `INVALID_PAYMENT_INSTRUMENT` | Marketplace-subscription models (Anthropic) need a valid payment method on the account; GLM/Kimi/DeepSeek don't |
| No alert emails | The SNS subscription was never confirmed — check the inbox from the first apply |
