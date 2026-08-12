.PHONY: up down fresh logs restart \
        aws-bootstrap aws-arn \
        aws-logs aws-errors aws-status aws-url \
        aws-destroy aws-nuke aws-verify-clean

# Which deployed environment the aws-* targets talk to. Override per command:
#   make aws-logs s=worker env=prod
env     ?= dev
profile ?= mgmt

# Start all services (uses cache)
up:
	docker compose up --build

# Fresh rebuild — no cache, then start
fresh:
	docker compose down
	docker compose build --no-cache
	docker compose up

# Stop and remove containers
down:
	docker compose down

# Tail logs for all services
logs:
	docker compose logs -f

# Restart a specific service: make restart s=worker
restart:
	docker compose restart $(s)

# --- AWS: bring the account back to life ---

# One-time per AWS account, and again after `make aws-nuke`. Creates the
# Terraform state bucket, the lock table, the GitHub OIDC provider and the
# deploy role — then prints the ARN to paste into GitHub.
#
# This is the ONLY terraform apply you ever run by hand: GitHub cannot
# authenticate to AWS until the role it assumes exists. Everything else (VPC,
# RDS, Redis, ALB, ECS) is created by the pipeline on push.
#
# Safe to re-run — it is idempotent, and the ARN is identical every time because
# the role name and account are fixed, so the GitHub variable never changes.
aws-bootstrap:
	cd terraform/bootstrap && \
	  terraform init -input=false && \
	  terraform apply -auto-approve -input=false -var="aws_profile=$(profile)"
	@echo
	@echo "Paste this into AWS_DEPLOY_ROLE_ARN (Settings > Secrets and variables > Actions > Variables):"
	@echo
	@cd terraform/bootstrap && terraform output -raw github_deploy_role_arn && echo
	@echo
	@echo "  AWS_REGION = us-east-1"
	@echo "  Environments needed: dev (no rules), prod (required reviewer)"
	@echo "  Then: git push origin aws-deployment"

# Print the deploy role ARN again without applying anything.
# `terraform output -raw` warns rather than failing when state is empty, so test
# the value instead of the exit code.
aws-arn:
	@arn=$$({ cd terraform/bootstrap && terraform output -raw github_deploy_role_arn; } 2>/dev/null); \
	case "$$arn" in \
	  arn:aws:iam::*) echo "$$arn" ;; \
	  *) echo "No bootstrap state — run: make aws-bootstrap" ;; \
	esac

# --- AWS: observing the deployed stack ---

# Live-tail one service: make aws-logs s=worker   (s=api|worker|frontend)
aws-logs:
	aws logs tail /ecs/agent-harness-$(env)/$(or $(s),worker) \
	  --follow --format short --profile $(profile)

# Errors from all three services in the last 30m: make aws-errors
aws-errors:
	@for svc in api worker frontend; do \
	  echo "── $$svc"; \
	  aws logs tail /ecs/agent-harness-$(env)/$$svc --since 30m \
	    --filter-pattern ERROR --format short --profile $(profile) || true; \
	done

# Is it up? Task counts, plus ECS events when a service will not start —
# which is where crash reasons appear before anything reaches CloudWatch.
aws-status:
	@aws ecs describe-services --cluster agent-harness-$(env) --profile $(profile) \
	  --services agent-harness-$(env)-api agent-harness-$(env)-worker agent-harness-$(env)-frontend \
	  --query 'services[].{service:serviceName,desired:desiredCount,running:runningCount,pending:pendingCount}' \
	  --output table
	@echo "── recent events"
	@aws ecs describe-services --cluster agent-harness-$(env) --profile $(profile) \
	  --services agent-harness-$(env)-api agent-harness-$(env)-worker agent-harness-$(env)-frontend \
	  --query 'services[].events[0].message' --output text | tr '\t' '\n'

# Print the live URL and check it: make aws-url
aws-url:
	@url=$$(aws elbv2 describe-load-balancers --profile $(profile) \
	  --names agent-harness-$(env)-alb --query 'LoadBalancers[0].DNSName' --output text); \
	echo "http://$$url"; \
	curl -sS -o /dev/null -w "  /          HTTP %{http_code}\n" "http://$$url/" || true; \
	curl -sS -w "  /api/health %{http_code} " "http://$$url/api/health" || true; echo

# --- AWS teardown (POC: both workspaces are disposable) ---

# Destroy the dev + prod stacks, keep the Terraform state backend
aws-destroy:
	cd terraform && ./destroy-all.sh

# Destroy everything, including the state bucket and lock table
aws-nuke:
	cd terraform && ./destroy-all.sh --nuke

# Prove nothing billable is left: make aws-verify-clean
# Exits non-zero and lists identifiers if anything remains.
aws-verify-clean:
	@AWS_PROFILE=$(profile) ./scripts/aws-verify-clean.sh
