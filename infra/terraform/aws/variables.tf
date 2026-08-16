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
  # 🔴 **365 → 30 (C-79 · 2026-08-16 감사에서 어긋남 발견).**
  #    종전 근거(*"구 Kafka DLQ 토픽의 대체물이라 사후분석용으로 더 오래 둔다"*)는 이 파일이
  #    쓰인 시점의 판단이고, **C-79(2026-08-13 사용자 확정)가 30일로 정했다.** 정본이 이긴다.
  #    🔵 잃는 것은 실질적으로 없다 — `failed/` 는 리파이닝이 실패한 원본이고 사후분석은
  #       며칠 안에 한다. 30일은 그것을 충분히 덮는다.
  description = "failed/ 보존일 (C-79 확정). 사후분석 창은 30일로 충분하다."
  type        = number
  default     = 30
}
