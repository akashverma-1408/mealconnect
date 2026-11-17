# Alarms go to an SNS topic; subscribe your e-mail via var.alert_email.
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alb_dim = { LoadBalancer = aws_lb.main.arn_suffix }
  tg_dim  = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
  alarms = {
    # name = [namespace, metric, statistic/extended, threshold, comparison, dimensions, description]
    api-5xx = ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "Sum", 10, "GreaterThanThreshold", local.tg_dim,
    "API returned more than 10 server errors in 5 minutes"]
    api-latency-p95 = ["AWS/ApplicationELB", "TargetResponseTime", "p95", 1, "GreaterThanThreshold", local.tg_dim,
    "API p95 latency above 1 second"]
    api-unhealthy = ["AWS/ApplicationELB", "UnHealthyHostCount", "Maximum", 0, "GreaterThanThreshold", local.tg_dim,
    "At least one API task is failing health checks"]
    api-cpu = ["AWS/ECS", "CPUUtilization", "Average", 85, "GreaterThanThreshold",
    { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.api.name }, "API CPU above 85% (autoscaling at max?)"]
    worker-down = ["ECS/ContainerInsights", "RunningTaskCount", "Minimum", 1, "LessThanThreshold",
    { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.worker.name }, "Background worker is not running"]
    db-cpu = ["AWS/RDS", "CPUUtilization", "Average", 80, "GreaterThanThreshold",
    { DBInstanceIdentifier = aws_db_instance.main.identifier }, "Database CPU above 80%"]
    db-storage = ["AWS/RDS", "FreeStorageSpace", "Minimum", 2147483648, "LessThanThreshold",
    { DBInstanceIdentifier = aws_db_instance.main.identifier }, "Less than 2 GB database storage left"]
    redis-memory = ["AWS/ElastiCache", "DatabaseMemoryUsagePercentage", "Maximum", 80, "GreaterThanThreshold",
    { ReplicationGroupId = aws_elasticache_replication_group.main.id }, "Redis memory above 80%"]
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each            = local.alarms
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = each.value[6]
  namespace           = each.value[0]
  metric_name         = each.value[1]
  statistic           = startswith(each.value[2], "p") ? null : each.value[2]
  extended_statistic  = startswith(each.value[2], "p") ? each.value[2] : null
  threshold           = each.value[3]
  comparison_operator = each.value[4]
  dimensions          = each.value[5]
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = each.key == "worker-down" ? "breaching" : "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# Application-level errors: count JSON log lines with "level": "ERROR".
resource "aws_cloudwatch_log_metric_filter" "api_errors" {
  name           = "${local.name}-api-errors"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.level = \"ERROR\" }"
  metric_transformation {
    name      = "ApiErrorLogs"
    namespace = "MealConnect"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_error_logs" {
  alarm_name          = "${local.name}-api-error-logs"
  alarm_description   = "API logged more than 5 errors in 5 minutes (search logs by request_id)"
  namespace           = "MealConnect"
  metric_name         = "ApiErrorLogs"
  statistic           = "Sum"
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      for i, w in [
        ["Requests", "AWS/ApplicationELB", "RequestCount", "Sum", local.alb_dim],
        ["5xx errors", "AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "Sum", local.tg_dim],
        ["Latency p95 (s)", "AWS/ApplicationELB", "TargetResponseTime", "p95", local.tg_dim],
        ["API CPU %", "AWS/ECS", "CPUUtilization", "Average", { ClusterName = aws_ecs_cluster.main.name, ServiceName = "api" }],
        ["DB CPU %", "AWS/RDS", "CPUUtilization", "Average", { DBInstanceIdentifier = aws_db_instance.main.identifier }],
        ["DB connections", "AWS/RDS", "DatabaseConnections", "Average", { DBInstanceIdentifier = aws_db_instance.main.identifier }],
        ["Redis memory %", "AWS/ElastiCache", "DatabaseMemoryUsagePercentage", "Maximum", { ReplicationGroupId = aws_elasticache_replication_group.main.id }],
        ["App error logs", "MealConnect", "ApiErrorLogs", "Sum", {}],
        ] : {
        type   = "metric"
        x      = (i % 2) * 12
        y      = floor(i / 2) * 6
        width  = 12
        height = 6
        properties = {
          title   = w[0]
          region  = var.region
          stat    = w[3]
          period  = 300
          metrics = [concat([w[1], w[2]], flatten([for k, v in w[4] : [k, v]]))]
        }
      }
    ]
  })
}
