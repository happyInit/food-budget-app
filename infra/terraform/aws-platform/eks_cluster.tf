# EKS 컨트롤플레인
#
# 🔴 **이 클러스터는 기본 형상이 아니다.** C-82(Cilium ENI 모드)가 세 가지를 강제한다:
#   ① `bootstrap_self_managed_addons = false` — EKS 가 자동으로 넣는 **vpc-cni · kube-proxy · coredns**
#      를 처음부터 만들지 않는다. vpc-cni 가 있으면 Cilium 과 CNI 소유권을 다투고,
#      kube-proxy 가 있으면 `kubeProxyReplacement` 와 이중으로 iptables/eBPF 를 건다.
#   ② coredns 는 **CNI 가 뜬 뒤**에야 Ready 가 된다 ⇒ Terraform 이 아니라 **Ansible `eks.yml`**
#      이 Cilium 다음에 애드온으로 만든다(Terraform 의 aws_eks_addon 은 ACTIVE 를 기다리다 죽는다).
#   ③ 노드는 CNI 가 없는 동안 **NotReady 로 뜬다** — 정상이다. Cilium DaemonSet 이
#      hostNetwork 로 그 노드에 내려가 CNI 를 깔면 Ready 로 바뀐다.
#
# 🔴 **kube-proxy 를 안 만드는 것의 대가** = `kubeProxyReplacement` 가 실패하면 Service 가 통째로
#    죽는다. 온프렘이 같은 형상(kubeadm + kube-proxy 미설치 + Cilium 1.19.6)으로 도는 것이 근거다.

resource "aws_iam_role" "cluster" {
  name = "mp-eks-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = ["sts:AssumeRole"]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_cloudwatch_log_group" "cluster" {
  name = "/aws/eks/${var.cluster_name}/cluster"

  # 🔴 EKS 가 이 로그그룹을 자동 생성하면 **보존이 "만료 없음"** 이다. C-66 이 월 ~$59 를
  #    추정한 근거가 audit 볼륨이고, 온프렘에서 감사로그 보존창이 30일 → 52.62h 로 붕괴한
  #    전례(`1-25`)가 있다. ⇒ 보존을 명시하고 그 값이 문서와 같게 둔다.
  retention_in_days = 30

  tags = { Name = "mp-eks-audit" }
}

resource "aws_eks_cluster" "main" {
  name     = var.cluster_name
  version  = var.cluster_version
  role_arn = aws_iam_role.cluster.arn

  # 🔴 C-82 ① — 기본 애드온을 심지 않는다.
  bootstrap_self_managed_addons = false

  vpc_config {
    subnet_ids = [for az, s in aws_subnet.node : s.id]

    # C-80 = 공개 엔드포인트 + IAM(비대화형 필수). 사설도 함께 켜서 노드/파드가
    # NAT 를 왕복하지 않고 API 서버에 붙게 한다(요금·지연·NAT SPOF 노출 모두 줄어든다).
    endpoint_public_access  = true
    endpoint_private_access = true
    public_access_cidrs     = var.cluster_public_access_cidrs
  }

  access_config {
    # C-24 = **Access Entry 단독**. `API_AND_CONFIG_MAP` 을 쓰지 않는 이유 = aws-auth ConfigMap 이
    # 남아 있으면 권한 정본이 둘이 되고, 그 둘이 갈렸을 때 아무도 알아채지 못한다.
    authentication_mode = "API"

    # 🔴 `false` 다 — 클러스터를 만든 주체에게 자동으로 cluster-admin 을 주지 않는다.
    #    사람 권한은 전부 아래 eks_access.tf 의 명시적 Access Entry 로만 들어온다.
    #    ⚠️ 그래서 `cluster_admin_principals` 가 비면 **아무도 못 들어간다**(변수 설명 참조).
    bootstrap_cluster_creator_admin_permissions = false
  }

  enabled_cluster_log_types = var.cluster_log_types

  # 미확정 ⑰ 가 열려 있어 기본은 끈다(변수 설명). 온프렘 etcd 암호화 대비 후퇴분이다.
  dynamic "encryption_config" {
    for_each = var.secrets_kms_key_arn == null ? [] : [var.secrets_kms_key_arn]
    content {
      provider {
        key_arn = encryption_config.value
      }
      resources = ["secrets"]
    }
  }

  tags = { Name = var.cluster_name }

  depends_on = [
    aws_iam_role_policy_attachment.cluster,
    aws_cloudwatch_log_group.cluster,
  ]
}

# ── IRSA 의 뿌리 (C-30) ───────────────────────────────────────────────────────
# 🔴 파드 신원 = **IRSA**(C-30 이 C-24 의 "Pod Identity" 를 정정했다). Pod Identity 미채택.
#    OIDC 프로바이더가 없으면 아래 iam_irsa.tf 의 롤을 파드가 하나도 맡을 수 없다.
data "tls_certificate" "oidc" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.oidc.certificates[0].sha1_fingerprint]

  tags = { Name = "mp-eks-oidc" }
}
