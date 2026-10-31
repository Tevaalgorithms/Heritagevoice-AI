terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
  }

  # State lives in an encrypted, versioned S3 bucket. The bucket name is passed at init time so no
  # account details are committed:
  #   terraform init -backend-config="bucket=<state bucket>" -backend-config="region=<region>"
  # Never commit state, plans or *.tfvars.
  backend "s3" {
    key     = "heritagevoice/single-instance.tfstate"
    encrypt = true
  }
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
