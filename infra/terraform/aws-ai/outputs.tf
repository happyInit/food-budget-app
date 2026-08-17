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
