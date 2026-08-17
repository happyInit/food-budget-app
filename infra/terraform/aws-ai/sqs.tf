# 접수 → 워커 큐. 🔴 형상은 `../aws/sqs.tf`(크롤 큐)를 그대로 따른다 — 이미 검증된 값이다.
#
# 🔵 **이미지는 큐에 안 실린다.** SQS 본문 상한 256KB < 영수증 사진(1600px JPEG, 200~500KB).
#    큐에는 좌표(`bucket`/`key`)만 흐르고 실물은 S3 에 있다 — `docs/serverless/07_…§2`.

resource "aws_sqs_queue" "dlq" {
  for_each = toset(local.queue_names)

  name                      = "mp-ai-${each.key}-jobs-dlq"
  message_retention_seconds = 1209600 # 14일 — 사람이 월요일에 봐도 남아 있어야 한다
}

resource "aws_sqs_queue" "jobs" {
  for_each = toset(local.queue_names)

  name = "mp-ai-${each.key}-jobs"

  # 🔴 **가시성 타임아웃 ≥ 함수 타임아웃.** 짧으면 워커가 아직 도는 중에 메시지가 다시 보이고
  #    **같은 잡을 두 개가 동시에** 처리한다(유료 모델 호출이 두 배). 여유를 두고 함수의 2배.
  visibility_timeout_seconds = each.key == "video" ? 300 : 240
  message_retention_seconds  = 345600 # 4일
  receive_wait_time_seconds  = 20     # long polling — 빈 폴링 요금을 줄인다

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    # 🔴 이 값은 코드의 `MAX_RECEIVE_COUNT` 와 **같아야 한다**(`common/jobs.py`).
    #    어긋나면 워커가 "마지막 시도" 를 잘못 판단해서, 아직 재시도가 남았는데 FAILED 로
    #    마감하거나(유저가 성공할 수 있었던 잡을 잃는다) 끝났는데 안 마감한다(영원히 PENDING).
    maxReceiveCount = 3
  })
}
