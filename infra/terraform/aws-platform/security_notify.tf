# 보안 알림 배관 — EventBridge → Lambda → Slack `#mp-security` (C-65)
#
# 탐지원(CloudTrail·GuardDuty)은 `security_audit.tf` 가 세운다. 여기는 **나르는 쪽**이다.
#
# 🔴 **Alertmanager 를 안 거치는 이유는 편의가 아니라 순환 의존이다**(C-65) — 이 경로가 나르는
#    사건은 *계정/클러스터가 이미 이상한 국면*이라, 알림 경로가 방어 대상 안에 있으면
#    같이 죽거나 침해자가 끌 수 있다. **경로는 분리 · 창구(Slack)는 통합.**
# 🟢 경로 A(Prometheus/Loki → Alertmanager → `#mp-alerts`)는 **한 줄도 안 바뀐다.**

# ══ ① Lambda 패키지 ════════════════════════════════════════════════════════════
# 🔵 의존성 0(표준 라이브러리 + 런타임 내장 boto3)이라 레이어·빌드 파이프라인이 필요 없다.
#    보안 경로에 빌드 단계를 얹지 않는 것 자체가 방어다 — 고장 지점이 줄어든다.
data "archive_file" "security_notifier" {
  type        = "zip"
  source_dir  = "${path.module}/lambda/security_notifier"
  output_path = "${path.module}/.build/security_notifier.zip"
}

# ══ ② 실행 롤 ══════════════════════════════════════════════════════════════════
data "aws_iam_policy_document" "security_notifier_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "security_notifier" {
  name               = "mp-security-notifier"
  assume_role_policy = data.aws_iam_policy_document.security_notifier_assume.json
}

# 🔴 권한을 **웹훅 하나 · 로그그룹 하나**로 묶는다. 이 Lambda 는 계정 전역 이벤트를 보지만
#    *읽고 쓰는 것*은 그 둘뿐이다 — 침해자가 이 롤을 쥐어도 가져갈 것이 없어야 한다.
data "aws_iam_policy_document" "security_notifier" {
  statement {
    sid       = "ReadSlackWebhook"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:${var.security_slack_secret_name}-*"]
  }

  # 🔵 Logs Insights 보강용. `StartQuery` 는 로그그룹 ARN 으로 좁히고, 결과 조회 계열은
  #    쿼리 ID 기반이라 리소스로 좁힐 수 없다(AWS 제약) — 대신 액션을 최소로 둔다.
  statement {
    sid       = "EnrichFromAuditLogs"
    actions   = ["logs:StartQuery"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${var.cluster_name}/cluster:*"]
  }
  statement {
    sid       = "EnrichPollResults"
    actions   = ["logs:GetQueryResults", "logs:StopQuery"]
    resources = ["*"]
  }

  # 자기 로그
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/mp-security-notifier:*"]
  }
}

resource "aws_iam_role_policy" "security_notifier" {
  name   = "mp-security-notifier"
  role   = aws_iam_role.security_notifier.id
  policy = data.aws_iam_policy_document.security_notifier.json
}

# ══ ③ Lambda ═══════════════════════════════════════════════════════════════════
resource "aws_lambda_function" "security_notifier" {
  function_name    = "mp-security-notifier"
  role             = aws_iam_role.security_notifier.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"] # C-29 와 같은 이유 — arm 이 싸다. 의존성 0 이라 아치 제약도 없다
  filename         = data.archive_file.security_notifier.output_path
  source_code_hash = data.archive_file.security_notifier.output_base64sha256

  # 🔴 Logs Insights 왕복(최대 20초)을 감당해야 한다. 짧으면 **보강이 아니라 알림이 죽는다.**
  timeout     = 60
  memory_size = 256

  environment {
    variables = {
      SLACK_SECRET_NAME = var.security_slack_secret_name
      AUDIT_LOG_GROUP   = "/aws/eks/${var.cluster_name}/cluster"
      ENRICH_WINDOW_S   = "900" # ±15분 (C-65)
    }
  }

  tags = { Name = "mp-security-notifier" }
}

# 🔴 보존 기간을 **명시**한다 — Lambda 로그그룹은 기본이 무기한이라, 안 적으면 조용히 쌓인다
#    (C-66 이 EKS 로그그룹에서 같은 함정을 지적했다).
resource "aws_cloudwatch_log_group" "security_notifier" {
  name              = "/aws/lambda/${aws_lambda_function.security_notifier.function_name}"
  retention_in_days = 30
}

# ══ ④ EventBridge 규칙 ═════════════════════════════════════════════════════════

# ── ④-a GuardDuty finding 전량 ────────────────────────────────────────────────
# 🔵 **severity 로 거르지 않는다.** 이 채널은 조용한 것이 정상이라 저심각 finding 이 와도
#    소음이 되지 않고, 반대로 "낮음" 으로 분류된 것이 침해의 첫 신호인 경우가 흔하다.
#    등급 표시는 Lambda 가 아이콘으로 한다.
resource "aws_cloudwatch_event_rule" "guardduty" {
  name          = "mp-security-guardduty"
  description   = "GuardDuty finding → #mp-security (C-65)"
  event_pattern = jsonencode({ source = ["aws.guardduty"], detail-type = ["GuardDuty Finding"] })
}

