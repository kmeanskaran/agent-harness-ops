# agent-harness — AWS dev deployment (Terraform)

ECS Fargate stack for the DevVoice app. One codebase, two environments via
Terraform **workspaces** (`dev`, `prod`).

**This is a POC.** Both workspaces are sized identically (smallest everything,
single node, no HA) and both are built to be destroyed on demand — `prod` here
means "a second isolated stack", not "hardened and durable". The knobs to
restore for a real production environment are listed at the top of `locals.tf`.

**Architecture (both workspaces):** public subnets + IGW (no NAT) · RDS Postgres t4g.micro ·
ElastiCache Redis t4g.micro · public ALB (HTTP) · 3 Fargate services
(api, worker, frontend) · Cloud Map for the `/api` proxy · Secrets Manager ·
CloudWatch logs (7d) + error alarm · monthly budget alarm.

Model: **Gemma on Bedrock** (`google.gemma-4-e2b`) — the ECS **task role** mints a
short-term bearer token at runtime, so **no model API key is stored anywhere**.

---

## Deploy

Deployment is driven by git. `.github/workflows/ci.yml` runs the checks and then
deploys — there is exactly **one** command you ever run locally, and only once.

### Step 1 — bootstrap (local, once per AWS account)

Creates the Terraform state bucket, the lock table, and the GitHub OIDC deploy
role. It has to be local: GitHub cannot authenticate to AWS until the role it
assumes exists.

```bash
export AWS_PROFILE=mgmt
cd bootstrap
terraform init
terraform apply -var="aws_profile=mgmt"
terraform output github_deploy_role_arn
```

### Step 2 — GitHub setup (once)

Settings → Secrets and variables → Actions → **Variables**:

| Name | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | the output from step 1 |
| `AWS_REGION` | `us-east-1` |

Settings → **Environments**: create `dev` (no rules) and `prod` (add yourself as
a **required reviewer**).

No GitHub *secrets* are needed — auth is OIDC, and app secrets live in AWS
Secrets Manager.

### Step 3 — deploy dev: just push

```bash
git push origin aws-deployment
```

Checks run (pre-commit, terraform validate, pytest, compose smoke test). If they
all pass, the pipeline creates ECR repos if missing, builds both images, applies
Terraform, rolls the ECS services, waits for `services-stable`, and curls
`/api/health` through the ALB. The run summary prints the live URL.

Every later push to `aws-deployment` repeats this. Terraform is declarative, so
a push with no infra change only rolls new images.

### Step 4 — promote dev → prod: tag the commit

```bash
git tag prod-2026-08-12
git push origin prod-2026-08-12
```

Same pipeline, `prod` workspace, same commit SHA so the images are identical.
The deploy job **pauses for approval** — the `prod` Environment's required
reviewer — and you approve it in the Actions tab.

### Step 5 — real secret values (once per environment)

Terraform creates the secrets with `REPLACE_ME` placeholders:

```bash
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_SECRET_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_PUBLIC_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/TAVILY_API_KEY     --secret-string '...'
```

Then push again (or re-run the workflow) to roll the tasks onto the new values.

Confirm the **SNS subscription email** after the first apply, or error alerts
won't be delivered.

---

## Logs & monitoring

Structured JSON, one object per line (see `app/logging_config.py`).

```bash
aws logs tail /ecs/agent-harness-dev/worker --follow      # live tail
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

Alarm: worker logs 3+ `ERROR`s in 5 minutes → SNS email.

---

## Destroy (stop the meter)

**Both environments, one command:**

```bash
./destroy-all.sh            # destroys the dev + prod stacks, keeps state backend
./destroy-all.sh --nuke     # ^ plus workspaces, state bucket, lock table
```

It prompts for confirmation, skips workspaces that don't exist, and — under
`--nuke` — empties every object *version* from the state bucket first, which is
required because the bucket is versioned and `bootstrap` sets
`force_destroy = false`. Running `cd bootstrap && terraform destroy` on its own
fails with `BucketNotEmpty` for exactly that reason.

Single environment, by hand — `terraform destroy` is **workspace-scoped**, so it
can only affect the selected environment:

```bash
terraform workspace select dev
terraform destroy                    # the whole app stack
```

Faster restarts — kill only the expensive resources, keep VPC/ECR/IAM:

```bash
terraform destroy \
  -target=aws_ecs_service.api \
  -target=aws_ecs_service.worker \
  -target=aws_ecs_service.frontend \
  -target=aws_db_instance.postgres \
  -target=aws_elasticache_replication_group.main \
  -target=aws_lb.main
```

**Both workspaces are built to destroy cleanly** (`force_delete` ECR,
`skip_final_snapshot` RDS, no final snapshot left behind, 0-day secret recovery,
no deletion protection). Nothing survives a destroy and keeps billing.

The trade-off is deliberate and POC-only: there is **no** accidental-destruction
guard on `prod`. Before this becomes a real environment, restore
`deletion_protection`, `skip_final_snapshot = false`, and ECR
`force_delete = false` for the `prod` workspace.

---

## Cost

Running 24/7 ≈ **$70–80/mo** (ALB ~$17, RDS ~$14, Redis ~$12, 3 Fargate tasks
~$35). Destroyed between test sessions ≈ **$0**. The NAT gateway (~$32/mo) is
deliberately omitted in dev.
