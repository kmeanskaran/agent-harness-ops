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

# The model MUST emit structured tool calls, because the orchestrator is a
# DeepAgents graph that does all its work through tools — it writes every draft
# with write_file. A model that cannot call tools does not fail; it returns
# prose, the graph ends after one turn, no draft files exist, and
# assemble_result yields empty strings. See the guard in orchestrator.py.
#
# `google.gemma-3-*` was the previous default and is exactly that trap. Bedrock
# accepts a toolConfig for it without complaint, but Gemma answers in its own
# ```tool_code``` dialect and AWS never wrote the Converse adapter for it, so
# replies come back as plain text with stopReason=end_turn. Both 12b and 27b
# behave this way — it is a missing adapter, not a model-size limit, and no
# amount of prompting works around it. Every other open-weights family on
# Bedrock (deepseek, qwen, mistral, gpt-oss, glm, minimax, kimi, nemotron)
# returns a real toolUse block.
#
# `google.gemma-4-e2b` (the original default, via the bedrock_openai/mantle
# path) is NOT offered in this account — us-east-1 lists only gemma-3-*.
#
# Anthropic models go through an AWS Marketplace subscription, still failing in
# this account with INVALID_PAYMENT_INSTRUMENT (re-verified 2026-08-14, on the
# `us.` inference profile — the bare id additionally rejects on-demand
# throughput). DeepSeek needs no Marketplace subscription. It does NOT support
# prompt caching, so app/agent/model.py skips the cachePoint injection for any
# non-Anthropic model id.
#
# Once a valid payment method is on the account, switch back with:
#   default = "us.anthropic.claude-sonnet-4-6"
variable "model_name" {
  description = "MODEL_NAME env (the Bedrock model id). Must support tool calling."
  type        = string
  # deepseek.v3.2 emits valid tool calls but does not converge in a long
  # delegation loop: with the workspace paths fixed it reached the extractor and
  # wrote extracted_insights.md, then called `ls` on the same directory ~40
  # times without moving on to the writer. GLM is built for extended
  # tool-calling loops. zai.glm-5 and moonshotai.kimi-k2.5 are the fallbacks —
  # all three verified `stopReason: tool_use` against this account.
  default = "zai.glm-4.7"
}