resource "aws_cloudwatch_event_target" "guardduty" {
  rule      = aws_cloudwatch_event_rule.guardduty.name
  target_id = "security-notifier"
  arn       = aws_lambda_function.security_notifier.arn
}

resource "aws_lambda_permission" "guardduty" {
  statement_id  = "AllowGuardDutyRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.security_notifier.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.guardduty.arn
}

# ── ④-b 콘솔 로그인 (특히 root) ───────────────────────────────────────────────
# 🔴 **root 로그인은 그 자체가 사건이다** — 평시 운영에 root 를 쓸 일이 없다(C-24 로 사람 접근은
#    IAM 사용자 + Access Entry). MFA 미사용 로그인도 같이 잡는다.
# 🔵 이 규칙이 **MFA 트랙(다음 작업)의 관측 장치**이기도 하다 — MFA 를 강제하기 전에
#    "누가 MFA 없이 들어오는가" 가 먼저 보여야 한다.
resource "aws_cloudwatch_event_rule" "console_signin" {
  name        = "mp-security-console-signin"
  description = "콘솔 로그인(root·MFA 미사용 포함) → #mp-security"
  event_pattern = jsonencode({
    source      = ["aws.signin"],
    detail-type = ["AWS Console Sign In via CloudTrail"]
  })
}

resource "aws_cloudwatch_event_target" "console_signin" {
  rule      = aws_cloudwatch_event_rule.console_signin.name
  target_id = "security-notifier"
  arn       = aws_lambda_function.security_notifier.arn
}

resource "aws_lambda_permission" "console_signin" {
  statement_id  = "AllowSigninRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.security_notifier.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.console_signin.arn
}

# ── ④-c A-33 월 1회 합성 점검 ─────────────────────────────────────────────────
# 🔴 **이것이 "조용함" 을 해석 가능하게 만든다.** 보안 채널은 조용한 것이 정상인데, 그러면
#    *정상적으로 조용한 것*과 *죽어서 조용한 것*이 구분되지 않는다. C-65 가 스스로 적은
#    대가("Lambda 는 단일 실패점이고 그 실패는 조용하다")를 받는 장치다.
resource "aws_cloudwatch_event_rule" "synthetic" {
  name                = "mp-security-synthetic"
  description         = "A-33 월 1회 합성 점검 — 경로가 살아 있는지 스스로 증명한다"
  schedule_expression = "cron(0 0 1 * ? *)" # 매월 1일 00:00 UTC (09:00 KST)
}

resource "aws_cloudwatch_event_target" "synthetic" {
  rule      = aws_cloudwatch_event_rule.synthetic.name
  target_id = "security-notifier"
  arn       = aws_lambda_function.security_notifier.arn
  input     = jsonencode({ source = "mp.synthetic" })
}

resource "aws_lambda_permission" "synthetic" {
  statement_id  = "AllowSyntheticRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.security_notifier.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.synthetic.arn
}

# ══ ⑤ A-32 알람 2종 — Lambda 자체의 고장을 잡는다 ══════════════════════════════
#
# 🔴 **순환 의존을 인지하고 받아들인다.** 이 알람의 목적지(SNS)는 결국 사람에게 닿아야 하는데,
#    Lambda 가 완전히 죽으면 Lambda 경유 통지도 죽는다. 그 전면 사망은 **A-33 합성 점검**이 받고,
#    여기 알람은 **부분 고장**(간헐 예외·스로틀)을 잡는다. 둘의 역할이 다르다.
# ⚠️ 완전 독립 경로가 필요하면 SNS 에 **AWS Chatbot 또는 이메일 구독**을 붙인다 —
#    Chatbot 은 Slack OAuth 라 콘솔 승인이 필요해 IaC 밖이다(C-65 가 Email 은 미채택).
resource "aws_sns_topic" "security_alarms" {
  name = "mp-security-alarms"
  tags = { Name = "mp-security-alarms" }
}

resource "aws_sns_topic_subscription" "security_alarms_to_lambda" {
  topic_arn = aws_sns_topic.security_alarms.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.security_notifier.arn
}

resource "aws_lambda_permission" "sns_alarms" {
  statement_id  = "AllowAlarmSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.security_notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.security_alarms.arn
}

resource "aws_cloudwatch_metric_alarm" "notifier_errors" {
  alarm_name          = "mp-security-notifier-errors"
  alarm_description   = "보안 알림 Lambda 가 예외로 실패했다 — 알림이 조용히 사라지는 중일 수 있다"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.security_notifier.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching" # 호출이 없는 것은 정상이다(조용한 채널)
  alarm_actions       = [aws_sns_topic.security_alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "notifier_throttles" {
  alarm_name          = "mp-security-notifier-throttles"
  alarm_description   = "보안 알림 Lambda 가 스로틀됐다 — 이벤트 폭주(=사건 진행 중)일 수 있다"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.security_notifier.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security_alarms.arn]
}
