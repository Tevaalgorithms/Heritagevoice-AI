terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Configure the remote encrypted state backend here (deployment step 2). Never commit state.
}

provider "aws" {
  region = var.region
}
