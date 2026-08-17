# Terraform state 원격 backend — S3. 네 스택이 **같은 버킷·다른 key** 를 쓴다.
#
#   tfstate/proxmox.tfstate       ../              (온프렘 VM)
#   tfstate/aws-crawl.tfstate     ../aws/          (크롤 S3·SQS)
#   tfstate/aws-platform.tfstate  ../aws-platform/ (VPC·EKS·ALB)
#   tfstate/aws-ai.tfstate        여기              ← AI 서버리스
#
# 🔴 **apply 프로필 ≠ backend 프로필.** backend 는 `mp-backup`(S3 만)로 충분하지만, 이 스택은
#    Lambda·SQS·S3·Scheduler 를 만든다. ⇒ `var.profile` 에 AI 배포용 프로필을 따로 준다
#    (권한요청서 A안 = `lambda:*` + 범위 제한 `iam:PassRole` + `scheduler:*`).
#
#   terraform init -backend-config=backend.conf
terraform {
  backend "s3" {}
}
