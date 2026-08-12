# ECS Fargate: one cluster, three services (api, worker, frontend) — the same
# shape as docker-compose. api + worker run the SAME image with different
# commands; frontend runs its own nginx image.
#
# Tasks run in PUBLIC subnets with assign_public_ip = true. That public IP is
# REQUIRED here: with no NAT gateway it's the only way tasks can pull images
# from ECR and reach Bedrock/Langfuse. Inbound is still blocked by the ECS
# security group (only the ALB may connect).

resource "aws_ecs_cluster" "main" {
  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = terraform.workspace == "prod" ? "enabled" : "disabled" # dev: save cost
  }
}

# --- Cloud Map private DNS: gives the API a stable internal name so the
#     frontend's nginx can proxy /api to it without an internal load balancer. ---
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${local.name_prefix}.local"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      type = "A"
      ttl  = 10
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config { failure_threshold = 1 }
}

locals {
  api_image      = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
  frontend_image = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"

  redis_url = "redis://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"

  # Plain (non-secret) env shared by api + worker.
  # AWS_BEARER_TOKEN_BEDROCK is deliberately NOT set: leaving it unset makes the
  # app mint a short-term Bedrock token from the ECS TASK ROLE at runtime.
  app_environment = [
    { name = "REDIS_URL", value = local.redis_url },
    { name = "MODEL_PROVIDER", value = var.model_provider },
    { name = "MODEL_NAME", value = var.model_name },
    { name = "AWS_REGION", value = var.region },
    { name = "JOB_TTL_SECONDS", value = "7200" },
    { name = "LANGFUSE_BASE_URL", value = "https://us.cloud.langfuse.com" },
  ]

  app_secrets = [
    { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
    { name = "LANGFUSE_SECRET_KEY", valueFrom = aws_secretsmanager_secret.langfuse_secret.arn },
    { name = "LANGFUSE_PUBLIC_KEY", valueFrom = aws_secretsmanager_secret.langfuse_public.arn },
    { name = "TAVILY_API_KEY", valueFrom = aws_secretsmanager_secret.tavily_key.arn },
  ]

  task_network = {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }
}

# ---------------- API ----------------
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.env.api_cpu
  memory                   = local.env.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = local.api_image
    essential    = true
    command      = local.api_command
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.app_environment
    secrets      = local.app_secrets
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = local.env.api_desired
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.task_network.subnets
    security_groups  = local.task_network.security_groups
    assign_public_ip = local.task_network.assign_public_ip
  }

  service_registries { registry_arn = aws_service_discovery_service.api.arn }

  depends_on = [aws_db_instance.postgres, aws_elasticache_replication_group.main]
}

# ---------------- Worker (no ALB, no discovery) ----------------
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.env.worker_cpu
  memory                   = local.env.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name        = "worker"
    image       = local.api_image
    essential   = true
    command     = local.worker_command
    environment = local.app_environment
    secrets     = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "worker" {
  name            = "${local.name_prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = local.env.worker_desired
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.task_network.subnets
    security_groups  = local.task_network.security_groups
    assign_public_ip = local.task_network.assign_public_ip
  }

  depends_on = [aws_db_instance.postgres, aws_elasticache_replication_group.main]
}

# ---------------- Frontend (nginx behind the ALB) ----------------
resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name_prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.env.frontend_cpu
  memory                   = local.env.frontend_memory
  execution_role_arn       = aws_iam_role.execution.arn

  container_definitions = jsonencode([{
    name         = "frontend"
    image        = local.frontend_image
    essential    = true
    portMappings = [{ containerPort = 80, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = "80" },
      # nginx proxies /api/ here; Cloud Map resolves it to the API tasks.
      { name = "BACKEND_URL", value = "http://api.${aws_service_discovery_private_dns_namespace.main.name}:8000" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "frontend"
      }
    }
  }])
}

resource "aws_ecs_service" "frontend" {
  name            = "${local.name_prefix}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = local.env.frontend_desired
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.task_network.subnets
    security_groups  = local.task_network.security_groups
    assign_public_ip = local.task_network.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 80
  }

  health_check_grace_period_seconds = 60
  depends_on                        = [aws_lb_listener.http]
}
