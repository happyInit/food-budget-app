# 대시보드 EC2 (C-84) — Operations AI + FinOps 공용, docs/operations-ai-aws-migration-plan.md
#
# 🔴 이 파일은 예전에 aws-platform 스택 안에 있었다 — 팀 IAM 구조(infra/iam/mp-dashboard/*)가
#    별도 apply 주체(mp-dashboard-dev/-ops/-guardrails)·별도 state 버킷으로 이미 분리돼 있는 게
#    확인돼 이 스택으로 옮겼다. VPC·서브넷·SG 는 aws-platform 소유라 여기서는 data 조회만 한다
#    (data.tf) — 이 스택이 실수로 그 리소스를 만들거나 지울 수 없다(SG·서브넷 변경은
#    mp-dashboard-guardrails 의 DenyChangingTheNetwork 가 애초에 explicit Deny).

# ── SG 인바운드 2줄 — SG 자체(mp-sg-dashboard)는 aws-platform 이 만든다 ──────────
# 🔴 description은 ASCII만 허용된다 — 한글은 terraform plan에서는 안 잡히고 apply의 API
#    호출 시점에 실패한다. 한글 설명은 주석으로 옮긴다.
# 없으면: 80 없음 → Let's Encrypt HTTP-01 발급·갱신 실패 / 8011 없음 → Alertmanager
# webhook이 조용히 안 옴(Operations의 입력 경로 자체).
#
# 🔴 provider = aws.no_default_tags 필수 — provider.tf 주석 참고. 기본 provider 를 쓰면
#    default_tags 가 자동으로 실려서 AuthorizeSecurityGroupIngress 호출 자체가 막힌다.
resource "aws_vpc_security_group_ingress_rule" "dashboard_http" {
  provider          = aws.no_default_tags
  security_group_id = data.aws_security_group.dashboard.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "Lets Encrypt HTTP-01 issuance and renewal"
}

resource "aws_vpc_security_group_ingress_rule" "dashboard_alertmanager_webhook" {
  provider                     = aws.no_default_tags
  security_group_id            = data.aws_security_group.dashboard.id
  referenced_security_group_id = data.aws_security_group.eks_node.id
  ip_protocol                  = "tcp"
  from_port                    = 8011
  to_port                      = 8011
  description                  = "EKS Alertmanager to operations-api webhook"
}

# ── IAM Role / Instance Profile ──────────────────────────────────────────────
# 🔴 EC2 1대에는 Instance Profile이 1개만 붙는다 — Operations(Bedrock)와 FinOps(GCP WIF 등) 권한을
#    분리할 수 없다. FinOps 컨테이너가 뚫리면 Bedrock 권한도 같이 넘어간다는 대가를 감수한다.
#
# 🔴🔴 permissions_boundary 필수 — `mp-dashboard-dev` 정책의 `InstanceRoleWithBoundaryOnly` Sid 가
#    `iam:CreateRole` 을 **`iam:PermissionsBoundary == mp-dashboard-boundary` 조건이 있을 때만**
#    허용한다(infra/iam/mp-dashboard/mp-dashboard-dev.json). 이 인자를 빼면 apply 가 그 자리에서
#    AccessDenied 로 죽는다 — 예전 aws-platform 안의 코드와 다른 팀원이 준 코드 둘 다 이게 빠져 있었다.
data "aws_iam_policy_document" "dashboard_ec2_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dashboard" {
  name                 = "mp-dashboard-ec2"
  assume_role_policy   = data.aws_iam_policy_document.dashboard_ec2_trust.json
  permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/mp-dashboard-boundary"
}

resource "aws_iam_instance_profile" "dashboard" {
  name = "mp-dashboard-ec2"
  role = aws_iam_role.dashboard.name
}

# Bedrock 권한 — mp-dashboard-boundary 의 RuntimeCommon 이 InvokeModel 을 이미 허용하므로
# 이 role 정책과의 교집합으로 실제 사용 가능해진다(경계는 상한일 뿐 그 자체로는 권한을 주지 않는다).
resource "aws_iam_role_policy" "dashboard_bedrock" {
  name = "bedrock-invoke-nova"
  role = aws_iam_role.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "BedrockInvokeNova"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = var.bedrock_model_arns
    }]
  })
}

