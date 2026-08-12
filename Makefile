.PHONY: up down fresh logs restart \
        aws-logs aws-errors aws-status aws-url aws-destroy aws-nuke

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
