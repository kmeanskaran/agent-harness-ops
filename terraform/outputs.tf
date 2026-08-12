output "app_url" {
  description = "Open this in a browser — frontend + proxied /api."
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_api_repo_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_frontend_repo_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "rds_endpoint" {
  value = aws_db_instance.postgres.address
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "api_internal_dns" {
  description = "Cloud Map name the frontend proxies /api to."
  value       = "api.${aws_service_discovery_private_dns_namespace.main.name}:8000"
}

output "task_role_arn" {
  description = "Runtime role the app uses to mint Bedrock tokens."
  value       = aws_iam_role.task.arn
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "secrets_to_set" {
  description = "Secrets whose placeholder value must be replaced."
  value = {
    LANGFUSE_SECRET_KEY = aws_secretsmanager_secret.langfuse_secret.name
    LANGFUSE_PUBLIC_KEY = aws_secretsmanager_secret.langfuse_public.name
    TAVILY_API_KEY      = aws_secretsmanager_secret.tavily_key.name
  }
}
