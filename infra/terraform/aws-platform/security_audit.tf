# 보안 감사 기반 — CloudTrail 버킷 · CloudTrail · GuardDuty (C-65 의 전제 · C-68)
#
# ── 이 파일이 있는 이유 = "결정은 다 있는데 실물이 0" ────────────────────────────
# C-65(보안 알림)가 **읽을 것**을 전제한다. 그런데 실측(2026-08-16)에서 계정에
#   GuardDuty 탐지기 0 · CloudTrail 0 · `mp-cloudtrail-ap2` 없음
# 이었다. 알림 배관(EventBridge→Lambda→Slack)을 아무리 잘 만들어도 **탐지원이 없으면
# 영원히 조용하고, 그 조용함이 "안전하다"로 읽힌다.** 그래서 탐지원부터 세운다.
#
# 🔵 **층이 셋이고 서로의 사각지대다**(C-65) — 하나로 못 합친다:
#     ① 워크로드   = Prometheus/Loki  → Alertmanager → `#mp-alerts`   [이 파일 밖 · 무변경]
#     ② 컨트롤플레인 = EKS audit 로그   → CloudWatch Logs             [C-66 · eks_cluster.tf]
#     ③ 계정      = CloudTrail        → S3 + EventBridge            [여기]
#     ④ 위협탐지   = GuardDuty                                       [여기]

# ══ ① CloudTrail 버킷 (C-68) ═══════════════════════════════════════════════════
#
# 🔴 **이 버킷의 목적은 하나다 — 아무도 못 지운다.** 그래서 다른 버킷과 설정이 다르다:
#    버전관리 ON + **Object Lock COMPLIANCE 90일**. COMPLIANCE 는 **루트 계정도 못 푼다**
#    (GOVERNANCE 는 `s3:BypassGovernanceRetention` 권한이 있으면 우회된다 — 침해자가
#     admin 을 쥔 국면을 상정하는 물건이므로 GOVERNANCE 는 의미가 없다).
#
# 🔴 **SSE-S3 를 쓴다. SSE-KMS 가 아니다** — C-68 이 명시적으로 정한 것이고 이유가 날카롭다:
#    SSE-KMS 면 **KMS 키를 지우는 것으로 Object Lock 이 우회**된다. 객체는 남지만 영구히
#    복호할 수 없으니 **지운 것과 결과가 같다.** SSE-S3 는 그 경로 자체가 없다.
#    🟡 포기 = *"IAM 은 통과했지만 키 정책으로 복호는 막는다"* 는 두 번째 자물쇠.
#       계정 1개·5인이라 값이 작다고 판단했다(C-68).
# 🔴 그래서 **설계도의 `CloudTrail → KMS` 화살표는 폐기된 경로다** — 그림을 고칠 것.
#
# 🔴 Object Lock 은 **버킷 생성 시에만 켤 수 있다**(`object_lock_enabled`). 나중에 못 켠다 —
#    이 버킷을 지우고 다시 만들어야 하는데, 그러면 그때까지의 감사 기록이 사라진다.
resource "aws_s3_bucket" "cloudtrail" {
  bucket              = var.cloudtrail_bucket
  object_lock_enabled = true
  tags                = { Name = var.cloudtrail_bucket, Purpose = "audit-immutable" }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 🔴 Object Lock 은 **버전관리를 요구한다** — 락은 "객체 버전" 에 걸리기 때문이다.
resource "aws_s3_bucket_versioning" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" } # 🔴 KMS 아님 — 위 머리말
  }
}

# 🔴 **90일은 "지울 수 없는 창" 이지 보존 기간이 아니다.** 락이 풀린 뒤에도 객체는 남는다 —
#    삭제는 아래 lifecycle 이 한다. 둘을 같은 값으로 두면 "락 풀리자마자 삭제" 가 되어
#    조사 여유가 0 이므로, 만료는 **400일**로 넉넉히 잡는다(연 단위 조사 대응).
resource "aws_s3_bucket_object_lock_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = 90
    }
  }
  depends_on = [aws_s3_bucket_versioning.cloudtrail]
}

# 🔵 계층 전환으로 비용을 낮춘다. 🔴 단 **90일 이전 삭제는 Object Lock 이 거부**하므로
#    만료는 반드시 락 기간보다 길어야 한다(여기 400일). 짧게 두면 lifecycle 이 매일
#    삭제를 시도하고 매번 거부당한다 — 동작은 안전하지만 로그만 시끄러워진다.
resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  rule {
    id     = "audit-tiering"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
    expiration { days = 400 }
    # 🔵 버전관리가 켜져 있으므로 **비현행 버전도 정리**해야 한다. 안 하면 덮어쓴 흔적이
    #    영원히 쌓인다(CloudTrail 은 같은 키를 덮어쓰지 않지만, 규칙이 없으면 미래의 실수를 못 막는다).
    noncurrent_version_expiration { noncurrent_days = 400 }
  }
}

