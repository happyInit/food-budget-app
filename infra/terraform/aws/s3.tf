data "aws_caller_identity" "current" {}

# 크롤 운반 버킷. 객체 키 규약:
#   incoming/<stream>/<source>/<yyyy-mm-dd>/<run-id>.jsonl
#   failed/<stream>/<source>/<yyyy-mm-dd>/<run-id>/<seq>.json
#     stream ∈ retail|deal|recipe  → 큐 3개와 1:1 (= 구 Kafka 토픽)
#     source ∈ kurly|oasis|10k     → 구 Kafka 메시지 헤더 `source` 와 1:1
#     run-id = <UTC타임스탬프>-<파드이름>  → Job 까지 역추적된다
resource "aws_s3_bucket" "crawl" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_public_access_block" "crawl" {
  bucket                  = aws_s3_bucket.crawl.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "crawl" {
  bucket = aws_s3_bucket.crawl.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3. KMS 는 요청당 과금이 붙는데 여기 데이터는 공개 상품가라 등급이 안 맞는다
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "crawl" {
  bucket = aws_s3_bucket.crawl.id

  rule {
    id     = "incoming-expire"
    status = "Enabled"
    filter { prefix = local.incoming_prefix }
    expiration { days = var.incoming_expire_days }
  }

  rule {
    id     = "failed-expire"
    status = "Enabled"
    filter { prefix = local.failed_prefix }
    expiration { days = var.failed_expire_days }
  }

  # 업로드가 중간에 죽으면 조각이 남아 조용히 과금된다(수명주기 없이는 영구히).
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# S3 → SQS. 스트림별 prefix 로 갈라 큐 3개로 보낸다.
# ⚠️ prefix 가 서로 겹치면 S3 가 알림 설정 자체를 거부한다 — incoming/retail/ · incoming/deal/ ·
#    incoming/recipe/ 는 서로의 prefix 가 아니라 안전하다.
resource "aws_s3_bucket_notification" "crawl" {
  bucket = aws_s3_bucket.crawl.id

  dynamic "queue" {
    for_each = local.streams
    content {
      id            = "mp-crawl-${queue.key}"
      queue_arn     = aws_sqs_queue.stream[queue.key].arn
      events        = ["s3:ObjectCreated:*"]
      filter_prefix = "${local.incoming_prefix}${queue.key}/"
    }
  }

  # 큐 정책이 먼저 있어야 S3 가 "보낼 수 있는지" 검증을 통과한다.
  depends_on = [aws_sqs_queue_policy.allow_s3]
}
