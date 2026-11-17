# ---- PostgreSQL (Amazon RDS) ---------------------------------------------------
resource "random_password" "db" {
  length  = 32
  special = false # avoids URL-escaping problems inside DATABASE_URL
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "pg16" {
  name   = "${local.name}-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl" # refuse unencrypted connections
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement" # log queries slower than 500 ms
    value = "500"
  }
}

resource "aws_db_instance" "main" {
  identifier            = local.name
  engine                = "postgres"
  engine_version        = "16"
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 100 # storage autoscaling
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "mealconnect"
  username = "mealconnect"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.pg16.name
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  backup_retention_period         = 7
  backup_window                   = "20:00-21:00" # 01:30-02:30 IST
  maintenance_window              = "sun:21:30-sun:22:30"
  auto_minor_version_upgrade      = true
  performance_insights_enabled    = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${local.name}-final" : null
}

# ---- Redis (Amazon ElastiCache) ------------------------------------------------
resource "random_password" "redis" {
  length  = 32
  special = false
}

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = local.name
  description                = "MealConnect cache, rate limits and job queue"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true # TLS: the app connects with rediss://
  auth_token                 = random_password.redis.result
  # Evict only keys with a TTL (cache, rate-limit counters); never queued jobs.
  parameter_group_name     = aws_elasticache_parameter_group.redis.name
  snapshot_retention_limit = 1
  apply_immediately        = true
}

resource "aws_elasticache_parameter_group" "redis" {
  name   = "${local.name}-redis7"
  family = "redis7"
  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }
}

# ---- Application secrets (AWS Secrets Manager) --------------------------------
resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "webhook" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name}/app"
  description             = "MealConnect runtime secrets (injected into ECS tasks)"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL           = "postgresql+psycopg://mealconnect:${random_password.db.result}@${aws_db_instance.main.address}:5432/mealconnect?sslmode=require"
    REDIS_URL              = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
    JWT_SECRET_KEY         = random_password.jwt.result
    PAYMENT_WEBHOOK_SECRET = random_password.webhook.result
    # Set the real value in the AWS console/CLI if you use Razorpay; Terraform ignores later edits.
    RAZORPAY_KEY_SECRET = ""
  })
  lifecycle {
    ignore_changes = [secret_string] # values edited by hand (e.g. Razorpay secret) are kept
  }
}
