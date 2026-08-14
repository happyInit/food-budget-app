# 관리형 노드그룹 — C-45(2대 시작) · C-29(`m7g.xlarge` · AZ 당 1대) · C-16(루트 60GiB)
#
# 🔴 여기는 **층1(고정)** 이다. 층2(버스트) = Karpenter → `karpenter.tf` + Ansible `eks_karpenter`
#    (A-12 채택 확정 = C-87). `A-19` 의 "노드그룹 2층" 중 이 파일이 아래층이다.
#
# 🔴 **Cilium 과 순서 문제가 있다 — README "2단 apply" 를 먼저 읽을 것.** C-82 로 CNI 가 없으므로
#    노드는 부팅 후 **NotReady** 로 남는다. MNG 는 노드가 클러스터에 *등록*되면 ACTIVE 가 되지만,
#    Ready 까지 기다리는 국면이 있으면 `NodeCreationFailure` 로 약 20분 뒤 실패한다.
#    ⇒ 안전한 순서 = **클러스터 → Cilium → 노드그룹**(README 절차).

resource "aws_iam_role" "node" {
  name = "mp-eks-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = ["sts:AssumeRole"]
    }]
  })
}

# 🔴 `AmazonEKS_CNI_Policy` 를 **붙이지 않는다** — 그 정책은 vpc-cni 용이고 우리는 Cilium 이다(C-82).
#    Cilium 이 필요한 EC2 권한은 **cilium-operator 의 IRSA 롤**로 준다(iam_irsa.tf) —
#    노드 롤에 붙이면 그 노드의 **모든** 파드가 ENI 를 만들 수 있게 되고, hop limit 1 로
#    IMDS 를 막아 둔 의미가 사라진다.
resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    # ECR pull. 🔴 리포는 계정 안에 있으므로 read-only 로 충분하다 — push 는 CI(GitLab EC2)가 한다.
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

