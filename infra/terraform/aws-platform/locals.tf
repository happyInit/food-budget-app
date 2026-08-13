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

  # Interface 엔드포인트 (C-56). 🔴 근거는 비용 절감이 아니라 **NAT 1대 SPOF 우회**다.
  #   ECR 미채택 = 레이어 바이트가 S3 Gateway EP 로 빠진다 / KMS 미채택 = 파드가 KMS 를 직접 안 부른다.
  #
  # 🔴 **리허설에서 나온 정합성 문제 — 정본 C-56 의 3종에 `ssm` 이 없다.**
  #    C-56 은 `sqs` · `secretsmanager` · `sts` 를 골랐는데, **C-23 이 비밀 백엔드를
  #    SSM ParameterStore 로 확정**했다(`spec.provider.aws.service: ParameterStore` — config
  #    `bootstrap/eso/overlays/eks/clustersecretstore.yaml` 실물). ⇒ 지금 형상에서
  #      · `secretsmanager` 엔드포인트는 **소비자가 없다**(월 $18.98 를 쓰는 ENI 2장)
  #      · ESO 의 SSM 호출은 **NAT 를 탄다** — 즉 *"ExternalSecret 30종 전부"* 를 가르는 컴포넌트가
  #        정확히 C-56 이 보험을 들려던 SPOF 위에 남는다
  #    🔴 **여기서 정본을 바꾸지 않는다**(C-56 = 사용자 확정). 변수로 빼 두어 결정이 나면 한 줄로 바뀐다.
  #    ⇒ 권고 = `secretsmanager` → `ssm` 교체(개수·비용 동일) 또는 `ssm` 추가(+$18.98/월).
  interface_endpoints = var.interface_endpoints

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

  # ── Ansible `eks.yml` 에 넘기는 값 묶음 (정의는 여기 한 곳) ──────────────────
  # 🔴 `outputs.tf` 의 두 output(`ansible_extra_vars` · `..._json`)이 이것을 함께 참조한다.
  #    종전에는 같은 map 을 두 벌 적어 뒀는데, 키를 추가할 때 한쪽만 고치면
  #    JSON 쪽에서만 값이 비어 Ansible 이 조용히 다르게 동작한다.
  ansible_extra_vars = {
    eks_cluster_name        = aws_eks_cluster.main.name
    eks_cluster_endpoint    = aws_eks_cluster.main.endpoint
    eks_region              = var.region
    eks_node_security_group = aws_security_group.node.id
    eks_vpc_id              = aws_vpc.service.id
    eks_ecr_registry        = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"

    # 🔴 **프로필이 반드시 함께 가야 한다** — 2026-08-13 실행에서 잡았다(결함 #10).
    #    이 머신의 `~/.aws/credentials` 에는 `[default]` 이 **없다**(`mp-platform` 단독).
    #    그런데 `eks.yml` 은 `--profile` 을 어디에도 붙이지 않아
    #      ① `aws eks update-kubeconfig` 이 자격증명을 못 찾아 죽고,
    #      ② 설령 넘겼어도 kubeconfig 의 `exec`(= `aws eks get-token`)에 프로필이 안 박혀
    #         **나중에 `kubectl` 이 같은 이유로 죽는다.**
    #    `--profile` 을 주면 AWS CLI 가 kubeconfig 의 exec env 에 `AWS_PROFILE` 을 심어 주므로
    #    ②까지 함께 해소된다. ⇒ 값을 손으로 적지 않고 Terraform 이 쓴 그 값을 흘려보낸다.
    eks_aws_profile = var.profile

    irsa_cilium_operator  = aws_iam_role.cilium_operator.arn
    irsa_ebs_csi          = aws_iam_role.ebs_csi.arn
    irsa_external_secrets = aws_iam_role.external_secrets.arn
    irsa_karpenter        = aws_iam_role.karpenter.arn
    karpenter_queue_name  = aws_sqs_queue.karpenter_interruption.name
    karpenter_node_role   = aws_iam_role.node.name
  }
}
