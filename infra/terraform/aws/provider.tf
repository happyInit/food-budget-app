terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# 🔴 이 스택은 Proxmox 스택(../)과 **완전히 별개다** — state 도 다르다.
#    지금까지 이 레포의 Terraform 은 Proxmox 전용이었고 aws_ 리소스가 0건이었다.
#    AWS 이관(C-44)에서 실제로 쓰는 첫 AWS 리소스이자, 이관 당일 EKS·VPC 를 짜기 전에
#    프로바이더·백엔드·자격증명 배선을 미리 태워보는 리허설이다.
provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      Project   = "mealplanning"
      ManagedBy = "terraform"
      Stack     = "aws-crawl"
    }
  }
}
