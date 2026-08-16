variable "region" {
  description = "AWS 리전. state 버킷(mp-dashboard-tfstate-ap2)·aws-platform 과 같아야 한다."
  type        = string
  default     = "ap-northeast-2"
}

variable "profile" {
  description = <<-EOT
    apply 에 쓰는 ~/.aws 프로필. 🔴 기본값을 두지 않는다 — `mealplanning-dashboard` 그룹
    (mp-dashboard-dev/-ops/-guardrails 부착)이 붙은 개인 프로필이어야 하고, 잘못된 프로필로
    절반쯤 apply 되는 것보다 처음부터 멈추는 쪽이 싸다(aws-platform/variables.tf 와 같은 판단).
  EOT
  type        = string
}

# ── 기존 aws-platform 리소스를 이름으로 조회하기 위한 키 ─────────────────────
# 🔴 ID 를 박아두지 않는 이유는 `infra/iam/mp-dashboard/apply.sh` 와 같다 — 재생성 때 조용히 어긋난다.

variable "service_vpc_name" {
  description = "aws-platform 이 만든 서비스 VPC 의 Name 태그. apply.sh 의 VPC_NAME 과 같아야 한다."
  type        = string
  default     = "mp-vpc-service"
}

variable "dashboard_subnet_name" {
  description = <<-EOT
    대시보드 EC2 를 띄울 공개 서브넷의 Name 태그. `mp-dashboard-dev` 정책의 `ec2:RunInstances`
    Allow 가 이 서브넷 ARN 하나로 고정돼 있다(apply.sh SUBNET_NAME) — 다른 서브넷으로 바꾸면
    apply 가 AccessDenied 로 막힌다(팀 IAM 도 같이 갱신해야 한다).
  EOT
  type        = string
  default     = "mp-subnet-public-ap-northeast-2a"
}

variable "dashboard_sg_name" {
  description = <<-EOT
    aws-platform 의 security_groups.tf 가 미리 만들어 둔 SG(`mp-sg-dashboard`) — 443 인바운드 +
    전체 아웃바운드만 있고, 이 스택이 80·8011 인바운드 2줄을 여기 추가한다. SG 자체는
    여기서 재생성하지 않는다(C-85 의 NodePort 참조 규칙이 그 SG 의 존재를 전제하기 때문).
  EOT
  type        = string
  default     = "mp-sg-dashboard"
}

variable "node_sg_name" {
  description = "EKS 노드 SG(mp-sg-eks-node). Alertmanager webhook(8011) 인바운드의 출발지로 참조한다."
  type        = string
  default     = "mp-sg-eks-node"
}

# ── 인스턴스 런타임 권한 ──────────────────────────────────────────────────────

variable "bedrock_model_arns" {
  description = <<-EOT
    Operations RCA/RAG 가 호출하는 Bedrock 모델 ARN 목록(교차리전 추론 프로파일 + 기반 모델 +
    RAG 임베딩용 titan-embed). nova-micro 2개는 aws-platform/variables.tf 의 같은 이름
    변수와 값이 같아야 한다(pipeline_bedrock IRSA 와 이 EC2 Instance Profile 이 같은 모델을
    부른다) — 단 스택이 분리돼 있어 변수 자체는 의도된 복제다(C-77, 공유 불가).
    titan-embed-text-v2 는 RAG(런북 임베딩) 전용이라 aws-platform 에는 없다.
  EOT
  type        = list(string)
  default = [
    "arn:aws:bedrock:ap-northeast-2:*:inference-profile/apac.amazon.nova-micro-v1:0",
    "arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.nova-micro-v1:0",
    "arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.titan-embed-text-v2:0",
  ]
}

variable "finops_dashboard_resource_read_policy_arn" {
  description = <<-EOT
    FinOps 가 이미 만든 EC2/EBS/EKS/ElastiCache/ELB Describe 등 읽기 정책의 ARN.
    🔴 이 스택에 정의가 없다 — 다른 곳(콘솔 또는 FinOps 담당)에서 관리 중으로 추정된다.
    빈 문자열이면 attachment 를 만들지 않는다(ARN 확정 전까지 apply 를 막지 않기 위함) —
    확정되면 값을 채우고 재적용한다. 🔴 이 ARN 이 담을 수 있는 action 은 `mp-dashboard-boundary`
    의 RuntimeCommon 범위(Describe/List 계열)를 넘지 못한다 — 넘으면 boundary 가 조용히 막는다.
  EOT
  type        = string
  default     = ""
}
