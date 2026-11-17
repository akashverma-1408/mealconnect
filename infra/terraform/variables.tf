variable "project" {
  type    = string
  default = "mealconnect"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "region" {
  description = "AWS region for everything except CloudFront certificates (Mumbai by default)."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "image_tag" {
  description = "Initial image tag for the task definitions; deploys register new revisions."
  type        = string
  default     = "latest"
}

# ---- sizing (smallest sensible defaults; scale up later) --------------------
variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "api_min_tasks" {
  type    = number
  default = 2
}

variable "api_max_tasks" {
  type    = number
  default = 4
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_multi_az" {
  description = "Standby database in a second AZ (doubles DB cost; recommended for real production)."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "deletion_protection" {
  description = "Protect the database from `destroy`. Set false only for throwaway environments."
  type        = bool
  default     = true
}

# ---- application settings ---------------------------------------------------
variable "payment_provider" {
  type    = string
  default = "mock"
  validation {
    condition     = contains(["mock", "razorpay"], var.payment_provider)
    error_message = "payment_provider must be mock or razorpay."
  }
}

variable "razorpay_key_id" {
  description = "Public Razorpay key id (rzp_test_...). The key SECRET is set in Secrets Manager, not here."
  type        = string
  default     = ""
}

variable "sandbox_payments_enabled" {
  description = "Allow the mock gateway's sandbox pay endpoint (demo deployments)."
  type        = bool
  default     = true
}

variable "api_docs_enabled" {
  type    = bool
  default = true
}

# ---- optional custom domain --------------------------------------------------
variable "domain_name" {
  description = "e.g. mealconnect.example.com. Empty = use the CloudFront *.cloudfront.net address."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Hosted zone that owns domain_name (needed for certificate validation and DNS)."
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Where CloudWatch alarms are e-mailed (you must click the confirmation link)."
  type        = string
  default     = ""
}
