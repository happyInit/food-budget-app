# 크롤 리파이너 IRSA — S3 incoming/ 읽기 + failed/ 격리 + SQS 소비 (A5-b, 2026-08-16)
#
# ── 🔴 왜 이 파일이 이 스택에 있나 ─────────────────────────────────────────────
#   운반 실물(S3 버킷·SQS 6개·업로더 IAM)은 **다른 스택**(`infra/terraform/aws`)이 만든다.
#   그런데 IRSA 는 **EKS OIDC 공급자**가 있어야 신뢰정책을 쓸 수 있고, 그건 이 스택 소유다.
#   ⇒ 크로스 스택 참조(remote state) 대신 **이름으로 참조**한다 — `backup_bucket` 이
#     이미 같은 방식이다(`variables.tf` 의 "이 스택이 만들지 않는다" 주석).
#   🔵 이름은 두 스택이 공유하는 계약이다. 저쪽 `var.bucket_name` 기본값과 아래 값이
#     같아야 한다(둘 다 `mp-crawl-ap2`). 바꿀 일이 생기면 **양쪽을 같이** 바꾼다.
#
# ── 🔴 이게 정적 키를 대체한다 ────────────────────────────────────────────────
#   `infra/terraform/aws/iam.tf` 가 `mp-crawl-refiner-onprem` 사용자를 만들면서
#   *"리파이너는 이관하면 AWS 로 가고 Pod Identity 를 받는다 → 이 키는 한시적"* 이라고
#   적어 뒀다. A5-b 에서 리파이너가 곧바로 EKS 에 서므로 **그 사용자의 액세스 키는
#   한 번도 발급되지 않는다.** 안 만드는 것이 가장 싼 회수다.
#   ⚠️ 업로더(`mp-crawl-uploader`)는 다르다 — 온프렘 크롤러는 EKS 밖이라 IRSA 를 못 쓴다.
#     그쪽은 정적 키가 불가피하고, 그래서 두 신원을 애초에 갈라 둔 것이다.

variable "crawl_bucket" {
  description = <<-EOT
    크롤 운반 버킷 (C-44). 🔴 이 스택이 만들지 않는다 — `infra/terraform/aws` 소관이다.
    IRSA 정책이 ARN 으로만 참조한다. 저쪽 `var.bucket_name` 과 **같은 값이어야 한다**.
  EOT
  type        = string
  default     = "mp-crawl-ap2"
}

variable "crawl_streams" {
  description = "SQS 큐 접미사. `infra/terraform/aws` 의 `local.streams` 키와 같아야 한다."
  type        = list(string)
  default     = ["retail", "deal", "recipe"]
}

resource "aws_iam_role" "crawl_refiner" {
  name               = "mp-crawl-refiner"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["crawl_refiner"].json
}

