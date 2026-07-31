# Terraform state 원격 backend — S3 (2026-07-29 이관, 런북 Q4).
#
# 🔴 왜 PG 백엔드를 버렸나: 종전 백엔드 = fb-data(.8) PG 의 terraform_state DB 였는데,
#    P2 에서 그 PG 자체가 Terraform 이 관리하는 클러스터(K8s) 위로 이사한다 —
#    "인프라를 만드는 도구의 상태가 그 인프라 안에 있는" 순환 의존이라 사전에 끊는다.
#    (VM PG 에 남은 terraform_state DB 는 이제 참조하지 않는다 — 런북 §4.1-⑤ 에서 DROP.)
#
# 설정 주입은 backend.conf(gitignored) — 키:
#   bucket / key / region / profile / use_lockfile
# 잠금 = S3 네이티브 락파일(use_lockfile, TF ≥1.10 — 현행 1.15.4). DynamoDB 불요(학생 예산).
# 자격증명 = ~/.aws 프로필 `mp-backup` (팀원별 로컬 배치 — credentials.env 와 같은 취급).
# ⚠️ 버킷 버전관리 OFF(콘솔 권한 밖 — status §4) → 이관 직전 state 사본을
#    s3://mp-backup-ap2/tfstate/pre-migration/ 에 남겨 보완한다.
#
#   terraform init -backend-config=backend.conf
terraform {
  backend "s3" {}
}
