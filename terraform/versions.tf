terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
  backend "s3" {}   # configured via -backend-config=backend.hcl
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "RealVote"
      ManagedBy = "terraform"
    }
  }
}

# CloudFront certificates and billing metrics only exist in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project   = "RealVote"
      ManagedBy = "terraform"
    }
  }
}
