# 스트림별 큐 + DLQ. 구 Kafka 토픽 3종(retail.crawl.raw · retail.deal.raw · recipe.crawl.raw)의 대체물.
#
# 🔴 전달 단위가 바뀐다: Kafka 는 **레코드 1건 = 메시지 1건**이었지만 여기서는
#    **객체 1개(= 크롤 1회분 N건) = 메시지 1건**이다. 그래서 재전달의 폭발 반경이 다르다 —
#    Kafka 는 최대 COMMIT_EVERY(200)건 재처리였는데 여기선 객체 전체(컬리 3,300여 건)다.
#    적재 SQL 이 전부 `on conflict do nothing` 이라 재처리 자체는 무해하다(멱등).
resource "aws_sqs_queue" "dlq" {
  for_each = local.streams

  name                      = "mp-crawl-${each.key}-dlq"
  message_retention_seconds = 1209600 # 14일(최대) — 주말을 끼고 죽어도 증거가 남아야 한다
}

resource "aws_sqs_queue" "stream" {
  for_each = local.streams

  name = "mp-crawl-${each.key}"

  # 객체 1개를 다 처리할 시간. 컨슈머가 진행 중 heartbeat(ChangeMessageVisibility)로 연장하므로
  # 이 값은 "파드가 죽은 걸 알아채기까지의 지연"이다. 크롤이 하루 단위라 15분이면 충분하다.
  visibility_timeout_seconds = 900

  message_retention_seconds = 1209600 # 14일 — 리파이너가 며칠 멈춰도 크롤분이 사라지지 않는다
  receive_wait_time_seconds = 20      # long polling — 빈 수신(=요금·CPU)을 줄인다

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    # 3회 실패하면 DLQ 로 보낸다. 여기 걸리는 것은 "객체 단위 실패"(다운로드 불가·파일 파손)다 —
    # 레코드 단위 영구실패는 컨슈머가 S3 failed/ 로 격리하고 메시지는 정상 삭제한다.
    maxReceiveCount = 3
  })
}

# S3 가 이 큐로 알림을 보낼 수 있게 한다. SourceArn 으로 **우리 버킷만** 허용 —
# 계정 내 다른 버킷이 이 큐를 오염시킬 수 없다.
resource "aws_sqs_queue_policy" "allow_s3" {
  for_each = local.streams

  queue_url = aws_sqs_queue.stream[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Notification"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.stream[each.key].arn
      Condition = {
        ArnLike      = { "aws:SourceArn" = aws_s3_bucket.crawl.arn }
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}
