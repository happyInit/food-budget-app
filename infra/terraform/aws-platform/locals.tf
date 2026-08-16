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
  # ⟳ **2026-08-13 정정 — 여기 있던 "정합성 문제" 는 내 오독이었다(결함 #24).**
  #    나는 *"C-23 이 비밀 백엔드를 SSM ParameterStore 로 확정했으니 `secretsmanager`
  #    엔드포인트는 소비자가 없다"* 고 적었다. **틀렸다** — C-23 은 이미 정정된 행이고
  #    **C-36 이 백엔드를 Secrets Manager 로 바꿨다**(2026-08-10 · 선생님 지시 · 4KB 한도 소멸).
  #    C-23 행의 머리말이 `🔄 정정(2026-08-10, C-36) — 백엔드가 SSM → Secrets Manager` 인데
  #    그 아래 **정정 전 본문**을 읽었다.
  #    ⇒ C-56 의 3종은 처음부터 정합했다. `secretsmanager` 엔드포인트의 소비자 = **ESO**
  #      (정본 §"엔드포인트별 사망 영향" = *"ESO 가 주기적으로 당긴다. 막히면 갱신 실패가
  #      조용하고, 파드 재기동 시점에 터진다"*). 🟢 그리고 여기 적혀 있던 **"받아들인 위험"
  #      (ESO 호출이 NAT 를 탄다)은 존재하지 않는다** — 애초에 엔드포인트로 나간다.
  #    🔴 교훈 = 정정된 결정 행은 **머리말이 본문을 이긴다.** 본문은 이력 보존용이다.
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

  # ── IRSA 롤 ARN 묶음 (정의는 여기 한 곳) ────────────────────────────────────
  # 🔴 여기에 키를 추가하면 `iam_irsa.tf` 의 `irsa_trust` for_each 에도 같은 키가 있어야 한다.
  #    (반대도 마찬가지) — 어긋나면 `outputs.tf` 의 `precondition` 이 **plan 을 죽인다.**
  #    2026-08-14 에 실제로 어긋났다: `s3_observability.tf` 가 롤 2개를 추가했는데 이 map 이
  #    7개 그대로여서 `terraform output` 이 9개 중 7개만 보여줬고, **기능이 멀쩡해서 아무도
  #    안 죽고 조용히 틀렸다.** 그 재발을 막는 것이 그 precondition 이다.
  irsa_role_arns = {
    cilium_operator  = aws_iam_role.cilium_operator.arn
    ebs_csi          = aws_iam_role.ebs_csi.arn
    external_secrets = aws_iam_role.external_secrets.arn
    karpenter        = aws_iam_role.karpenter.arn
    pipeline_bedrock = aws_iam_role.pipeline_bedrock.arn
    pg_barman        = aws_iam_role.pg_barman.arn
    pg_dump          = aws_iam_role.pg_dump.arn
    # A2(2026-08-14) — 관측 오브젝트 스토어. ns 가 `observability` 라 위 36개 SA 셈과 별개다.
    loki_s3  = aws_iam_role.loki_s3.arn
    tempo_s3 = aws_iam_role.tempo_s3.arn

    # A2 후반(2026-08-14 · C-60) — 공개 진입 ALB 의 타깃 등록자. 정의는 `alb.tf`.
    lb_controller = aws_iam_role.lb_controller.arn

    # A5-b(2026-08-16 · C-44) — 크롤 리파이너 3종 공용. 정의는 `iam_crawl_refiner.tf`.
    crawl_refiner = aws_iam_role.crawl_refiner.arn
  }

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

    # ── 공개 진입 ALB (A2 후반 · C-60) ──────────────────────────────────────
    # 🔴 **타깃그룹 ARN 이 여기로 흐르는 것이 요점이다.** config 레포는 이 값을 담을 수 없다 —
    #    ARN 에 계정 ID 가 들어가고 그 레포는 계정 ID 를 `PLACEHOLDER` 로 두는 규칙이다
    #    (`scripts/sites.yaml` 의 `eks.registry` 와 같은 이유). 게다가 apply 마다 바뀔 수 있다.
    #    ⇒ `TargetGroupBinding` 은 ArgoCD 가 아니라 **Ansible `eks_lb_controller` 가 만든다.**
    #    같은 부류의 선례 = istiod·ArgoCD 자신도 Ansible 이 세운다.
    irsa_lb_controller   = aws_iam_role.lb_controller.arn
    alb_target_group_arn = aws_lb_target_group.gateway.arn
    alb_dns_name         = aws_lb.public.dns_name
  }
}

# ── A0.5 CI 서버 (A-28) → `gitlab.yml` ────────────────────────────────────────
locals {
  ci_ansible_extra_vars = {
    ci_instance_id = aws_instance.ci.id
    ci_region      = var.region
    ci_ssm_bucket  = aws_s3_bucket.ssm_transfer.id

    # 🔴 하이픈을 뗀 형태로 넘긴다 — by-id 심볼릭 링크가 그 형식이다.
    #    실물: /dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol04db46666435e58ce
    #    ⇒ Ansible 쪽에서 replace 를 하면 그 변환 규칙이 두 곳에 살게 되므로 여기서 끝낸다.
    ci_docker_volume_serial = replace(aws_ebs_volume.ci_docker.id, "-", "")
    ci_data_volume_serial   = replace(aws_ebs_volume.ci_data.id, "-", "")

    # 🔴 감사용으로 원본 ID 도 같이 넘긴다 — 사람이 콘솔에서 대조할 때 필요하다.
    ci_docker_volume_id = aws_ebs_volume.ci_docker.id
    ci_data_volume_id   = aws_ebs_volume.ci_data.id
  }
}
