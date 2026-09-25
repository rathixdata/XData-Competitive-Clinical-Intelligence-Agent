terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state per environment, e.g.:
  #   terraform init -backend-config=envs/production.backend.hcl
  # with bucket / key / region / dynamodb_table (or use_lockfile = true) in that file.
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}
