resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
  # AWS sends a confirmation email; the subscription is pending until it is clicked.
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "More than 5 Lambda errors in 5 minutes."
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# Billing metrics are published only in us-east-1.
resource "aws_cloudwatch_metric_alarm" "billing" {
  provider            = aws.us_east_1
  alarm_name          = "${var.project}-monthly-charges"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600
  statistic           = "Maximum"
  threshold           = var.monthly_budget_usd
  alarm_description   = "Estimated AWS charges crossed the budget."
  dimensions          = { Currency = "USD" }
  alarm_actions       = [aws_sns_topic.alerts_us.arn]
  treat_missing_data  = "notBreaching"
}

# The billing alarm's SNS action must live in the same region as the alarm.
resource "aws_sns_topic" "alerts_us" {
  provider = aws.us_east_1
  name     = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email_us" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.alerts_us.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}
