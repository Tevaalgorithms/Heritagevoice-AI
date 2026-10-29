terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Configure the remote encrypted state backend here before the first apply.
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "heritagevoice"
      ManagedBy = "terraform"
    }
  }
}