# CloudTrail 이 이 버킷에 쓸 수 있게 하는 버킷 정책 — AWS 가 요구하는 고정 형식이다.
# 🔴 `aws:SourceArn` 조건이 **혼동된 대리인(confused deputy)** 을 막는다. 없으면 남의 계정
#    트레일이 우리 버킷에 쓰도록 유도될 수 있다.
data "aws_iam_policy_document" "cloudtrail_bucket" {
  statement {
    sid     = "AWSCloudTrailAclCheck"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = [aws_s3_bucket.cloudtrail.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.region}:${data.aws_caller_identity.current.account_id}:trail/${var.cloudtrail_name}"]
    }
  }

  statement {
    sid     = "AWSCloudTrailWrite"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.region}:${data.aws_caller_identity.current.account_id}:trail/${var.cloudtrail_name}"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  policy = data.aws_iam_policy_document.cloudtrail_bucket.json
}

# ══ ② CloudTrail ═══════════════════════════════════════════════════════════════
#
# 🔴 **멀티리전이어야 한다.** 우리 자원은 ap-northeast-2 에 있지만, 침해자는 **감시가 없는
#    리전에서** 자원을 만든다(크립토마이닝의 고전적 수법). 단일리전 트레일은 그걸 못 본다.
#    비용은 거의 안 오른다 — 다른 리전엔 활동이 없으므로 이벤트가 안 생긴다.
# 🔵 **관리 이벤트만** 기록한다. 데이터 이벤트(S3 오브젝트 단위 · Lambda 호출)는 켜지 않는다 —
#    우리 S3 트래픽은 크롤 객체라 **볼륨이 곧 비용**인데 보안 가치는 낮다(GuardDuty S3
#    Protection 이 이상행위 쪽을 본다). 필요해지면 그때 켠다.
# 🔵 `include_global_service_events` = IAM·STS 처럼 리전이 없는 서비스의 이벤트.
#    🔴 이게 꺼지면 **"누가 AssumeRole 했는가" 가 통째로 안 남는다** — 이 프로젝트에서
#       IRSA·STS 가 자격증명의 중심이라 가장 중요한 축이다.
resource "aws_cloudtrail" "main" {
  name                          = var.cloudtrail_name
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true # 🔴 다이제스트 파일로 **사후 변조 탐지**. 켜는 비용 0.

  tags = { Name = var.cloudtrail_name }

  # 🔴 버킷 정책이 먼저 붙어야 트레일 생성이 통과한다(AWS 가 생성 시점에 쓰기 권한을 검증한다).
  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

# ══ ③ GuardDuty ════════════════════════════════════════════════════════════════
#
# 🔵 GuardDuty 는 CloudTrail·VPC Flow·DNS 로그를 **자기가 알아서** 읽는다 — 우리가 그 로그를
#    켜 두거나 넘겨줄 필요가 없다(그래서 위 CloudTrail 과 중복이 아니다. CloudTrail 은
#    *기록*이고 GuardDuty 는 *판단*이다).
# 🔴 **EKS Protection = C-66 과 같은 손잡이다.** GuardDuty 가 EKS 감사로그를 보려면
#    컨트롤플레인 `audit` 로깅이 켜져 있어야 한다 — C-66 이 그걸 켠 이유의 절반이 이것이다.
#    (나머지 절반은 `1-26` = "누가 Secret 을 읽었는지" 를 남기는 것.)
# 🔵 Malware Protection 은 켜지 않는다 — EBS 스냅샷을 떠서 스캔하는 물건이라 비용 축이 다르고,
#    우리 워크로드는 컨테이너 이미지가 ECR 스캔 대상이라 층이 겹친다.
resource "aws_guardduty_detector" "main" {
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES" # 🔴 기본 6시간은 대응 지연이 너무 크다

  tags = { Name = "mp-guardduty" }
}

# 🔵 기능은 **별도 리소스**로 켠다 — 구 `datasources {}` 인라인 블록은 프로바이더 6.x 에서
#    deprecated 다(terraform validate 경고). 리소스로 갈리면 기능별로 켜고 끄는 이력이 남는다.
resource "aws_guardduty_detector_feature" "s3_data_events" {
  detector_id = aws_guardduty_detector.main.id
  name        = "S3_DATA_EVENTS"
  status      = "ENABLED" # 크롤 버킷·백업 버킷의 이상 접근
}

# 🔴 **C-66 과 같은 손잡이다.** 이게 의미를 가지려면 EKS 컨트롤플레인 `audit` 로깅이 켜져 있어야
#    한다 — C-66 이 audit 를 켠 이유의 절반이 이것이고(나머지 절반은 `1-26` "누가 Secret 을
#    읽었는지"), 그래서 감사 완전성과 이 기능의 비용이 함께 움직인다.
resource "aws_guardduty_detector_feature" "eks_audit_logs" {
  detector_id = aws_guardduty_detector.main.id
  name        = "EKS_AUDIT_LOGS"
  status      = "ENABLED"
}

# 🔵 EBS 스냅샷을 떠서 스캔하는 물건이라 **비용 축이 다르고**, 우리 워크로드는 컨테이너 이미지가
#    ECR 스캔 대상이라 층이 겹친다. 끄는 것이 의도다.
resource "aws_guardduty_detector_feature" "ebs_malware" {
  detector_id = aws_guardduty_detector.main.id
  name        = "EBS_MALWARE_PROTECTION"
  status      = "DISABLED"
}
