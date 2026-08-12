variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Local AWS profile for auth (the org management account). In prod/CI this is unset and creds come from the environment/role."
  type        = string
  default     = "mgmt"
}

variable "api_image_tag" {
  description = "Tag of the agent-harness-api image to deploy (git short SHA)."
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Tag of the agent-harness-frontend image to deploy."
  type        = string
  default     = "latest"
}

variable "model_provider" {
  description = "MODEL_PROVIDER env for the app."
  type        = string
  default     = "bedrock"
}

# `google.gemma-4-e2b` (the old default, via the bedrock_openai/mantle path) is
# NOT offered in this account — us-east-1 lists only gemma-3-*.
#
# Anthropic models on Bedrock go through an AWS Marketplace subscription, which
# is currently failing in this account with INVALID_PAYMENT_INSTRUMENT. Gemma 3
# needs no Marketplace subscription and is ~30x cheaper. It does NOT support
# prompt caching, so app/agent/model.py skips the cachePoint injection for any
# non-Anthropic model id.
#
# Once a valid payment method is on the account, switch back with:
#   default = "us.anthropic.claude-sonnet-4-6"
variable "model_name" {
  description = "MODEL_NAME env (the Bedrock model id)."
  type        = string
  default     = "google.gemma-3-12b-it"
}
