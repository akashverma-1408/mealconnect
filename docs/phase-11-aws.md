# Phase 11 — AWS Deployment (prepared, not yet applied)

Infrastructure as code in `infra/terraform/` (OpenTofu/Terraform). Validated with `tofu validate` (AWS provider 6.73). **Not applied yet — it needs your AWS account and costs money (roughly $60–100/month at default sizes).**

## Architecture
CloudFront (HTTPS, security headers, SPA-rewrite function) → `/` S3 (private, OAC) and `/api/*` ALB (CloudFront-only prefix list + secret origin header) → ECS Fargate ARM64 (`api` ×2–4 autoscaled on CPU, `worker` ×1) → RDS PostgreSQL 16 (private, encrypted, SSL forced, 7-day backups) + ElastiCache Redis 7.1 (private, TLS, auth token, volatile-lru). Secrets in Secrets Manager; images in ECR (immutable tags, scan on push); logs in CloudWatch (30 days); 9 alarms → SNS e-mail; CloudWatch dashboard. No NAT gateway (tasks get public IPs, inbound blocked by security groups). Optional custom domain adds ACM certs + Route 53 + HTTPS origin.

## Deploy (when you're ready)
1. Create an AWS account and an IAM user/role; `aws configure` (your credentials — I can't enter them).
2. `cd infra/terraform && cp terraform.tfvars.example terraform.tfvars` and edit.
3. `tofu init && tofu apply -target=aws_ecr_repository.api` (registry first).
4. `tofu apply` (≈15 min: RDS and CloudFront are slow).
5. `./scripts/deploy-aws.sh` — push image (arm64, git-SHA tag), run migrations as a one-off task (stops on failure), roll out with circuit-breaker rollback, upload frontend, invalidate CloudFront. `DRY_RUN=1` prints the steps.
6. Seed demo data (optional): run the migrate task definition with command override `python -m app.seed --reset` and `ENVIRONMENT=development`.
7. Tear down: `tofu destroy` (set `deletion_protection = false` first).

## Verified locally
`tofu validate` passes; deploy script passes `bash -n`; the API image builds for `linux/arm64` (Fargate Graviton).
