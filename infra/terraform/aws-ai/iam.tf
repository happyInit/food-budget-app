# 실행 역할 — 🔵 **AI 파트가 직접 만든다. 우회가 아니라 설계된 경로다.**
#
# 권한요청서를 쓸 때는 *"인프라가 역할을 만들고 AI 는 PassRole 만 받는다"*(A안)를 전제했는데,
# 실측해 보니 **이미 그럴 필요가 없다**(2026-08-17 `simulate-principal-policy`):
#
#     iam:CreateRole      (iam:PermissionsBoundary = mp-ai-boundary 조건)   allowed
#     iam:PutRolePolicy · iam:AttachRolePolicy · iam:TagRole                 allowed
#     iam:PassRole        (iam:PassedToService = lambda.amazonaws.com)      allowed
#
# 🔴 그리고 경계(`infra/iam/mp-ai/mp-ai-boundary.json`)에 **`ec2:CreateNetworkInterface` 가
#    이미 들어 있다.** 이건 **VPC Lambda 를 전제하고 설계했다**는 뜻이다. 즉 우리가 역할을
#    만드는 것은 «권한을 비집고 들어가는 것» 이 아니라 그 설계가 의도한 사용법이다.
#    (`docs/mp_aws_team_access.md §4` — "경계가 붙으면 실효 권한 = 경계 ∩ 정책 이라 천장을
#     못 넘고, **그 안에서는 자유롭다**")
#
# 🔴 **경계 밖은 적어도 무효다.** 아래 인라인 정책은 전부 경계 안에서만 쓴다:
#      RuntimeCommon      logs · bedrock · ecr · ec2 네트워크인터페이스        (Resource *)
#      RuntimeOwnResources s3:* · sqs:* · lambda:InvokeFunction · secretsmanager:GetSecretValue
#                          → **`mp-ai-*` / `mp-ai/*` 안에서만**
#    ⚠️ 그래서 `mp/prod/*` 시크릿은 **이 역할들이 못 읽는다.** 배치 5종이 PG 비밀번호를 쓰려면
#       `mp-ai/*` 로 따로 넣어야 한다(관리자 몫이 아니라 **우리 몫**이다 — dev 정책이
#       `secretsmanager:*` 를 `secret:mp-ai/*` 에 준다).

locals {
  create_roles = length(var.exec_role_arns) == 0

  # 🔵 만들면 이 이름, 받으면 넘겨받은 ARN. 아래 lambda.tf 는 이것만 본다.
  role_arns = local.create_roles ? {
    for k, r in aws_iam_role.exec : k => r.arn
  } : var.exec_role_arns

  boundary_arn = "arn:aws:iam::${data.aws_caller_identity.me.account_id}:policy/${var.boundary_policy_name}"

  role_names = ["batch", "api", "worker", "scheduler"]
}

data "aws_caller_identity" "me" {}

data "aws_iam_policy_document" "assume" {
  for_each = local.create_roles ? toset(local.role_names) : toset([])

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type = "Service"
      # 🔴 스케줄러 역할만 주체가 다르다 — Lambda 가 맡는 역할이 아니라
      #    **스케줄러가 맡아서 Lambda 를 부르는** 역할이다.
      identifiers = [each.key == "scheduler" ? "scheduler.amazonaws.com" : "lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "exec" {
  for_each = local.create_roles ? toset(local.role_names) : toset([])

  name               = "mp-ai-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.assume[each.key].json

  # 🔴 **이게 빠지면 `iam:CreateRole` 자체가 거부된다.** dev 정책이 경계 조건부로 허용한다 —
  #    없으면 *"AdministratorAccess 붙인 역할을 만들어 Lambda 에 넘기는"* 권한 상승이 되기 때문이다.
  permissions_boundary = local.boundary_arn

  tags = { Project = "mp-ai" }
}

# ── 공통: 로그 + VPC ENI ─────────────────────────────────────────────────────
# 🔴 VPC Lambda 는 ENI 3종이 **없으면 함수가 아예 안 뜬다**(INIT 전에 실패한다).
#    관리형 정책 `AWSLambdaVPCAccessExecutionRole` 과 같은 내용을 인라인으로 둔다 —
#    경계 안에 있는 것만 쓴다는 것을 눈으로 확인할 수 있게.
data "aws_iam_policy_document" "common" {
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:${data.aws_caller_identity.me.account_id}:log-group:/aws/lambda/mp-ai-*"]
  }
  statement {
    actions = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces",
    "ec2:DeleteNetworkInterface"]
    # 🔵 ENI 는 리소스 수준 제한이 성립하지 않는다(만들기 전엔 ARN 이 없다). 경계가 천장이다.
    resources = ["*"]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:*:${data.aws_caller_identity.me.account_id}:secret:mp-ai/*"]
  }
}

data "aws_iam_policy_document" "role" {
  for_each = local.create_roles ? toset(local.role_names) : toset([])

  source_policy_documents = [data.aws_iam_policy_document.common.json]

  # 접수 — 큐에 넣고 업로드한다(읽지 않는다)
  dynamic "statement" {
    for_each = each.key == "api" ? [1] : []
    content {
      actions   = ["sqs:SendMessage", "sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
      resources = [for q in aws_sqs_queue.jobs : q.arn]
    }
  }
  dynamic "statement" {
    for_each = each.key == "api" ? [1] : []
    content {
      # `PutObject` = 인라인 업로드 · presigned PUT 서명은 **호출 권한이 아니라 서명자의 권한**을 쓴다
      # `GetObject` = presigned 뒤 `head_object` 로 «정말 올라왔나» 확인
      actions   = ["s3:PutObject", "s3:GetObject"]
      resources = ["${aws_s3_bucket.uploads.arn}/*"]
    }
  }

  # 워커 — 큐에서 꺼내고 원본을 읽고 지운다
  dynamic "statement" {
    for_each = each.key == "worker" ? [1] : []
    content {
      # 🔴 이 셋이 **이벤트 소스 매핑의 전제**다. 하나만 빠져도 매핑이 Disabled 로 떨어지는데
      #    그 실패는 «워커가 조용히 안 도는» 모양이라 알아채기 어렵다.
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      resources = [for q in aws_sqs_queue.jobs : q.arn]
    }
  }
  dynamic "statement" {
    for_each = each.key == "worker" ? [1] : []
    content {
      actions   = ["s3:GetObject", "s3:DeleteObject"] # 개인정보 — 끝나면 지운다
      resources = ["${aws_s3_bucket.uploads.arn}/*"]
    }
  }

  # 배치 — Bedrock(리뷰 요약·감성·챗 refine)
  dynamic "statement" {
    for_each = each.key == "batch" ? [1] : []
    content {
      actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = ["*"] # 🔵 모델 ARN 제한은 경계가 아니라 별건이다(C-56 축과 다름)
    }
  }

  # 스케줄러 — 함수를 부르는 것만
  dynamic "statement" {
    for_each = each.key == "scheduler" ? [1] : []
    content {
      actions   = ["lambda:InvokeFunction"]
      resources = ["arn:aws:lambda:*:${data.aws_caller_identity.me.account_id}:function:mp-ai-*"]
    }
  }
}

resource "aws_iam_role_policy" "exec" {
  for_each = local.create_roles ? toset(local.role_names) : toset([])

  name   = "mp-ai-${each.key}-inline"
  role   = aws_iam_role.exec[each.key].id
  policy = data.aws_iam_policy_document.role[each.key].json
}
