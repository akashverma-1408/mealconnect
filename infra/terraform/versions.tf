# Works with Terraform >= 1.6 and OpenTofu >= 1.6 (same language).
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }

  # Recommended: keep state in S3 (encrypted, versioned) instead of on your laptop.
  # The state contains generated secrets, so it must be private.
  # backend "s3" {
  #   bucket       = "mealconnect-tfstate-<your-account-id>"
  #   key          = "prod/terraform.tfstate"
  #   region       = "ap-south-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project, Environment = var.environment, ManagedBy = "terraform" }
  }
}

# CloudFront certificates must live in us-east-1, whatever region the app runs in.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = { Project = var.project, Environment = var.environment, ManagedBy = "terraform" }
  }
}
