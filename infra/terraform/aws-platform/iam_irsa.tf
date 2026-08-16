# IRSA 롤 — 파드 신원 (C-30 이 C-24 의 "Pod Identity" 를 정정 · Pod Identity 미채택)
#
# 🔴 **`StringEquals` + `sub` 리스트로 쓴다.** `StringLike` + `mp-*` 로 쓰면
#    pipeline ns 의 SA 22개가 전부 그 롤을 맡을 수 있게 되어 **`0-14c`(워크로드별 SA 36개)를
#    통째로 되돌린다.** 그 항목의 산출물은 "SA 를 나눈 것" 이 아니라 **"33개엔 롤을 안 붙인 것"** 이다.
#
# 🔴 아래 9개가 IRSA 롤 **전부**다(2026-08-14 — 관측 2종 + LB 컨트롤러 1종 추가. 종전 6개).
#    config #161 이 만든 app/pipeline SA 36개 중 롤을 받는 것은 3개뿐이고 나머지 33개는
#    의도적으로 비어 있다. 관측 2종·LB 컨트롤러는 그 36개와 **별개 ns** 라 이 셈에 안 든다.
#
# 🔴 **여기에 키를 더하면 `locals.irsa_role_arns` 에도 같은 키를 더해야 한다** —
#    안 그러면 `outputs.tf` 의 precondition 이 plan 을 죽인다(그게 그 가드의 목적이다).

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

    # ── A5-b 크롤 리파이너 3종 (2026-08-16) ──────────────────────────────────
    # 🔴 **`infra/terraform/aws` 의 `mp-crawl-refiner-onprem` IAM 사용자를 대신한다.**
    #    그 파일 주석이 이미 예고했다 — *"리파이너는 이관하면 AWS 로 가고 Pod Identity 를
    #    받는다 → 이 키는 **한시적**"*. 여기가 그 시점이라 **정적 키를 아예 발급하지 않는다**
    #    (그 사용자는 액세스 키가 없는 채로 남는다 — 안 만드는 것이 곧 회수다).
    # 🔵 **롤 하나에 SA 셋** — `pipeline_bedrock`(SA 2개)과 같은 선례다. 큐별로 롤을 가르면
    #    더 좁지만, 원 설계(`aws/iam.tf` 의 refiner 정책)가 한 신원에 3큐를 준 형태라
    #    사이트별로 권한 모델이 갈리는 대가가 더 크다고 봤다.
    #    ⚠️ 대가 = retail 리파이너가 recipe 큐도 **읽을 수는 있다**. 실제로 읽지는 않는다 —
    #      `MP_SQS_URL` 이 큐를 못박고 그 값은 매니페스트에 워크로드별로 적힌다.
    crawl_refiner = [
      "system:serviceaccount:pipeline:mp-retail-refiner",
      "system:serviceaccount:pipeline:mp-recipe-refiner",
      "system:serviceaccount:pipeline:mp-deal-notifier",
    ]

    # ── 관측 오브젝트 스토어 2종 (A2, 2026-08-14) ─────────────────────────────
    # SA 이름의 정본은 **라이브 실측**이다 — `observability` ns 의 `loki`·`tempo` SA 가
    # 이미 `eks.amazonaws.com/role-arn` 으로 아래 롤 이름을 가리키고 있다(config 소관).
    # 롤이 없어서 그 어노테이션이 허공을 가리키던 상태였다. 정책·버킷 = `s3_observability.tf`
    loki_s3  = ["system:serviceaccount:observability:loki"]
    tempo_s3 = ["system:serviceaccount:observability:tempo"]

    # ── 공개 진입 ALB (A2 후반, 2026-08-14 · C-60) ────────────────────────────
    # 🔴 이름이 `aws-load-balancer-controller` 인데 **LB 를 만들 권한이 없다** — 정책은
    #    `TargetGroupBinding` 에 필요한 등록/해제뿐이다(근거 = `alb.tf` 롤 주석).
    #    SA 이름은 차트 기본값이고 Ansible `eks_lb_controller` 롤이 그 이름으로 만든다.
    lb_controller = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
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

          # 🔴 **이걸 빼먹으면 ENI 할당이 통째로 안 된다** (2026-08-13 실측 · 결함 #16):
          #   level=warn  "Unable to retrieve EC2 route table list" … UnauthorizedOperation:
          #               not authorized to perform: ec2:DescribeRouteTables
          #   level=warn  "Unable to synchronize infrastructure"
          #   level=fatal "Unable to start eni allocator" error="Initial synchronization
          #               with instances API failed"
          # ⇒ operator CrashLoop → 에이전트 `required=2 available=0` → **파드 IP 0개**.
          #
          # 🔴 왜 필요한가 = Cilium 은 서브넷의 **라우팅**을 봐야 파드를 붙일 서브넷을 판단한다.
          #    우리 형상에서 특히 중요하다 — RT 가 **3개**(공개·노드·데이터 격리)이고
          #    데이터 티어는 *"밖으로 나가는 경로 없음"*(§1)이다. 라우트 테이블을 못 읽으면
          #    Cilium 은 그 구분을 할 수 없다.
          #
          # ⚠️ 이 정책은 **문서를 읽어서 만든 목록이었고 그래서 하나 빠졌다.** 돌려 보기 전까지
          #    빠진 줄 몰랐고, `plan`·`validate` 로는 알 수 없는 부류다(IAM 은 문법이 맞았다).
          "ec2:DescribeRouteTables",
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

