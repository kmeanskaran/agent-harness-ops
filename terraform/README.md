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

```bash
export AWS_PROFILE=dev
aws sso login --profile dev          # SSO expires ~12h

# 1. One-time: state backend
cd bootstrap && terraform init && terraform apply && cd ..

# 2. Init + select environment
terraform init
terraform workspace new dev          # later: terraform workspace select dev

# 3. ECR first (images need somewhere to go)
terraform apply -target=aws_ecr_repository.api -target=aws_ecr_repository.frontend

# 4. Build + push images
./push-images.sh dev

# 5. Full apply (pin the tag push-images.sh printed)
terraform apply -var=api_image_tag=<sha> -var=frontend_image_tag=<sha>

# 6. Real secret values (placeholders won't work)
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_SECRET_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/LANGFUSE_PUBLIC_KEY --secret-string '...'
aws secretsmanager put-secret-value --secret-id agent-harness-dev/TAVILY_API_KEY     --secret-string '...'
aws ecs update-service --cluster agent-harness-dev --service agent-harness-dev-api    --force-new-deployment
aws ecs update-service --cluster agent-harness-dev --service agent-harness-dev-worker --force-new-deployment

terraform output app_url             # open in a browser
```

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
