# 알람 알림 목적지 — 🔵 **토픽과 구독만** Terraform 이 갖는다.
#
# 🔴 알람(`aws_cloudwatch_metric_alarm`)은 여기 없다. `serverless/alarms.sh` 로 옮겼다 —
#    프로바이더가 refresh 때 알람 태그를 읽는데 `cloudwatch:ListTagsForResource` 가
#    `mp-ai-dev` 에 없어서 **`plan` 이 매번 AccessDenied 로 죽었다**(2026-08-17 실측).
#    자원 하나가 스택 전체를 못 쓰게 만드는 상황이라, 그 하나만 밖으로 뺐다.
#    🔵 SNS 는 `sns:*` 가 `mp-ai-*` 에 있어서 태그 읽기까지 통한다 — 그래서 여기 남는다.
resource "aws_sns_topic" "alerts" {
  name = "mp-ai-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.alert_emails)

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
  # ⚠️ 이메일 구독은 **수신자가 확인 메일을 눌러야** 활성화된다. 누르기 전까지 `PendingConfirmation`
  #    이고 알람이 도착하지 않는다 — 걸어 놓고 확인을 안 하는 것은 «구독이 없는 것» 과 같다.
}
