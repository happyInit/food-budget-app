terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

# 🔴 이 스택은 이 레포의 다른 두 Terraform 스택과 **완전히 별개다** (C-77 · 사용자 지시).
#      ../          = Proxmox VM (온프렘)          state: tfstate/proxmox.tfstate
#      ../aws/      = 크롤 운반 S3·SQS·IAM (C-44)   state: tfstate/aws-crawl.tfstate
#      여기         = AWS 플랫폼 (VPC·EKS·IRSA·ECR) state: tfstate/aws-platform.tfstate
#    같은 파일을 고치지 않고 새로 쓴 이유 = **AWS 쪽 수정이 온프렘으로 번지지 않게** 하는 것이고,
#    state 를 가른 이유 = 이 스택의 apply 가 크롤 큐나 Proxmox VM 을 건드릴 수 없어야 하는 것이다.
provider "aws" {
  region  = var.region
  profile = var.profile

  # A-7 요구사항. 태그가 없으면 kubecost·Cost Explorer 가 "이 비용이 무엇인지" 를 못 가른다.
  default_tags {
    tags = {
      Project   = "mealplanning"
      ManagedBy = "terraform"
      Stack     = "aws-platform"
    }
  }
}
