# EventBridge Scheduler — 배치 3종.
#
# 🔴 **`enable_schedules` 기본값이 false 인 이유를 반드시 읽을 것**(variables.tf).
#    같은 일을 하는 K8s CronJob 이 EKS 에서 **지금 돌고 있다.** 둘 다 켜면 하루에 두 번 돌고,
#    리뷰 요약·감성은 유료 모델이라 **비용이 그대로 두 배**다. 켜기 전에 CronJob suspend 가 순서다.
#
# 🔵 EventBridge **Rule 이 아니라 Scheduler** 를 쓰는 이유 = **타임존을 그대로 준다.**
#    CronJob 이 `spec.timeZone: Asia/Seoul` 로 도는데 Rule 은 UTC 뿐이라, cron 을 손으로
#    변환해야 하고 «두 표현이 갈리는» 자리가 생긴다. 같은 시각을 두 문법으로 적으면 언젠가 어긋난다.

resource "aws_scheduler_schedule" "batch" {
  for_each = var.enable_schedules ? local.schedule_functions : {}

  name                         = "mp-ai-${each.key}"
  schedule_expression          = each.value.cron
  schedule_expression_timezone = "Asia/Seoul" # ← CronJob 의 spec.timeZone 과 같은 값

  # 정시에 돈다 — 배치 사이에 순서가 있다(가격 적재 → 이상탐지). 창을 열면 그 순서가 흔들린다.
  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.fn[each.key].arn
    role_arn = local.role_arns["scheduler"]

    # 🔴 `apply` 를 **명시적으로 준다.** 안 주면 배치가 **미리보기 모드**로 돌아 아무것도
    #    적재하지 않는다 — "돌긴 도는데 결과가 안 쌓인다" 는 실제로 밟은 사고다(2026-08-16,
    #    팀원이 발견). 내가 IAM·PVC·이미지·PG 까지 훑고도 **명령줄 플래그 하나**를 놓쳤다.
    input = jsonencode({ apply = true })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
