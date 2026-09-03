variable "region" {
  description = "AWS 리전."
  type        = string
  default     = "ap-northeast-2"
}

variable "profile" {
  description = "apply 에 쓰는 ~/.aws 프로필. 기본값을 두지 않는다 — 잘못된 프로필로 절반쯤 apply 되는 것보다 처음부터 멈추는 쪽이 싸다."
  type        = string
}

variable "availability_zone" {
  description = "Lightsail 가용영역. 🔴 인스턴스와 디스크가 여기 묶인다 — 나중에 옮길 수 없다."
  type        = string
  default     = "ap-northeast-2a"
}

variable "bundle_id" {
  description = <<-EOT
    Lightsail 요금제. medium_3_0 = 2 vCPU / 4 GiB / 80 GiB SSD / 4 TB 전송 / 월 $24.
    실측 소요 메모리는 앱 11종 1.33 GiB + 데이터 티어 1.22 GiB + OS 0.35 GiB = 약 2.9 GiB.
    모자라면 large_3_0(8 GiB, $44)로 올린다.
  EOT
  type        = string
  default     = "medium_3_0"
}

variable "blueprint_id" {
  description = "OS 이미지."
  type        = string
  default     = "ubuntu_24_04"
}

variable "ssh_allowed_cidr" {
  description = <<-EOT
    SSH(22) 허용 대역. 기본값이 전체 개방인 이유는 Lightsail 브라우저 SSH 콘솔이
    AWS 측 주소에서 붙기 때문이다(고정 대역이 공개돼 있지 않다).
    비밀번호 인증은 꺼져 있고 키 인증만 받는다. 접속을 본인 IP 로 좁히려면 여기를 바꾼다.
  EOT
  type        = string
  default     = "0.0.0.0/0"
}

variable "seed_bucket" {
  description = "초기 데이터(PG 덤프·ES 색인)와 백업이 오가는 S3 버킷."
  type        = string
  default     = "mp-backup-ap2"
}