# RCA/챗봇 응답의 Contextual Grounding Check용 Guardrail 관리 권한.
# docs/operations-ai-bedrock-guardrail-rag-permission-request.md 에서 검토·확정된 범위 그대로다.
# 🔴 팀장 리뷰로 정정(원래 버전은 5개 액션에 aws:RequestTag/Name 조건을 통째로 걸었었다) —
# aws:RequestTag 는 요청이 실제로 태그를 실어 보낼 때만 존재하는 조건 키다. CreateGuardrail
# 은 생성 시 태그를 실어 보내므로 성립하지만, Update/Get/Delete/CreateGuardrailVersion 은
# 이미 있는 리소스를 ARN 으로 가리키는 호출이라 태그를 안 실어 보낸다 — 없는 키에
# StringLike 를 걸면 조용히 매칭 실패해 implicit deny 로 떨어진다(SsmSendCommand 건과
# 같은 부류). 기존 리소스 대상 액션은 aws:ResourceTag/Name(리소스에 이미 붙은 태그)로 봐야
# ABAC 가 성립한다. Bedrock guardrail 은 태깅 가능한 리소스라 ResourceTag 를 지원한다.
resource "aws_iam_role_policy" "dashboard_bedrock_guardrail" {
  name = "mp-operations-bedrock-guardrail"
  role = aws_iam_role.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GuardrailCreate"
        Effect = "Allow"
        # 🔴 bedrock:TagResource 추가(2026-08-16) — create-guardrail --tags 가 내부적으로
        #    별도 TagResource 호출을 하는데, 이게 없으면 AccessDeniedException(TagResource on
        #    guardrail/*)으로 CreateGuardrail 자체가 실패한다(실측). simulate-principal-policy
        #    로는 미리 안 잡혔다 — API 내부에서 발생하는 2차 호출이라 그렇다.
        Action = ["bedrock:CreateGuardrail", "bedrock:TagResource"]
        # 🔴 `guardrail/*` 로 좁히면 **안 된다** — `bedrock:CreateGuardrail` 은 리소스 단위
        #    권한을 지원하지 않는 액션이라, Resource 를 좁히는 순간 문장이 아예 매칭되지 않고
        #    implicit deny 로 떨어진다(2026-08-16 실측: apply 후 이 액션만 막혔다).
        #    `simulate-custom-policy` 로 변수 분리해 확정한 결과 —
        #      Resource "*" + 구체 guardrail ARN 지정 → implicitDeny  (액션이 그 리소스 타입에 안 붙음)
        #      Resource "*" + 리소스 미지정          → allowed
        #    ⇒ 범위 제한은 Resource 가 아니라 **아래 태그 조건**이 한다. 대조군으로 검증했다
        #      (`aws:RequestTag/Name=someone-else` → implicitDeny). AWS 표준 tag-on-create 패턴.
        #    🔴 생성 시 태그를 실제로 달아야 통과한다 — 안 달면 CreateGuardrail 자체가 AccessDenied:
        #      aws bedrock create-guardrail --name mp-operations-rca --tags key=Name,value=mp-operations-rca
        #    같은 이유로 `GuardrailManageExisting` 쪽은 반대다 — 그것들은 기존 리소스를 ARN 으로
        #    가리키는 호출이라 Resource 를 좁힐 수 있고, 조건도 `aws:ResourceTag` 여야 한다.
        Resource = "*"
        Condition = {
          StringLike = {
            "aws:RequestTag/Name" = "mp-operations-*"
          }
        }
      },
      {
        Sid    = "GuardrailManageExisting"
        Effect = "Allow"
        Action = [
          "bedrock:CreateGuardrailVersion",
          "bedrock:UpdateGuardrail",
          "bedrock:GetGuardrail",
          "bedrock:DeleteGuardrail",
        ]
        Resource = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:guardrail/*"
        Condition = {
          StringLike = {
            "aws:ResourceTag/Name" = "mp-operations-*"
          }
        }
      },
      {
        Sid      = "GuardrailList"
        Effect   = "Allow"
        Action   = "bedrock:ListGuardrails"
        Resource = "*"
      },
      {
        Sid      = "GuardrailApply"
        Effect   = "Allow"
        Action   = "bedrock:ApplyGuardrail"
        Resource = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:guardrail/*"
      },
    ]
  })
}

# EC2 시작/배포 시 MNG 노드 Private IP를 조회해 cluster-proxy의 upstream을 자동 갱신하는 데 필요
# (kubecost NodePort와 Prometheus NodePort 둘 다 같은 조회를 씀). boundary 의 ec2:Describe* 범위 안.
resource "aws_iam_role_policy" "dashboard_describe_instances" {
  name = "describe-mng-nodes"
  role = aws_iam_role.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DescribeMngNodes"
      Effect   = "Allow"
      Action   = ["ec2:DescribeInstances"]
      Resource = "*"
    }]
  })
}

# 🔴 수동 정책 대신 AWS 관리형 정책을 쓴다 — SSM Agent 핵심 권한(Session Manager 포함)을
#    이 정책 하나가 커버한다. boundary 의 RuntimeCommon(ssmmessages:*·ec2messages:*)과 교집합.
resource "aws_iam_role_policy_attachment" "dashboard_ssm" {
  role       = aws_iam_role.dashboard.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ── 애플리케이션 런타임 권한 ──────────────────────────────────────────────────
# 🔴 ECR 은 의도적으로 뺐다 — EC2에서 소스를 직접 빌드해 docker compose로 띄운다
#    (operations-ai-aws-migration-plan.md §4 확정: "ECR을 쓰지 않는다"). 다른 팀원이 준 코드에
#    ECR pull 정책이 붙어 있었는데, 그건 이 결정 이전의 초판 계획(docs/aws-dashboard-ec2-
#    deployment-plan.md, SUPERSEDED)을 따른 것으로 보인다 — 지금 정본과 어긋나서 넣지 않는다.
#    (참고로 mp-dashboard-boundary 의 RuntimePullImages Sid 는 ECR pull 을 "상한"으로는 허용해
#    두었지만, 이 role 자체의 정책에 ECR action 을 안 넣으면 교집합상 실제로는 막힌다 — 그래서
#    boundary 를 건드리지 않고도 "ECR 안 씀" 결정이 안전하게 지켜진다.)

# Secrets Manager mp/prod/dashboard/* — PostgreSQL 비밀번호·CA 등
resource "aws_iam_role_policy" "dashboard_secrets_read" {
  name = "secrets-dashboard-read"
  role = aws_iam_role.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SecretsDashboardRead"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:mp/prod/dashboard/*"
    }]
  })
}

# SSM Parameter Store /mp/dashboard/* — Kubecost NodePort, 캐시 TTL 등 일반 설정
resource "aws_iam_role_policy" "dashboard_ssm_params_read" {
  name = "ssm-params-dashboard-read"
  role = aws_iam_role.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SsmParamsDashboardRead"
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
      Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/mp/dashboard/*"
    }]
  })
}

# FinOps 빠른 비용 조회 — Cost Explorer·CloudWatch. boundary 의 RuntimeCommon 범위 안(ce:Get*·pricing 제외).
#
# 🔴🔴 Athena·Glue 는 여기 없다 — 넣어도 동작하지 않는다. mp-dashboard-boundary 의 RuntimeCommon 이
#    athena:*·glue:* 를 아예 포함하지 않아서, 이 role 에 아무리 허용을 붙여도 경계와의 교집합이
#    비어 실질 권한이 안 생긴다(explicit Deny 가 아니라 "경계가 허용 안 함"으로 조용히 막히는
#    형태라 더 위험 — 배포 뒤에야 AccessDenied 로 드러난다). operations-ai-aws-migration-plan.md
#    §2 표의 "AWS 실제 비용 = CUR S3 + Athena" 경로는 **지금 이 role 로는 못 만든다.**
#    mp-dashboard-ops(운영자 개인 프로필)에는 AthenaAndGlueCatalog Sid 로 이미 있으므로,
#    당장은 "사람이 직접 Athena 콘솔/CLI로 조회" 또는 "boundary 갱신"둘 중 하나가 선행돼야 한다 —
#    임의로 boundary 를 넓히지 않는다(팀 확인 필요).
resource "aws_iam_role_policy" "dashboard_finops_cost_read" {
  name = "finops-cost-read"
  role = aws_iam_role.dashboard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "FinOpsCostRead"
      Effect = "Allow"
      Action = [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast",
        "ce:GetDimensionValues",
        "ce:GetTags",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
      ]
      Resource = "*"
    }]
  })
}

# 🔴 기존 finops-dashboard-resource-read 정책(EC2/EBS/EKS/ElastiCache Describe 등)을
#    이 Role에 attach한다. EC2에는 Role이 1개만 붙으므로 "FinOpsDashboardReadOnlyRole을
#    Instance Profile에 연결"은 기술적으로 불가능하다 — 대신 기존 정책을 이 Role에 attach.
# ⚠️ ARN은 실제 정책이 이 계정에 생성된 뒤 확정한다 — 지금은 var로 비워두고 apply 전 반드시 채운다.
resource "aws_iam_role_policy_attachment" "dashboard_finops_read" {
  count      = var.finops_dashboard_resource_read_policy_arn == "" ? 0 : 1
  role       = aws_iam_role.dashboard.name
  policy_arn = var.finops_dashboard_resource_read_policy_arn
}

# ── EC2 인스턴스 ──────────────────────────────────────────────────────────────
resource "aws_eip" "dashboard" {
  domain = "vpc"
  tags   = { Name = "mp-eip-dashboard" }
}

resource "aws_instance" "dashboard" {
  ami                    = data.aws_ami.al2023_x86.id
  instance_type          = "t3.medium"
  subnet_id              = data.aws_subnet.dashboard.id # AZ-a — NAT와 같은 AZ (AZ간 전송비 회피)
  vpc_security_group_ids = [data.aws_security_group.dashboard.id]
  iam_instance_profile   = aws_iam_instance_profile.dashboard.name

  # bridge 컨테이너 → IMDS는 홉을 하나 더 지난다. hop limit 1이면 Bedrock·Cost Explorer·
  # DescribeInstances·GCP WIF 전부 실패한다.
  # 🔴 CI 서버(mp-ci-server)는 일부러 1로 뒀다(컨테이너가 IMDS에 닿으면 안 되는 반대 설계) —
  #    그대로 베끼면 안 된다. 대가 = 컨테이너 하나 뚫리면 인스턴스 권한 전부가 넘어간다
  #    → 컨테이너 non-root 실행을 반드시 같이 적용한다(compose 쪽 책임).
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 강제
    http_put_response_hop_limit = 2
  }

  # 🔴 명시적으로 암호화 — 이 EC2는 런타임 비밀·설정이 내려오는 서버라 계정 기본 EBS
  #    암호화 설정에 의존하지 않고 코드로 강제한다.
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true
  }

  # 🔴🔴 이 태그가 없으면 launch 자체가 막힌다 — mp-dashboard-guardrails 의
  #    DenyLaunchWithoutDashboardTag 가 RequestTag/Component != finops-dashboard 를 explicit Deny.
  #    이후 관리(중지·재시작·태그 변경 등)도 mp-dashboard-dev 의 ManageOwnInstances 가 이 태그
  #    조건으로 걸려 있어 계속 필요하다.
  tags = {
    Name      = "mp-dashboard"
    Component = "finops-dashboard"
  }
}

resource "aws_eip_association" "dashboard" {
  instance_id   = aws_instance.dashboard.id
  allocation_id = aws_eip.dashboard.id
}
