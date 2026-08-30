terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# 🔴 이 스택은 aws-platform 과 완전히 별개다.
#    aws-platform 은 프로젝트 종료와 함께 destroy 되지만 이 스택은 남는다 —
#    그래서 그쪽 VPC·서브넷을 참조하지 않는다. Lightsail 은 자체 네트워크를 쓴다.
#
#      ../aws-platform/ = VPC·EKS·ALB·CI (철거 예정)  state: tfstate/aws-platform.tfstate
#      여기            = 포트폴리오 Lightsail 1대     state: tfstate/portfolio.tfstate
provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      Project   = "mealplanning"
      ManagedBy = "terraform"
      Stack     = "mp-portfolio"
    }
  }
}
