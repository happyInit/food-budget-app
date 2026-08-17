terraform {
  # 🔴 **1.10 이상** — `backend.conf` 의 `use_lockfile`(S3 네이티브 락 · DynamoDB 불요 = 학생 예산)이
  #    1.10 에서 들어왔다. 1.9.x 로 `init` 하면 원인을 짚기 어려운 에러로 죽는다
  #    (`Unsupported argument — "use_lockfile"`). 형제 스택 `../aws-platform` 과 같은 이유·같은 값.
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # 번들 zip 패키징용. 🔵 zip 자체는 `serverless/build.sh` 가 만들고 여기서는 **묶기만** 한다 —
    #    의존성 해석을 Terraform 에 맡기지 않는다(락 파일이 그 일을 한다).
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

# 🔴 이 스택은 이 레포의 다른 세 스택과 **완전히 별개다**.
#      ../             = Proxmox VM (온프렘)             state: tfstate/proxmox.tfstate
#      ../aws/         = 크롤 운반 S3·SQS·IAM (C-44)      state: tfstate/aws-crawl.tfstate
#      ../aws-platform = AWS 플랫폼 (VPC·EKS·ALB·IRSA)    state: tfstate/aws-platform.tfstate
#      여기            = **AI 서버리스** (Lambda 11종)     state: tfstate/aws-ai.tfstate
#
#    state 를 가르는 이유 = **이 스택의 apply 가 VPC·EKS·크롤 큐를 건드릴 수 없어야** 한다.
#    AI 파트가 자기 함수를 배포하는 동안 플랫폼이 흔들리면 안 된다 — 소관이 다르다.
#    🔴 그래서 여기서는 **VPC·서브넷·SG·ALB 를 만들지 않는다.** 전부 변수로 «받는다».
provider "aws" {
  region  = var.region
  profile = var.profile

  # 🔴 **`Project = "mp-ai"` 다. 형제 스택(`mealplanning`)과 일부러 다르다.**
  #    이 프로젝트는 **이름이 곧 권한 경계**다(`docs/mp_aws_team_access.md §4` — "`mp-ai-*` /
  #    `mp-ai/*` 접두사 밖은 전부 거부"). SG 는 ARN 에 이름 자리가 없어 **태그 `Project=mp-ai`**
  #    로 소유권을 판정하는데, 여기서 `mealplanning` 을 기본값으로 두면 그게 우리 자원에 얹혀
  #    **우리가 우리 것을 못 만지게** 된다(`DenySecurityGroupsNotOwnedByMpAi`).
  #    ⚠️ 실제로 밟을 뻔했다 — `TagOnCreateOnly` 가 먼저 막아 준 덕에 사고가 안 났다(2026-08-17).
  #
  # 🔵 부수 효과도 맞는 방향이다 — 비용 태그가 «별도 트랙» 으로 갈려서 kubecost·Cost Explorer 에서
  #    AI 서버리스 비용이 앱 비용과 섞이지 않는다.
  default_tags {
    tags = {
      Project   = "mp-ai"
      ManagedBy = "terraform"
      Stack     = "aws-ai"
    }
  }
}
