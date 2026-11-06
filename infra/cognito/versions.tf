terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # State lives in an encrypted, versioned S3 bucket. The bucket name is passed at init time so no
  # account details are committed:
  #   terraform init -backend-config="bucket=<state bucket>" -backend-config="region=<region>"
  # Never commit state, plans or *.tfvars.
  backend "s3" {
    key     = "heritagevoice/cognito.tfstate"
    encrypt = true
  }
}

provider "aws" {
  region = var.region
}

# A custom sign-in domain is served through CloudFront, which only accepts certificates from
# us-east-1 (N. Virginia). Nothing else of ours lives there.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
