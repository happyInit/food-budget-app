# Terraform state 원격 backend — S3. aws-platform 과 **다른 버킷**을 쓴다.
#
# 🔴 같은 버킷(mp-backup-ap2)을 못 쓰는 이유 — `mp-dashboard-guardrails` 의 `DenyProtectedBuckets`
#    가 그 버킷을 explicit Deny 한다(`infra/iam/mp-dashboard/mp-dashboard-guardrails.json`).
#    같은 버킷을 쓰려면 그 Deny 를 풀어야 하는데, 그러면 이 스택의 apply 주체가 백업 버킷도
#    건드릴 수 있게 돼 C-77 의 격리 목적이 무너진다. ⇒ 스택을 쪼갠 김에 state 버킷도 쪼갠다.
#
# 잠금 = S3 네이티브 락파일(use_lockfile). 자격증명 = `mealplanning-dashboard` 그룹(mp-dashboard-dev
# + mp-dashboard-ops + mp-dashboard-guardrails 부착)이 붙은 개인 프로필 — `mp-dashboard-dev` 의
# `TerraformStateForDashboardStack` Sid 가 이 버킷 하나에만 s3:* 를 허용한다.
#
#   terraform init -backend-config=backend.conf
terraform {
  backend "s3" {}
}
