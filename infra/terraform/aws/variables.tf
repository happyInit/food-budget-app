variable "region" {
  description = "AWS 리전. 백업 버킷(mp-backup-ap2)·이관 대상 EKS 와 같은 리전이어야 한다."
  type        = string
  default     = "ap-northeast-2"
}

variable "profile" {
  description = <<-EOT
    apply 에 쓰는 ~/.aws 프로필. 🔴 S3 버킷·SQS 큐·**IAM 사용자** 생성 권한이 필요하다 —
    백업 전용 프로필(mp-backup)로는 부족할 수 있다(backend.tf 주석 참조).
  EOT
  type        = string
  default     = "mp-backup"
}

variable "bucket_name" {
  description = "크롤 운반 버킷. 백업 버킷과 반드시 분리한다 — 수명주기·권한·삭제정책이 전혀 다르고, 업로더 키가 백업 버킷을 스치면 안 된다."
  type        = string
  default     = "mp-crawl-ap2"
}

variable "incoming_expire_days" {
  description = "incoming/ 보존일. PG crawl_raw 가 원문을 이미 durable 하게 갖고 있으므로 S3 사본은 재처리(replay) 용도다. 4.7MB/일 × 90일 ≈ 423MB ≈ 월 $0.01."
  type        = number
  default     = 90
}

variable "failed_expire_days" {
  description = "failed/ 보존일. 구 Kafka DLQ 토픽의 대체물이라 사후분석용으로 더 오래 둔다."
  type        = number
  default     = 365
}
