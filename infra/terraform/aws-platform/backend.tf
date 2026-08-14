# Terraform state 원격 backend — S3. 세 스택이 **같은 버킷·다른 key** 를 쓴다.
#
#   tfstate/proxmox.tfstate       ../          (온프렘 VM)
#   tfstate/aws-crawl.tfstate     ../aws/      (크롤 S3·SQS)
#   tfstate/aws-platform.tfstate  여기          ← C-77 이 지정한 key
#
# 같은 버킷을 쓰는 이유 = 잠금·자격증명·리전 배선을 이미 검증한 경로를 재사용하는 것이 싸다.
# key 를 가르는 이유 = **이 스택의 apply 가 클러스터 VM 이나 크롤 큐를 건드릴 수 없어야 한다**(C-77).
#
# 🔴 **apply 프로필 ≠ backend 프로필.** backend 는 `mp-backup`(S3 만) 으로 충분하지만,
#    이 스택은 **VPC·EKS·IAM 롤·ECR** 을 만든다. `mp-backup` 은 백업 전용으로 발급된 키라
#    거의 확실히 부족하다(근거: 그 자격증명으로 mp-backup-ap2 의 버전관리조차 못 켰다 —
#    ../backend.tf 주석). ⇒ `var.profile` 에 **플랫폼 권한 프로필**을 따로 준다.
#
# ⚠️ 버킷 버전관리 OFF → apply 전에 state 사본을 s3://mp-backup-ap2/tfstate/pre-migration/ 에 남긴다.
#
#   terraform init -backend-config=backend.conf
terraform {
  backend "s3" {}
}
