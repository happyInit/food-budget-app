output "bucket" {
  description = "크롤 운반 버킷 이름"
  value       = aws_s3_bucket.crawl.bucket
}

output "queue_urls" {
  description = "스트림별 SQS 큐 URL — 컨슈머 env(MP_SQS_URL)와 KEDA ScaledObject 에 그대로 들어간다"
  value       = { for k, _ in local.streams : k => aws_sqs_queue.stream[k].id }
}

output "dlq_urls" {
  description = "스트림별 DLQ URL — 객체 단위 실패(3회)가 여기 쌓인다. 알림 대상"
  value       = { for k, _ in local.streams : k => aws_sqs_queue.dlq[k].id }
}

output "iam_users" {
  description = "생성된 IAM 사용자. 액세스 키는 Terraform 이 만들지 않는다(README 참조)"
  value = {
    uploader       = aws_iam_user.uploader.name
    refiner_onprem = aws_iam_user.refiner_onprem.name
  }
}
