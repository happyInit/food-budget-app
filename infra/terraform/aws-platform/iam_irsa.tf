# IRSA 롤 — 파드 신원 (C-30 이 C-24 의 "Pod Identity" 를 정정 · Pod Identity 미채택)
#
# 🔴 **`StringEquals` + `sub` 리스트로 쓴다.** `StringLike` + `mp-*` 로 쓰면
#    pipeline ns 의 SA 22개가 전부 그 롤을 맡을 수 있게 되어 **`0-14c`(워크로드별 SA 36개)를
#    통째로 되돌린다.** 그 항목의 산출물은 "SA 를 나눈 것" 이 아니라 **"33개엔 롤을 안 붙인 것"** 이다.
#
# 🔴 아래 6개가 IRSA 롤 **전부**다. config #161 이 만든 SA 36개 중 롤을 받는 것은 3개뿐이고
#    나머지 33개는 의도적으로 비어 있다.

locals {
  oidc_arn  = aws_iam_openid_connect_provider.eks.arn
  oidc_host = replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")
}

# 신뢰정책 생성기 — SA 목록을 받아 `sub` 를 리스트로 넣는다.
data "aws_iam_policy_document" "irsa_trust" {
  for_each = {
    cilium_operator = ["system:serviceaccount:kube-system:cilium-operator"]
    ebs_csi         = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    # 출처 = config `bootstrap/eso/README.md` — 온프렘 helm release ns 와 같다.
    external_secrets = ["system:serviceaccount:external-secrets:external-secrets"]
    karpenter        = ["system:serviceaccount:kube-system:karpenter"]

    # ── A-47 3종 ────────────────────────────────────────────────────────────
    pipeline_bedrock = [
      "system:serviceaccount:pipeline:mp-score-review-sentiment",
      "system:serviceaccount:pipeline:mp-summarize-reviews",
    ]
    pg_barman = ["system:serviceaccount:data:pg"]
    pg_dump   = ["system:serviceaccount:data:mp-pg-onsite-dump"]
  }

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = each.value # 🔴 리스트다 — 와일드카드가 아니다
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# ── ① Cilium operator — ENI IPAM (C-82) ───────────────────────────────────────
# 🔴 이 권한을 **노드 롤에 붙이지 않는 것**이 요점이다(eks_nodegroup.tf 주석).
#    붙이면 그 노드의 모든 파드가 ENI 를 만들 수 있고, IMDS hop limit 1 로 막아 둔 의미가 사라진다.
resource "aws_iam_role" "cilium_operator" {
  name               = "mp-cilium-operator"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["cilium_operator"].json
}

resource "aws_iam_role_policy" "cilium_operator" {
  name = "eni-ipam"
  role = aws_iam_role.cilium_operator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DescribeForIPAM"
        Effect = "Allow"
        Action = [
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeTags",
        ]
        Resource = "*" # Describe* 는 리소스 한정이 불가한 액션들이다
      },
      {
        Sid    = "ManageENI"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:AttachNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:ModifyNetworkInterfaceAttribute",
          "ec2:AssignPrivateIpAddresses",
          "ec2:UnassignPrivateIpAddresses",
          "ec2:CreateTags",
        ]
        Resource = "*"
      },
    ]
  })
}

# ── ② EBS CSI (C-16) ─────────────────────────────────────────────────────────
resource "aws_iam_role" "ebs_csi" {
  name               = "mp-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["ebs_csi"].json
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

# ── ③ ESO (C-23 · SSM ParameterStore) ────────────────────────────────────────
# 명세 출처 = config `bootstrap/eso/README.md`.
# 🔴 `ssm:GetParametersByPath` 를 **넣지 않는다** — `dataFrom.find` 사용이 실측 0건이고,
#    넣으면 "경로 아래 전부 나열"이 가능해져 `prefix: /mp/prod/` 로 얻은 경계가 약해진다.
resource "aws_iam_role" "external_secrets" {
  name               = "mp-external-secrets"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["external_secrets"].json
}

resource "aws_iam_role_policy" "external_secrets" {
  name = "ssm-read"
  role = aws_iam_role.external_secrets.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParameters"]
      Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/mp/prod/*"
    }]
  })
  # ⚠️ SecureString 을 쓰면 `kms:Decrypt` 가 추가로 필요하다 — 키 선택이 미결 ⑥ 이라 지금은 넣지 않는다.
  #    (AWS 관리 키 `alias/aws/ssm` 이면 그 ARN, CMK 면 그 ARN.)
}

# ── ④ A-47: 파이프라인 Bedrock ────────────────────────────────────────────────
resource "aws_iam_role" "pipeline_bedrock" {
  name               = "mp-pipeline-bedrock"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["pipeline_bedrock"].json
}

resource "aws_iam_role_policy" "pipeline_bedrock" {
  name = "invoke-model"
  role = aws_iam_role.pipeline_bedrock.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = var.bedrock_model_arns
    }]
  })
}

# ── ⑤ A-47: PG barman → S3 (C-51 페일백 고려) ────────────────────────────────
resource "aws_iam_role" "pg_barman" {
  name               = "mp-pg-barman"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["pg_barman"].json
}

resource "aws_iam_role_policy" "pg_barman" {
  name = "barman-s3"
  role = aws_iam_role.pg_barman.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # AWS 쪽 프리픽스 = 읽기·쓰기. `0-23`/`0-30` 이 경로를 사이트별로 갈라 놓았다(config #148).
        Sid      = "AwsPrefixReadWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
        Resource = "arn:aws:s3:::${var.backup_bucket}/pg-eks/*"
      },
      {
        # 🔴 온프렘 프리픽스는 **읽기만**이다 — C-51(페일백)에서 온프렘 체인을 읽어야 하지만,
        #    쓰기를 주면 AWS 쪽 사고가 **온프렘 WAL 체인을 오염시킬 수 있다**.
        Sid      = "OnpremPrefixReadOnly"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.backup_bucket}/pg/*"
      },
      {
        Sid      = "ListBucketScoped"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.backup_bucket}"
        Condition = {
          StringLike = { "s3:prefix" = ["pg-eks/*", "pg/*"] }
        }
      },
    ]
  })
}

# ── ⑥ A-47: 논리 덤프 → 별 버킷 ──────────────────────────────────────────────
resource "aws_iam_role" "pg_dump" {
  name               = "mp-pg-dump"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["pg_dump"].json
}

resource "aws_iam_role_policy" "pg_dump" {
  name = "dump-s3"
  role = aws_iam_role.pg_dump.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 🔴 **`s3:DeleteObject` 를 주지 않는다** — 미결 ㉕ 해소(2026-08-13)로 보존을 **라이프사이클**이
        #    맡기로 했다(C-79 · 190일). 컨테이너가 지우는 `mc rm --older-than 7d` 를 eks 에서 걷는 것이
        #    그 결정의 절반이고(`A-49`), 권한을 안 주는 것이 나머지 절반이다.
        Sid      = "PutDumpOnly"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = "arn:aws:s3:::${var.pg_dump_bucket}/aws/*"
      },
      {
        Sid      = "ListOwnPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.pg_dump_bucket}"
        Condition = {
          StringLike = { "s3:prefix" = ["aws/*"] }
        }
      },
    ]
  })
  # 🔴 **`mp-backup-ap2` 를 주지 않는다** — 장애 도메인 분리가 C-18·C-69 의 요지다.
  #    한 버킷이 사람 실수로 지워질 때 두 트랙이 함께 죽으면 2트랙의 의미가 없다.
}

data "aws_caller_identity" "current" {}
