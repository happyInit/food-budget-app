# state = S3 원격 backend. 잠금은 S3 네이티브 락파일(use_lockfile) — DynamoDB 불요.
#
#   terraform init -backend-config=backend.conf
terraform {
  backend "s3" {}
}
