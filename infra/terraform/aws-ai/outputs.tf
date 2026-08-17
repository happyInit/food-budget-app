output "functions" {
  description = "만들어진 함수 이름 → ARN. 🔵 배선이 안 갖춰진 함수는 **여기 없다**(locals.ready)."
  value       = { for k, f in aws_lambda_function.fn : k => f.arn }
}

output "not_created" {
  description = <<-EOT
    🔴 **만들지 않은 함수와 그 이유.** 조용히 빠지면 «올렸는데 왜 안 도나» 가 되므로 드러낸다.
    비우려면 variables.tf 의 `pg_host`·`es_host`·`valkey_host` 를 채운다(선행 = docs/serverless/06).
  EOT
  value = {
    for k, f in local.functions : k => join(", ", [for n in f.needs : "${n}_host 미설정" if !local.have[n]])
    if !contains(keys(local.ready), k)
  }
}

output "queue_urls" {
  value = { for k, q in aws_sqs_queue.jobs : k => q.url }
}

output "upload_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "alb_routes_enabled" {
  description = "🔴 true 면 해당 경로를 **파드가 아니라 Lambda 가 받고 있다**."
  value       = var.enable_alb_routes
}

output "alerts_topic" {
  description = <<-EOT
    알람 SNS 토픽. 🔵 **토픽만 Terraform 이 갖는다** — 알람 자체는 `serverless/alarms.sh` 다.
    프로바이더가 refresh 때 알람 태그를 읽는데 `cloudwatch:ListTagsForResource` 가 없어
    **`plan` 이 매번 죽었다**(자원 하나가 스택 전체를 못 쓰게 만든다). 근거 = 그 스크립트 머리말.
  EOT
  value       = aws_sns_topic.alerts.arn
}

output "alerts_warning" {
  description = "🔴 구독자가 없으면 알람은 장식이다 — 그 상태를 출력으로 드러낸다."
  value = length(var.alert_emails) == 0 ? join("", [
    "🔴 alert_emails 가 비어 있다 — `serverless/alarms.sh` 가 만든 알람이 **아무에게도 안 간다.** ",
    "`alert_emails = [...]` 를 채우고 apply 한 뒤, 받은 확인 메일을 반드시 누를 것.",
  ]) : "OK: ${length(var.alert_emails)}명 구독(각자 확인 메일을 눌러야 활성)"
}
