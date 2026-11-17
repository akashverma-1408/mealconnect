output "site_url" {
  description = "Open this in a browser."
  value       = local.site
}

output "region" {
  value = var.region
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "web_bucket" {
  value = aws_s3_bucket.web.bucket
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "app_subnets" {
  value = aws_subnet.public[*].id
}

output "app_security_group" {
  value = aws_security_group.app.id
}

output "app_secret_arn" {
  description = "Edit RAZORPAY_KEY_SECRET here if you switch to Razorpay."
  value       = aws_secretsmanager_secret.app.arn
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${local.name}"
}