# 🔵 정책 본문은 `infra/terraform/aws/iam.tf` 의 `data.aws_iam_policy_document.refiner` 와
#    **의도적으로 같다.** 신원 방식만 정적 키 → IRSA 로 바뀌고 권한 범위는 그대로다.
#    (그래야 "온프렘에서 돌던 리파이너를 그대로 옮겼다" 가 참이 된다.)
resource "aws_iam_role_policy" "crawl_refiner" {
  name = "crawl-refine"
  role = aws_iam_role.crawl_refiner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 크롤러가 올린 원본을 읽는다. `incoming/` 밖은 못 본다.
        Sid      = "GetCrawlObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.crawl_bucket}/incoming/*"
      },
      {
        # 🔵 레코드 단위 영구실패는 DLQ 가 아니라 여기로 간다 — C-44 의 "DLQ 대체 = S3 failed/".
        Sid      = "QuarantineFailedRecords"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::${var.crawl_bucket}/failed/*"
      },
      {
        # 🔴 `s3:DeleteObject` 는 **주지 않는다** — 처리 끝난 객체는 라이프사이클이 지운다
        #    (incoming/ 90일). 재처리(replay) 능력을 남기는 편이 값지고 권한도 그만큼 좁다.
        #    저쪽 스택의 refiner 정책과 같은 판단이다.
        Sid    = "ConsumeQueues"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",     # 🔵 KEDA 스케일러도 이것 하나만 쓴다
          "sqs:ChangeMessageVisibility", # 큰 객체 처리 중 heartbeat (가시성 900s 연장)
        ]
        Resource = [
          for s in var.crawl_streams :
          "arn:aws:sqs:${var.region}:${data.aws_caller_identity.current.account_id}:mp-crawl-${s}"
        ]
      },
    ]
  })
}

# 🔵 ARN 은 따로 output 하지 않는다 — 이 스택은 **`outputs.tf` 의 `irsa_role_arns` 하나로**
#    모으는 설계이고, 거기에 `locals.tf` 를 통해 `crawl_refiner` 를 등록했다.
#    🔴 그 등록을 빼먹으면 `outputs.tf` 의 precondition 이 plan 을 죽인다(실측 — 이 커밋
#      작성 중 실제로 걸렸다). 롤을 늘릴 때 **iam_irsa.tf 의 trust · locals · 롤 정의 셋**을
#      함께 고치라는 뜻이고, 그 가드가 의도대로 작동한다.

# ══════════════════════════════════════════════════════════════════════════════
# KEDA SQS 스케일러 전용 롤 — 큐 깊이 조회만 (A5-b, 2026-08-16)
# ══════════════════════════════════════════════════════════════════════════════
# 🔴 **왜 위 `crawl_refiner` 를 재사용하지 않나** — 스케일러가 하는 일은
#    `sqs:GetQueueAttributes`(ApproximateNumberOfMessages) **하나**뿐이다. 리파이너 롤을
#    맡기면 KEDA 오퍼레이터가 S3 원본 읽기·격리 쓰기·**메시지 삭제**까지 갖게 된다.
#    스케일러는 데이터를 만질 이유가 없고, KEDA 는 클러스터 전역 컴포넌트라 폭발 반경도 넓다.
#
# 🔴 **왜 KEDA 자신의 신원이 필요한가 = 다른 길이 막혔다**(실측 2026-08-16).
#    KEDA 2.20 의 `identityOwner: workload` 는 오퍼레이터가 **워크로드 SA 의 토큰을 발급해**
#    그 롤을 맡는 방식인데, 이 클러스터에서는:
#        kubectl auth can-i create serviceaccounts/token \
#          --as=system:serviceaccount:keda:keda-operator -n pipeline   →  no
#    ClusterRole `keda-operator` 가 serviceaccounts 에 get/list/watch 만 준다.
#    ⇒ 차트 RBAC 을 넓히는 것보다 **최소권한 롤을 하나 더 파는 쪽이 좁다.**
#
# 🔵 큐 목록은 리파이너와 같은 `var.crawl_streams` 를 쓴다 — 큐가 늘면 양쪽이 함께 따라간다.
resource "aws_iam_role" "crawl_scaler" {
  name               = "mp-crawl-scaler"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["crawl_scaler"].json
}

resource "aws_iam_role_policy" "crawl_scaler" {
  name = "sqs-depth-only"
  role = aws_iam_role.crawl_scaler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 🔴 **이 액션 하나뿐이다.** ReceiveMessage 도 DeleteMessage 도 주지 않는다 —
        #    KEDA 가 메시지를 소비하면 리파이너가 볼 것이 사라진다(조용한 데이터 유실).
        Sid      = "ReadQueueDepth"
        Effect   = "Allow"
        Action   = ["sqs:GetQueueAttributes"]
        Resource = [
          for s in var.crawl_streams :
          "arn:aws:sqs:${var.region}:${data.aws_caller_identity.current.account_id}:mp-crawl-${s}"
        ]
      },
    ]
  })
}
