terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }

  # Remote state in the bucket created by ./bootstrap. Workspaces namespace the
  # state under env:/<workspace>/<key>, so `dev` and `prod` never collide while
  # sharing one bucket + lock table.
  #
  # Deliberately EMPTY (partial config): the bucket name embeds an account id,
  # and backend blocks cannot interpolate variables. Supply it at init time:
  #   terraform init -backend-config=backend.hcl
  # Switching target accounts = point at a different backend.hcl.
  backend "s3" {}
}

provider "aws" {
  region = var.region
  # Local dev uses the `dev` SSO profile; in CI (GitHub OIDC) the profile is
  # empty, so fall back to the ambient credential chain (the assumed role).
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      Project     = "agent-harness"
      Environment = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}
