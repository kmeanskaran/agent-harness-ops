# Minimal guardrail for dev: one account-wide monthly budget with an email
# alert. Cheap insurance against a forgotten stack or a retry storm.
# (Dashboards, alarms, and tracing are deliberately skipped in dev — Langfuse
# already covers LLM-pipeline observability.)

variable "budget_limit_usd" {
  description = "Monthly AWS budget threshold (USD)."
  type        = string
  default     = "50"
}

variable "budget_email" {
  description = "Email notified at the budget thresholds."
  type        = string
  default     = "karanshingde@gmail.com"
}

# --- Application error monitoring -------------------------------------------
# The app now emits one JSON object per log line, so a metric filter can match
# on the `level` field directly and turn ERROR logs into a CloudWatch metric we
# can alarm on. This is the "monitor the logs" half of structured logging.

resource "aws_cloudwatch_log_metric_filter" "worker_errors" {
  name           = "${local.name_prefix}-worker-errors"
  log_group_name = aws_cloudwatch_log_group.worker.name
  pattern        = "{ $.level = \"ERROR\" }" # JSON field match

  metric_transformation {
    name          = "WorkerErrors"
    namespace     = "agent-harness/${terraform.workspace}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "api_errors" {
  name           = "${local.name_prefix}-api-errors"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.level = \"ERROR\" }"

  metric_transformation {
    name          = "ApiErrors"
    namespace     = "agent-harness/${terraform.workspace}"
    value         = "1"
    default_value = "0"
  }
}

# Alarm when jobs start failing. Emails the same address as the budget alarm.
resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.budget_email
}

resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${local.name_prefix}-worker-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 3 # 3+ errors in 5 min
  period              = 300
  statistic           = "Sum"
  metric_name         = aws_cloudwatch_log_metric_filter.worker_errors.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.worker_errors.metric_transformation[0].namespace
  treat_missing_data  = "notBreaching" # no logs = no errors, not an alarm
  alarm_description   = "Worker logged 3+ ERRORs in 5 minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = var.budget_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