# ── ③ ESO (🔴 **C-36** · AWS Secrets Manager) ────────────────────────────────
# 명세 출처 = config `bootstrap/eso/README.md`.
# ⟳ **2026-08-13 정정 (결함 #24)** — 원래 `ssm:GetParameter` 로 지었다. **C-23 이 아니라 C-36 이
#    정본**이다: *"비밀 = AWS Secrets Manager. C-23 의 SSM Parameter Store 를 정정한다
#    (ESO provider `service: SecretsManager`)"* (2026-08-10 · 선생님 지시 · 4KB 한도 소멸).
# 🔴 `secretsmanager:ListSecrets` 를 **넣지 않는다** — `dataFrom.find` 사용이 실측 0건이고,
#    넣으면 "경로 아래 전부 나열"이 가능해져 `prefix: mp/prod/` 로 얻은 경계가 약해진다.
#    (`dataFrom.extract` 는 키를 명시하므로 ListSecrets 가 필요 없다 — argocd 배포키가 그 형태다.)
resource "aws_iam_role" "external_secrets" {
  name               = "mp-external-secrets"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["external_secrets"].json
}

resource "aws_iam_role_policy" "external_secrets" {
  name = "secrets-read"
  role = aws_iam_role.external_secrets.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      # 🔴 **와일드카드가 필수다** — Secrets Manager 는 ARN 끝에 6자 랜덤 접미사를 붙인다
      #    (`secret:mp/prod/app-secrets-AbCdEf`). 이름을 정확히 박으면 **영원히 매치되지 않는다.**
      Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:mp/prod/*"
    }]
  })
  # ⚠️ `kms:Decrypt` 를 **아직 넣지 않는다** — 미결 ⑰(CMK $1/키 vs AWS 관리형 $0)이 미해결이고,
  #    기본 키 `aws/secretsmanager` 로 만들면 IAM 추가 없이 읽히는지 **실측으로 판정**한다.
  #    🔴 CMK 로 가면 IAM 허용만으로는 부족하다 — **A-26**(KMS 키 정책에 이 롤 ARN 명시)이 선행이다.
  #    🟢 되돌릴 수 있는 선택이다: `update-secret --kms-key-id` 로 나중에 CMK 로 옮긴다
  #      (SSM advanced 티어처럼 편도가 아니다).
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
        # 🔴 **`StringLike` 가 아니라 `StringLikeIfExists` 다** — 결함 #49(2026-08-14 실측).
        #    barman 은 `barman-cloud-check-wal-archive` 에서 **HeadBucket** 을 부르는데,
        #    그 호출엔 `s3:prefix` 키가 **아예 없다.** IAM 에서 조건 키가 없으면 `StringLike` 는
        #    **거짓**이므로 통째로 거부된다 — 실측 로그:
        #      ERROR: Barman cloud WAL archive check exception:
        #             An error occurred (403) when calling the HeadBucket operation: Forbidden
        #    ⇒ WAL 아카이빙이 전량 실패한다(`pg_stat_archiver.failed_count` 만 오른다).
        #    🟢 `IfExists` = "키가 있으면 검사하고, 없으면 통과". 즉 **프리픽스를 주는 목록 호출은
        #      여전히 `pg-eks/`·`pg/` 로 묶이고**(예: `harbor/` 목록은 계속 거부), 프리픽스가
        #      없는 HeadBucket 만 통과한다. 조건을 아예 빼는 것보다 좁다.
        #    ⚠️ 대가 = 프리픽스 없는 `ListObjectsV2` 도 통과한다(버킷 전체 **키 이름** 열람).
        #      객체 **내용**은 위 두 Statement 로 `pg-eks/*`·`pg/*` 에 묶여 있어 못 읽는다.
        Sid      = "ListBucketScoped"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.backup_bucket}"
        Condition = {
          StringLikeIfExists = { "s3:prefix" = ["pg-eks/*", "pg/*"] }
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
        # 🔴 위 `ListBucketScoped` 와 **같은 이유로** `IfExists` 다(결함 #49).
        #    ⚠️ 이쪽은 아직 실측으로 터지지 않았다 — barman 처럼 HeadBucket 을 부르는지
        #      확인되지 않았다. 그래도 같은 함정이 같은 모양으로 놓여 있어 함께 걷는다
        #      (A-47 덤프가 A3 에서 처음 도는데, 그때 403 으로 만나면 원인 찾기가 또 길어진다).
        Sid      = "ListOwnPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.pg_dump_bucket}"
        Condition = {
          StringLikeIfExists = { "s3:prefix" = ["aws/*"] }
        }
      },
    ]
  })
  # 🔴 **`mp-backup-ap2` 를 주지 않는다** — 장애 도메인 분리가 C-18·C-69 의 요지다.
  #    한 버킷이 사람 실수로 지워질 때 두 트랙이 함께 죽으면 2트랙의 의미가 없다.
}

data "aws_caller_identity" "current" {}