# ── 런치 템플릿 ───────────────────────────────────────────────────────────────
# 🔴 `user_data` 를 쓰지 않는다 — AL2023 은 nodeadm(MIME multipart) 형식이고, 직접 쓰면
#    MNG 가 자동으로 넣어 주는 부트스트랩을 **덮어써서** 노드가 클러스터에 붙지 못한다.
#    필요한 것(EBS·IMDS)은 전부 런치 템플릿 필드로 표현되므로 user_data 가 필요 없다.
#
# 🔴 **max-pods 를 지정하지 않는 것도 의도다.** EKS 기본 계산식이
#    `(ENI 4 × (IPv4 15 - 1)) + 2 = 58` 이고, 그것이 정본 §1 의 "max-pods 58/노드" 와 같은 값이다.
#    실측 파드 36 이라 천장이 아니다. ⇒ 손으로 넣으면 두 정본이 생긴다.
resource "aws_launch_template" "node" {
  name_prefix = "mp-eks-node-"

  vpc_security_group_ids = [aws_security_group.node.id]

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = var.node_root_volume_gib
      volume_type = "gp3"
      encrypted   = true
      # 🔴 KMS 키를 지정하지 않으면 계정 기본 키(`aws/ebs`, AWS 관리형) = **$0** 이다.
      #    미확정 ⑰(CMK vs 관리형)와 같은 축이지만, 암호화 자체는 나중에 켤 수 없는 부류라 켠다.
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 강제

    # 🔴 **1 = 파드가 IMDS 에 닿지 못한다.** `0-17` 이 경고한 *"IMDS 를 통한 노드 IAM 롤 탈취"*
    #    경로를 구조로 끊는다. 파드 신원은 IRSA(C-30)이므로 IMDS 가 필요 없다.
    #    ⚠️ 대가 = IMDS 를 기대하는 서드파티 파드는 **조용히 실패하지 않고 즉시 실패**한다(그게 낫다).
    http_put_response_hop_limit = 1
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "mp-eks-node" }
  }

  # ENI 태그 — Cilium 이 만드는 ENI 에는 이 태그가 안 붙는다(Cilium 이 따로 붙인다).
  # 여기 것은 **1차 ENI** 용이다.
  tag_specifications {
    resource_type = "network-interface"
    tags          = { Name = "mp-eks-node-primary" }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_eks_node_group" "main" {
  # 🔴 **`count` 는 "2단 apply" 를 config 에 새긴 것이다** — `-target` 이 아니다.
  #    `-target` 은 의존성만 끌어와 네트워크·IRSA·SQS·SG 를 빼먹고, 그러면
  #    `output "ansible_extra_vars_json"` 을 못 뽑아 Ansible 로 넘어갈 수 없다.
  #    근거·절차 = `variables.tf` 의 `create_node_group` · README "2단 apply".
  count = var.create_node_group ? 1 : 0

  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "mp-mng-general"
  node_role_arn   = aws_iam_role.node.arn

  # 🔴 노드는 **노드 전용 서브넷**에만 (C-33 · 선생님 지시 "EKS 노드는 별도 서브넷").
  #    ENI 모드에서 파드 IP 도 이 서브넷에서 나온다.
  subnet_ids = [for az, s in aws_subnet.node : s.id]

  # arm64. 🔴 `AL2023_x86_64_STANDARD` 로 잘못 두면 m7g 에서 인스턴스가 아예 안 뜬다.
  ami_type       = "AL2023_ARM_64_STANDARD"
  instance_types = [var.node_instance_type]
  capacity_type  = "ON_DEMAND" # Spot 미채택 — CLAUDE.md(C-29): 우리가 사는 건 CPU 가 아니라 메모리다

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_desired_size
    max_size     = var.node_max_size
  }

  # 🔴 노드 2대에서 `max_unavailable = 1` 은 **롤링 중 절반이 빠진다**는 뜻이다.
  #    C-85 가 경고한 *"MNG 롤링 업그레이드로 노드가 동시에 교체되면 대시보드 조회가 끊긴다"* 가
  #    바로 이 국면이다 ⇒ 1 로 못박아 **동시 교체를 금지**한다(기본값도 1 이지만 명시가 기록이다).
  update_config {
    max_unavailable = 1
  }

  launch_template {
    id      = aws_launch_template.node.id
    version = aws_launch_template.node.latest_version
  }

  lifecycle {
    # 🔴 desired_size 를 무시한다 — 사람이 급할 때 콘솔/CLI 로 늘린 대수를
    #    다음 apply 가 조용히 되돌리면 안 된다(온프렘에서 HPA·stateful 때문에
    #    ArgoCD selfHeal 을 끈 것과 같은 판단 — [[argocd-sync-policy-tiers]]).
    ignore_changes = [scaling_config[0].desired_size]
  }

  tags = { Name = "mp-mng-general" }

  # 🔴 **리허설(2026-08-13 · `terraform graph`)에서 잡은 결함** — 이 블록이 없으면 노드그룹이
  #    `aws_subnet.node` 만 기다리고 **NAT 기본 경로·라우트 연결·S3 엔드포인트·컨트롤플레인
  #    인바운드 규칙을 기다리지 않는다.** 그러면 첫 apply 에서:
  #      ① 노드가 아웃바운드 없이 부팅 → pause·기타 부트스트랩 이미지 pull 실패
  #         → `NodeCreationFailure: Instances failed to join the kubernetes cluster` (약 20분 타임아웃)
  #      ② 붙어도 컨트롤플레인 → kubelet(10250) 이 막혀 `kubectl logs/exec`·웹훅이 죽는다
  #    Terraform 은 참조가 없으면 **병렬로** 만들기 때문에 "될 때도 있고 안 될 때도 있는" 플레이크가 된다.
  #    ⇒ 순서를 명시한다. 이 depends_on 이 이 파일에서 가장 중요한 5줄이다.
  depends_on = [
    aws_iam_role_policy_attachment.node,
    aws_route.node_default,                                      # NAT 아웃바운드
    aws_route_table_association.node,                            # 그 경로가 실제로 붙는다
    aws_vpc_endpoint.s3,                                         # ECR 레이어가 S3 로 빠진다
    aws_vpc_security_group_ingress_rule.node_from_control_plane, # 웹훅·kubectl logs
    aws_vpc_security_group_ingress_rule.node_self,               # 파드 간 통신(ENI 모드)
  ]
}
