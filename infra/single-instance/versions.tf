terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Configure the remote encrypted state backend here before the first apply (deployment step 2).
  # Never commit state, plans or *.tfvars.
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "heritagevoice"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
