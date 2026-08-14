terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# 🔴 이 스택은 aws-platform 과 완전히 별개다 — C-77(스택 분리 원칙)의 연장, 그리고 IAM 도
#    별도 4종(`infra/iam/mp-dashboard/*.json`)이라 apply 주체(mp-dashboard-dev 가 붙은 사람)가
#    aws-platform 의 VPC·EKS·ECR 을 만들거나 지울 수 없다(mp-dashboard-guardrails 가 explicit Deny).
#      ../aws-platform/ = VPC·EKS·IRSA·ECR    state: tfstate/aws-platform.tfstate · 버킷 mp-backup-ap2
#      여기            = 대시보드 EC2(C-84)   state: tfstate/dashboard.tfstate    · 버킷 mp-dashboard-tfstate-ap2
provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      Project   = "mealplanning"
      ManagedBy = "terraform"
      Stack     = "mp-dashboard"
    }
  }
}

# 🔴 `aws_vpc_security_group_ingress_rule` 전용 — default_tags 를 안 붙이는 별칭.
#    이유: 이 리소스는 tags 를 지원해서(스키마 확인됨) 위 provider 를 쓰면 생성 시 태그가
#    자동으로 같이 붙는데, AWS 는 "생성 + 태깅" 복합 호출에 `ec2:CreateTags` 를
#    `ec2:CreateAction == AuthorizeSecurityGroupIngress` 조건으로 **별도 허용**해야 한다.
#    `mp-dashboard-dev` 의 `TagAtCreationTime` Sid 는 그 액션을 허용 목록에 안 넣었다
#    (RunInstances·CreateSecurityGroup·AllocateAddress·CreateVolume·CreateNetworkInterface 뿐) —
#    즉 태그가 같이 실리면 호출 전체가 AccessDenied 로 막힌다. 테라폼은 리소스 단위로
#    default_tags 를 끄는 옵션이 없어서(공급자 단위로만 가능) 별칭 provider 로 우회한다.
provider "aws" {
  alias   = "no_default_tags"
  region  = var.region
  profile = var.profile
}
