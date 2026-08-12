# Secrets Manager — injected into tasks via `secrets` in the task definition
# (resolved by the execution role at task start).
#
# NOTE: there is NO model API key here. The Gemma path authenticates with a
# short-term bearer token minted from the ECS TASK ROLE at runtime, so there is
# nothing to store for the model.
#
#   - DATABASE_URL: fully Terraform-managed (built from the RDS endpoint).
#   - The rest: Terraform creates the container with a placeholder; you set the
#     real value once. `ignore_changes` stops Terraform reverting it later.

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${local.name_prefix}/DATABASE_URL"
  recovery_window_in_days = 0 # POC: delete immediately, so a re-apply can reuse the name
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql://%s:%s@%s:5432/%s",
    aws_db_instance.postgres.username,
    random_password.db.result,
    aws_db_instance.postgres.address,
    aws_db_instance.postgres.db_name,
  )
}

resource "aws_secretsmanager_secret" "langfuse_secret" {
  name                    = "${local.name_prefix}/LANGFUSE_SECRET_KEY"
  recovery_window_in_days = 0 # POC: delete immediately, so a re-apply can reuse the name
}
resource "aws_secretsmanager_secret" "langfuse_public" {
  name                    = "${local.name_prefix}/LANGFUSE_PUBLIC_KEY"
  recovery_window_in_days = 0 # POC: delete immediately, so a re-apply can reuse the name
}
resource "aws_secretsmanager_secret" "tavily_key" {
  name                    = "${local.name_prefix}/TAVILY_API_KEY"
  recovery_window_in_days = 0 # POC: delete immediately, so a re-apply can reuse the name
}

resource "aws_secretsmanager_secret_version" "langfuse_secret" {
  secret_id     = aws_secretsmanager_secret.langfuse_secret.id
  secret_string = "REPLACE_ME"
  lifecycle { ignore_changes = [secret_string] }
}
resource "aws_secretsmanager_secret_version" "langfuse_public" {
  secret_id     = aws_secretsmanager_secret.langfuse_public.id
  secret_string = "REPLACE_ME"
  lifecycle { ignore_changes = [secret_string] }
}
resource "aws_secretsmanager_secret_version" "tavily_key" {
  secret_id     = aws_secretsmanager_secret.tavily_key.id
  secret_string = "REPLACE_ME"
  lifecycle { ignore_changes = [secret_string] }
}
