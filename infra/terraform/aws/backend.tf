# Terraform state 원격 backend — S3. Proxmox 스택과 **같은 버킷·다른 key** 를 쓴다.
#
# key = tfstate/aws-crawl.tfstate   (Proxmox 는 tfstate/proxmox.tfstate)
#   같은 버킷을 쓰는 이유 = 잠금·자격증명·리전 배선을 이미 검증한 경로를 재사용하는 것이 싸다.
#   다른 key 를 쓰는 이유 = 크롤 인프라의 apply 가 클러스터 VM 을 건드릴 수 있으면 안 된다.
#
# 🔴 apply 하는 사람의 자격증명은 backend 용(`mp-backup`)과 **다를 수 있다** —
#    이 스택은 S3 버킷 생성·SQS 생성·**IAM 사용자 생성**을 한다. `mp-backup` 프로필은
#    백업 전용으로 발급된 키라 IAM 권한이 없을 가능성이 높다(근거: 그 자격증명으로
#    mp-backup-ap2 의 버전관리를 못 켰다 — ../backend.tf 주석). 권한 부족이면
#    var.profile 을 관리자 프로필로 바꿔서 apply 한다. backend 프로필은 backend.conf 가 따로 정한다.
#
#   terraform init -backend-config=backend.conf
terraform {
  backend "s3" {}
}
