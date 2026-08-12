# 🔴 정적 IAM 키는 체크리스트 "열린 항목 ③" 이 지목한 **이 설계의 유일한 보안 후퇴**다.
#    온프렘은 EKS 밖이라 IRSA·Pod Identity 를 못 쓴다. 그래서 범위를 좁히는 것으로 갚는다.
#
# 역할을 둘로 가른 이유 = **수명이 다르다**.
#   uploader       크롤은 이관 후에도 온프렘 상시 프로덕션이다(C-3) → 이 키는 **영구**
#   refiner-onprem 리파이너는 이관하면 AWS 로 가고 Pod Identity 를 받는다 → 이 키는 **한시적**
#   한 키에 합치면 "이관 당일 무엇을 지워야 하는가"가 아무 데도 안 적힌다. 이름에 -onprem 을
#   박아 그 답을 자격증명 자체에 새긴다.
#
# 🔴 액세스 키(비밀)는 Terraform 이 만들지 않는다.
#    aws_iam_access_key 를 쓰면 **비밀이 tfstate 에 평문으로 들어간다.** state 는
#    mp-backup-ap2 에 있고 그 버킷은 버전관리조차 못 켠 상태다(../backend.tf) —
#    장기 자격증명을 거기 두는 건 후퇴를 넓히는 짓이다.
#    키 발급은 apply 이후 수동 1회(`aws iam create-access-key`)로 하고 ESO 로 배달한다. 절차는 README.

resource "aws_iam_user" "uploader" {
  name = "mp-crawl-uploader"
  tags = { Lifetime = "permanent", Site = "onprem" }
}

resource "aws_iam_user" "refiner_onprem" {
  name = "mp-crawl-refiner-onprem"
  tags = { Lifetime = "until-migration", Site = "onprem" }
}

# 업로더 = incoming/ 에 쓰기만. 읽기도 목록도 삭제도 없다.
# 버킷 목록(ListBucket)이 필요 없는 이유 = 업로드는 항상 정확한 키로 PutObject 한다.
data "aws_iam_policy_document" "uploader" {
  statement {
    sid       = "PutCrawlObjects"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.crawl.arn}/${local.incoming_prefix}*"]
  }
}

# 리파이너 = incoming/ 읽기 + failed/ 쓰기 + 큐 소비.
# 🔴 DeleteObject 는 **주지 않는다** — 처리 끝난 객체는 수명주기가 지운다. 재처리(replay) 능력을
#    남겨두는 것이 더 값지고, 권한도 그만큼 좁아진다.
data "aws_iam_policy_document" "refiner" {
  statement {
    sid       = "GetCrawlObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.crawl.arn}/${local.incoming_prefix}*"]
  }

  statement {
    sid       = "QuarantineFailedRecords"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.crawl.arn}/${local.failed_prefix}*"]
  }

  statement {
    sid    = "ConsumeQueues"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",   # KEDA 스케일러도 이것만 쓴다
      "sqs:ChangeMessageVisibility", # 긴 객체 처리 중 heartbeat
    ]
    resources = [for k, _ in local.streams : aws_sqs_queue.stream[k].arn]
  }
}

resource "aws_iam_user_policy" "uploader" {
  name   = "mp-crawl-uploader"
  user   = aws_iam_user.uploader.name
  policy = data.aws_iam_policy_document.uploader.json
}

resource "aws_iam_user_policy" "refiner_onprem" {
  name   = "mp-crawl-refiner-onprem"
  user   = aws_iam_user.refiner_onprem.name
  policy = data.aws_iam_policy_document.refiner.json
}
