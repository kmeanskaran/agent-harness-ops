# Bootstrap: creates the S3 bucket + DynamoDB table that hold Terraform state
# for the MAIN config. Run ONCE, on local state (there's no remote backend to
# store its own state yet — chicken/egg). After apply, the main config's S3
# backend (../versions.tf) points at these.
#
#   cd terraform/bootstrap
#   terraform init
#   terraform apply -var="aws_profile=mgmt"
#
# The bucket name embeds the account id, which is read from the caller identity
# — so this targets whichever account var.aws_profile authenticates to. Run it
# once per account you deploy into.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "aws_profile" {
  description = "Local AWS profile to bootstrap into (e.g. `mgmt` for the org management account)."
  type        = string
}

provider "aws" {
  region  = "us-east-1"
  profile = var.aws_profile
}

data "aws_caller_identity" "current" {}

locals {
  state_bucket = "agent-harness-tfstate-${data.aws_caller_identity.current.account_id}"
  lock_table   = "agent-harness-tflock"
}

resource "aws_s3_bucket" "state" {
  bucket        = local.state_bucket
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Locks concurrent applies; dev + prod workspaces share it, keyed by state path.
resource "aws_dynamodb_table" "lock" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

# --------------------------------------------------------------------------- #
# GitHub Actions → AWS auth via OIDC (no stored AWS keys in GitHub).
#
# GitHub mints a short-lived OIDC token per workflow run; AWS trusts it and lets
# the run assume this deploy role. You store only the ROLE ARN in GitHub (not a
# secret). Same "identity, not keys" idea as the Bedrock task role.
#
# This lives in BOOTSTRAP, not the main config, because it is account-level and
# unnamespaced: the OIDC provider is one-per-account and the role name is fixed,
# so applying it from both the `dev` and `prod` workspaces would collide with
# EntityAlreadyExists. Keeping it here also means CI auth survives
# `./destroy-all.sh` and only disappears on `--nuke`.
# --------------------------------------------------------------------------- #

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as owner/repo."
  type        = string
  default     = "kmeanskaran/agent-harness-ops"
}

# The only refs that deploy. Anything else in the repo — a feature branch, a
# non-prod tag, a fork's PR — cannot assume the role even though the workflow
# file is public and readable. Keep in sync with the `target` job in ci.yml.
variable "github_deploy_refs" {
  description = "Git refs allowed to assume the deploy role."
  type        = list(string)
  default = [
    "refs/heads/aws-deployment", # -> dev
    "refs/tags/prod-*",          # -> prod
  ]
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only this repo, and only from the refs that actually deploy. StringLike
    # so the `prod-*` tag pattern matches; the branch entry has no wildcard, so
    # it matches exactly.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for r in var.github_deploy_refs : "repo:${var.github_repo}:ref:${r}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "agent-harness-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

# Permissions the pipeline needs: push to ECR, run Terraform (state + the
# resources it manages), roll ECS. Broad within this project's namespace;
# tighten before this is a real production account.
data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrPush"
    actions   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = ["*"]
  }
  statement {
    sid     = "TerraformState"
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [
      "arn:aws:s3:::${local.state_bucket}",
      "arn:aws:s3:::${local.state_bucket}/*",
      "arn:aws:dynamodb:us-east-1:${data.aws_caller_identity.current.account_id}:table/${local.lock_table}",
    ]
  }
  statement {
    sid    = "ManageStack"
    effect = "Allow"
    # The services Terraform creates/updates for this project.
    actions = [
      "ec2:*", "ecs:*", "elasticloadbalancing:*", "rds:*", "elasticache:*",
      "ecr:*", "logs:*", "servicediscovery:*", "secretsmanager:*",
      "iam:*", "budgets:*", "cloudwatch:*", "sns:*", "application-autoscaling:*",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "agent-harness-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

output "state_bucket" { value = aws_s3_bucket.state.id }
output "lock_table" { value = aws_dynamodb_table.lock.name }

output "github_deploy_role_arn" {
  description = "Put this in the GitHub Actions variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.github_deploy.arn
}
