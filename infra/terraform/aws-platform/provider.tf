terraform {
  # 🔴 **1.10 이상이다 — `>= 1.6` 이 아니다.** 리허설(2026-08-13)에서 실측으로 잡았다:
  #    `backend.conf` 의 **`use_lockfile`**(S3 네이티브 락 · DynamoDB 불요 = 학생 예산)이
  #    **Terraform 1.10 에서 들어온 기능**이라, 1.9.x 로 `init` 하면
  #      `Error: Unsupported argument — An argument named "use_lockfile" is not expected here.`
  #    로 죽는다. 원인을 짚기 어려운 에러라 **여기서 버전으로 먼저 막는다.**
  #    ⚠️ 기존 `../`(Proxmox)·`../aws/` 스택도 같은 backend 옵션을 쓰면서 `>= 1.6` 이지만,
  #       그 파일들은 C-77 로 손대지 않는다(같은 잠재 불일치가 있다는 사실만 기록한다).
  required_version = ">= 1.10"
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
