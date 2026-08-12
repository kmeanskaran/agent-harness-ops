# Two roles (guide §1), workspace-named so dev/prod are isolated:
#   - Execution role: used by the ECS agent BEFORE your code runs — pull the
#     image from ECR, ship logs to CloudWatch, read secrets to inject as env.
#   - Task role: assumed by your code at runtime — call Bedrock. Folds in the
#     Claude + Gemma + bearer-token permissions from the old standalone
#     bedrock.tf (which this replaces). app + worker share it in dev.

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---------------- Execution role ----------------
resource "aws_iam_role" "execution" {
  name               = "${local.name_prefix}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Read only this env's secrets (for `secrets` in the task def). Scoped by name
# prefix so it doesn't depend on secrets.tf resource references.
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:${local.name_prefix}/*"]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "${local.name_prefix}-execution-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# ---------------- Task role (runtime: Bedrock) ----------------
resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_bedrock" {
  name = "${local.name_prefix}-bedrock"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeClaude"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*.anthropic.claude-*",
        ]
      },
      {
        # Gemma is served only on bedrock-mantle (/openai/v1); the app reaches it
        # with a short-term bearer token minted from THIS role's credentials.
        Sid      = "InvokeGemma"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = ["arn:aws:bedrock:*::foundation-model/google.gemma-*"]
      },
      {
        Sid      = "CallWithBearerToken"
        Effect   = "Allow"
        Action   = ["bedrock:CallWithBearerToken", "bedrock-mantle:CallWithBearerToken"]
        Resource = "*"
      },
    ]
  })
}
