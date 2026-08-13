# 서브넷 배분 — C-33(3티어 × 2AZ = **6개**. 종전 4티어/8개에서 도구 티어 삭제 = C-74) ·
# 대역 값은 목표 아키텍처 §1 다이어그램 정본.
#
#   ① 공개  10.10.0.0/24 · 10.10.1.0/24     ALB 랜카드 · NAT GW(AZ-a) · 대시보드 EC2(C-84)
#   ② 노드  10.10.64.0/20 · 10.10.80.0/20   EKS 노드 + 파드(C-82 ENI = 파드가 이 대역을 쓴다) + Interface EP
#   ③ 데이터 10.10.32.0/24 · 10.10.33.0/24   ElastiCache (A1) · 🔴 밖으로 나가는 경로 없음
#   ❌ 도구 10.10.16.0/20 = **예비**(C-74 로 입주자 0 · 서브넷을 만들지 않는다)
#
# 🔴 노드 티어가 /20 인 이유 = **C-82(ENI 모드)로 파드가 이 서브넷의 VPC IP 를 직접 쓴다.**
#    별도 파드 CIDR 이 없으므로 여기가 좁으면 파드가 안 뜬다. /20 = 4,091 사용 가능(AWS 예약 5개 제외)
#    vs 노드 2대 × max-pods 58 = 116 ⇒ 35배 여유. Karpenter 확장·BG 2배 버스트를 함께 흡수한다.
locals {
  az_keys = { for i, az in var.azs : az => i }

  public_subnets = { for az, i in local.az_keys : az => cidrsubnet(var.vpc_service_cidr, 8, i) }
  # 10.10.0.0/24, 10.10.1.0/24

  node_subnets = { for az, i in local.az_keys : az => cidrsubnet(var.vpc_service_cidr, 4, 4 + i) }
  # 10.10.64.0/20, 10.10.80.0/20

  data_subnets = { for az, i in local.az_keys : az => cidrsubnet(var.vpc_service_cidr, 8, 32 + i) }
  # 10.10.32.0/24, 10.10.33.0/24

  # NAT 는 1대뿐이고 AZ-a 공개 서브넷에 둔다 (C-47).
  # 🔴 포기한 것 = AZ-a 단절 시 **두 AZ 모두 아웃바운드 사망**(OAuth 로그인 불가) → 온프렘 페일오버로 받는다(C-3).
  nat_az = var.azs[0]

  # Interface 엔드포인트 3종 (C-56). 🔴 근거는 비용 절감이 아니라 **NAT 1대 SPOF 우회**다.
  #   ECR 미채택 = 레이어 바이트가 S3 Gateway EP 로 빠진다 / KMS 미채택 = 파드가 KMS 를 직접 안 부른다.
  interface_endpoints = ["sqs", "secretsmanager", "sts"]

  # ── ECR 리포 18개 (A-46 확정 = `mealplanning/` 유지 · A-2 lifecycle) ─────────
  # 🔴 자동 생성되지 않는다 — 이름이 갈리면 A2 의 pull 실패로 **가장 늦게** 드러난다.
  # 목록의 출처 = config 레포에서 기계적으로 뽑은 것이며 추측이 아니다:
  #   ① `overlays/eks` 의 `images[].newName` 16개 (services 13 + data-pipeline + crawler-kurly + pgsync)
  #   ② base 인라인 핀 중 EKS 에서도 쓰는 커스텀 이미지 2개 (elasticsearch-nori · rollouts-gatewayapi-plugin)
  # ❌ `mp-cloudflared` 제외 — `services/cloudflared` 는 `overlays/eks` 가 **없다**(C-5 = 온프렘 DR 전용).
  #    온프렘이 Harbor 에서 계속 받는다. ECR↔Harbor 미러 경로는 별건(`A-31`).
  ecr_repositories = [
    "mealplanning/mp-account-service",
    "mealplanning/mp-chat-service",
    "mealplanning/mp-crawler-kurly",
    "mealplanning/mp-data-pipeline",
    "mealplanning/mp-elasticsearch-nori",
    "mealplanning/mp-frontend",
    "mealplanning/mp-mealplan-service",
    "mealplanning/mp-notify-service",
    "mealplanning/mp-ocr-service",
    "mealplanning/mp-operations-service",
    "mealplanning/mp-pantry-service",
    "mealplanning/mp-pgsync",
    "mealplanning/mp-price-service",
    "mealplanning/mp-ranking-serving",
    "mealplanning/mp-recipe-service",
    "mealplanning/mp-recipebook-service",
    "mealplanning/mp-rollouts-gatewayapi-plugin",
    "mealplanning/mp-video-service",
  ]
}
