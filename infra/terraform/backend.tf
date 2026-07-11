# Terraform state 원격 backend (PostgreSQL, fb-data)
# conn_str 은 backend.conf(gitignored)로 주입:
#   terraform init -backend-config=backend.conf
terraform {
  backend "pg" {}
}
